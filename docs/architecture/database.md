# Данные и миграции

## Текущее состояние

PostgreSQL 17, SQLAlchemy 2.0 async с asyncpg, Alembic через `run_sync`.
После пустого baseline `0001_foundation` ревизия `0002_compact_analysis`
создаёт две предметные таблицы: `beatmap_inputs` и `analysis_results`.
Ревизия `0003_osu_metadata` добавляет третью — `osu_beatmap_matches` для
отдельного кеша metadata, полученной при явной сверке с сайтом.
Ревизия `0004_sources` добавляет четвёртую — `beatmap_sources`: происхождение
download bytes и версии metadata adapter, отдельно от официального API match.
Решение о временном входе и компактных результатах:
[ADR-0003](../adr/0003-transient-inputs-compact-results.md).

Сырые `.osu`, архивы, hit objects, slider anchors и timing points в БД
не сохраняются. Reader разбирает объекты в памяти отдельного CPU-процесса;
из процесса возвращаются только metadata, settings, версии и измерения.
HTTP-сценарий вообще не создаёт файлов: ограниченный вход существует в памяти
на время обработки. Локальная команда `extract-osz` остаётся отдельным
инструментом подготовки исследовательского корпуса с явным output-dir;
её файлы не являются постоянным хранилищем HTTP-сервиса и не удаляются импортом.

## Идентичность входа: beatmap_inputs

Одна строка описывает точные исходные байты одного `.osu`. Это fingerprint
версии файла с компактной metadata, а не сохранённая карта или подтверждённая
запись osu! API.

| Поля | Представление и ограничения |
| --- | --- |
| `id`, `created_at` | Локальный `BIGINT IDENTITY`; время с часовым поясом |
| `source_sha256` | `BYTEA`, ровно 32 байта, `UNIQUE`; ключ дедупликации входа |
| `source_md5` | `BYTEA`, ровно 16 байт, обычный индекс; атрибут для совместимого checksum lookup |
| `byte_size`, `format_version`, `ruleset` | Положительный размер и версия формата; текущий ruleset строго 0 |
| `claimed_beatmap_id`, `claimed_beatmap_set_id` | Nullable положительные IDs из файла; обычный индекс только по ID карты |
| `title`, `artist`, `creator`, `difficulty_name` | Ограниченные строки: 512, 512, 256 и 512 символов соответственно |
| `metadata_parser_version` | Версия reader, которым впервые получена сохранённая metadata |

SHA-256 и MD5 вычисляются по одному и тому же snapshot исходных байтов.
В HTTP-ответе digest представлен hex-строкой; в PostgreSQL он хранится в
двоичном виде. MD5 не обеспечивает уникальность: разные SHA-256 допускаются
при одинаковом MD5. Внешний lookup реализован в явном `verify-osu` сценарии.

IDs внутри пользовательского `.osu` остаются claims. Без явной сверки ответ
содержит `identity_status="unverified"`; при наличии соответствующей строки
`osu_beatmap_matches` — `checksum_match` и отдельную API metadata с временем.
Отдельного scalar столбца статуса в input нет. Claimed IDs не уникальны: несколько
изменённых файлов могут заявлять один BeatmapID и BeatmapSetID. Отсутствующие
IDs, 0 и -1 reader переводит в `NULL`. Поиск по claimed ID находит утверждения
файлов, а не доказывает соответствие официальной карте. Поэтому сейчас нет
таблиц Beatmap/BeatmapSet с уникальными внешними ID и авторитетной связью с сайтом.

Любое изменение байтов, включая игнорируемую ссылку на видео, создаёт другой
SHA-256 и отдельный вход. Совпадение измерений не объединяет такие входы.
Повторный импорт существующего SHA-256 не перезаписывает metadata, MD5 или
`metadata_parser_version`. Неизменяемость обеспечивается текущим сценарием
записи без `UPDATE`; SQL-триггера, запрещающего изменения администратору, нет.

## Metadata сайта: osu_beatmap_matches

Одна строка на input, `input_id` одновременно PK и FK с `ON DELETE RESTRICT`.
Хранит API beatmap/set IDs, 16-байтовый MD5, title/artist, `set_creator`, creator ID,
difficulty name, status, `last_updated`, `fetched_at`, API response version и
metadata schema version. Строки имеют те же ограничения длины, что API DTO;
MD5 length и положительные IDs дополнительно проверяются БД.

Repository сравнивает checksum с `beatmap_inputs.source_md5` до upsert. Это
application invariant: SQL CHECK не сравнивает digest с другой таблицей.
Связь не перезаписывает metadata файла. Более старое время наблюдения не может
заменить свежее при конкурентной проверке. Это обновляемый кеш metadata;
история изменений API не сохраняется, количественные метрики сюда не входят.
По beatmap_id есть неуникальный индекс; один сайт ID может иметь несколько inputs.

Analysis query использует LEFT JOIN, поэтому отсутствие сверки сохраняет
доступность raw результатов. Positive cache в БД действует по `fetched_at`
и TTL; GET читает даже старое наблюдение со временем, refresh выполняется явно.
Подробности: [osu-api](osu-api.md), [ADR-0005](../adr/0005-osu-checksum-metadata.md).

## Download observations: beatmap_sources

Связь many-to-one с input через `ON DELETE RESTRICT`. Уникален ключ
`(input_id, provider, requested_beatmap_id, adapter_version, metadata_schema_version)`.
Новая версия adapter/schema остаётся отдельным observation; в одной комбинации
более свежий `file_fetched_at` может обновить запись. Это не полный журнал попыток.

Столбцы: provider (пока CHECK hinamizawa), requested map ID, metadata set ID,
16-байтовый metadata MD5, adapter/schema versions, metadata last_updated/fetched_at,
file_fetched_at, nullable metadata/file source layers, freshness и ETag. Строки
bounded; нет JSON, raw bytes, media paths или object arrays. SHA-256 уже есть в input.

Application/repository проверяют receipt против hashes и file claims input;
source и новый analysis сохраняются одной транзакцией. Source constraint failure
откатывает input/result. По requested ID есть неуникальный индекс; разные bytes
с одним ID не объединяются. GET/list группируют source observations отдельно,
не умножая строки пагинации. Mirror source не меняет статус официальной сверки.
Контракт: [mirror-import](mirror-import.md).

## Результаты: analysis_results

Каждый результат связан с `beatmap_inputs.id` внешним ключом с
`ON DELETE RESTRICT`. Уникальна комбинация
`(input_id, algorithm_version, parser_version, configuration_sha256)`.
Один исходник может иметь несколько результатов для разных версий алгоритма,
reader или параметров. Повтор той же комбинации возвращает существующую строку.

Settings сохранены типизированными столбцами: HP, CS, OD, AR,
`slider_multiplier`, `slider_tick_rate` и `stack_leniency`. Это исходные
значения после defaults reader, без применения mods и игровой нормализации.
Текущий `basic-raw/1` хранит ещё 22 скалярных признака:

| Группа | Столбцы |
| --- | --- |
| Объекты | `hit_object_count`, `circle_count`, `slider_count`, `spinner_count` |
| Timing points | `timing_point_count`, `red_timing_point_count`, `inherited_timing_point_count` |
| Red BPM | `red_bpm_min`, `red_bpm_max` |
| Начала объектов | `first_object_start_ms`, `last_object_start_ms`, `object_start_span_ms` |
| Пары голов circle/slider | `head_object_count`, `head_pair_count` |
| Интервалы голов | `head_interval_min_ms`, `head_interval_max_ms`, `head_interval_mean_ms`, `head_interval_median_ms`, `zero_head_interval_count` |
| Расстояния голов | `raw_head_distance_min_px`, `raw_head_distance_max_px`, `raw_head_distance_mean_px` |

Агрегат без наблюдений равен `NULL`, например расстояния при отсутствии пары
голов. Границы времени относятся к началам объектов и не являются полной
длительностью карты. Формулы и ограничения определены в
[basic-features](basic-features.md). Star rating, PP,
skill profile и турнирные слоты этими измерениями не подменяются.

`configuration` — единственный JSONB-столбец: небольшой объект параметров,
а не feature vector или копия разобранной карты. PostgreSQL проверяет
`jsonb_typeof(configuration) = 'object'` и
`octet_length(configuration::text) <= 4096`. Индекса GIN нет. Текущая
конфигурация задаёт ruleset 0, пустые mods, raw coordinate space и лимиты reader;
настройка произвольных mods через HTTP не реализована.

Application канонизирует конфигурацию через `json.dumps` с `sort_keys=True`,
`separators=(",", ":")`, `allow_nan=False`, затем считает SHA-256 UTF-8 строки.
В `configuration_sha256` хранится 32-байтовый digest. Его соответствие JSON
задаёт preparation-код; БД проверяет длину, но сама digest не пересчитывает.
Версии алгоритма и reader хранятся непосредственно в результате; отдельных
справочников AlgorithmVersion или AnalysisJob в текущей схеме нет.

Количество полей входа и результата не зависит от числа объектов карты.
Ограниченные metadata и configuration остаются переменными по размеру;
конкретная стоимость строки/индексов не заявляется без измерения PostgreSQL.
Новые устойчивые признаки добавляются миграциями как типизированные поля,
без массива hit objects или бесконтрольного JSONB с результатами.

## Транзакции и конкурентные повторы

Reader и вычисления завершаются до открытия транзакции. Application выполняет
`async with session.begin()` для сохранения входа и результата вместе.
Ошибки результата или приложения откатывают обе вставки, не оставляя новый
вход без результата. Repository не делает неявный commit; закрытие сессии с
незавершённой транзакцией также откатывает изменения.

Каждая конкурентная операция использует отдельную сессию. Вход вставляется
через `INSERT ... ON CONFLICT DO NOTHING RETURNING id`. При конфликте отдельный
`SELECT` получает существующий ID с новым snapshot при стандартном
`READ COMMITTED`. Та же схема применяется к уникальному ключу результата.
Нет предварительного `SELECT` с последующей незащищённой вставкой и нет
перезаписи через `ON CONFLICT DO UPDATE`.

Ограничения уникальности дают одну строку входа и результата даже при
конкурентных импортах одной комбинации. Они не гарантируют единственное
выполнение CPU-расчёта: конкуренты могут независимо посчитать одинаковые
признаки. Поле `created` в результате сохранения означает новую строку анализа.
Долговечные retry/lease/outbox и состояния заданий M2 описаны в
[batch-processing](batch-processing.md); result и job success — две транзакции,
поэтому повтор CPU после crash возможен, уникальность результата сохраняется.

## Повторный анализ после освобождения входа

Checksum, metadata и версии позволяют проверить происхождение результата,
но не восстановить исходные байты или объекты. Для расчёта новым алгоритмом
нужно снова получить `.osu` и проверить его SHA-256. Карта с тем же BeatmapID,
но другим SHA-256 — новый вход; доступность исторической версии на сайте не
гарантируется. Поэтому повторяемость расчёта требует одновременно прежнего
исходника, соответствующего кода, reader и конфигурации.

Повтор анализа требует нового получения bytes: upload или mirror import с SHA-256
pin прежнего input. Доступность точной редакции у зеркала не гарантируется. Жизненный
цикл ограничен обработкой в памяти; это не обещание криптографического
стирания RAM или немедленной остановки уже запущенного процесса при отмене
HTTP-запроса. Если позднее worker потребует staging на диске, срок хранения,
очистка при ошибках и retry должны быть определены отдельно.

## Миграции и проверки

`Base.metadata` задаёт имена PK/FK/unique/index/check constraints. Миграции
запускаются отдельной командой, не из startup и не через `create_all()`.
Помимо digest/JSON-ограничений БД проверяет согласованность object/timing/head
counts и диапазоны settings. Алгоритмический контракт и hash конфигурации
остаются ответственностью application/analysis.

Интеграционные тесты требуют реальный PostgreSQL и БД с суффиксом `_test`.
Alembic поднимает схему в изолированном случайном namespace; тест миграций
выполняет upgrade, повторный upgrade, `alembic check`, downgrade и upgrade.
[Persistence tests](../../tests/integration/test_analysis_persistence.py)
проверяют конкурентную дедупликацию, неизменяемую metadata, различия версий,
rollback, одинаковые claimed IDs/MD5, пагинацию, nullable measurements,
отказ при большом configuration и фактическое отсутствие массивов/feature blob.
SQLite и `create_all()` эти проверки не подменяют.

## Расширение difficulty/pp — принятое направление

Текущие raw результаты и 22 поля не объявляются окончательной моделью всех метрик.
Перед подключением внешнего вычислителя добавятся отдельные типизированные
семейства difficulty/performance и provenance engine/build/upstream/adapter/schema.
Новые столбцы вводятся миграциями, старые snapshots сохраняются. Performance
потребует score/scenario и связи с соответствующим difficulty snapshot.
Эти таблицы/поля пока не созданы; текущий runtime хранит только `basic-raw/1`.
Контракт: [metric-evolution](metric-evolution.md),
[ADR-0004](../adr/0004-versioned-metric-families.md).

В первом срезе M2 provenance уже реализован в `beatmap_sources`.
Download provider и официальный checksum verification
не взаимозаменяемы; `osu_beatmap_matches` не принимает mirror metadata как данные
официального API. Revision `0005_batch_jobs` добавила ещё три таблицы:
`analysis_batches` (UUID key/request hash/pipeline identity), `analysis_jobs`
(один item/job, state/attempts/run_after/delivery_after/lease/pins/result/error),
`provider_budgets` (общий Hinamizawa pacing/cooldown). Только типизированные поля,
без payload JSON/source bytes/object arrays. Job rows содержат последнее состояние,
не журнал попыток. Контракт: [batch-processing](batch-processing.md).
