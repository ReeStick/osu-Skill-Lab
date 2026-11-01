# Текущее состояние

## 2026-11-01 — Карта и простая разметка

- [x] Новый `/lab`: коллекция, проверка одного тега, optimistic undo.
- [x] Локальный checksum-verified browser preview .osu + отдельное audio.
- [x] Cursor/search каталога; старые эксперименты сохранены в `/lab/research`.
- [x] Автоматическая групповая partition новых решений, прежние роли сохранены.
- [x] JS/targeted Python и Chromium smoke; подробнее в [devlog](docs/devlog/2026-11-01-map-first-workbench.md).
- [ ] PostgreSQL integration и Docker проверка новой версии в среде с сервисами.
- [ ] Точное отображение stacking/ticks и получение исходников без ручного выбора.

Контракт: [ADR-0011](docs/adr/0011-map-first-workbench.md). Ниже — история предыдущих срезов.

Передача контекста: [HANDOFF](HANDOFF.md). По замечаниям владельца переработан `/lab`:
аналитика и разметка разделены, выбор карт справа, светлая/спокойная тёмная темы,
multi-tag click/drag-and-drop, signed metric contributions и мини-гистограммы.
Приоритет остаётся за обсуждением UI; M3 и полный M4 не закрыты.

## Доработка UI по обратной связи

- [x] Карточки карт справа с выделением активной difficulty и общим выбором для двух видов.
- [x] «Аналитика»: явные вклады метрик, распределения, свёрнутые настройки и обучение.
- [x] «Разметка»: несколько тегов на карту, click/drag-and-drop, явные no/unsure и undo.
- [x] Светлая и спокойная тёмная темы с сохранением выбора в браузере.
- [x] Рассмотрен переход в локальный editor; интеграция не реализована по текущему запросу.
- [ ] Настоящий SR — следующий срез вместе с difficulty engine; сейчас честное `★ —`.

Контракт: [label-workbench](docs/architecture/label-workbench.md),
проект editor handoff: [client-handoff](docs/architecture/client-handoff.md),
проверки и локальный режим запуска: [devlog UI](docs/devlog/2026-10-26-ui-feedback.md).

**Milestone 0 — Project Foundation завершён** (2026-10-25).
**Milestone 1 — Beatmap Analysis MVP завершён** (2026-10-25).
**M1a — osu! API metadata/identity завершён** (2026-10-25), включая живую OAuth-сверку.
**M2 — Batch Import & Background Processing завершён** (2026-10-26).
Текущий этап — M3: работает CPU runtime foundation с configurable worker capacity.
SR/pp engine, автоматические tag providers и GPU ещё не реализованы.
По согласию владельца добавлен ранний срез M4: локальная разметка и logistic baseline.

## Ранний M4 — гибридный workbench

- [x] `/lab`: каталог тегов/definitions, ручные yes/no/unsure, контрольные карты и undo.
- [x] Append-only labels и optimistic guard, immutable версии правил и моделей.
- [x] Web Worker preview на готовых фичах; threshold переиспользует scoring cache.
- [x] Train-only preprocessing и logistic baseline в отдельном CPU-процессе.
- [x] Контрольные set groups исключены из train; model lineage/profile/artifact hashes.
- [x] `0006_label_lab`: пять используемых таблиц, отдельное хранение model JSON artifacts.
- [x] Целевые PostgreSQL/CPU/JS и Chrome-сценарии; Docker API с локальным UI.
- [ ] Собрать реальные labels, grouped final test, оценить ошибки/качество/latency.
- [ ] Подключить проверенные difficulty/pp components и providers M3.

Контракт: [label-workbench](docs/architecture/label-workbench.md),
решение: [ADR-0010](docs/adr/0010-hybrid-label-workbench.md).
Проверки и ограничения: [devlog](docs/devlog/2026-10-26-label-workbench.md).
M3 и полный M4 не закрыты; ранний UI — согласованное изменение порядка работ.

## Первый runtime срез M3 — очередь и мощность worker

- [x] Общая durable runtime queue M2; один item/job на карту, отдельный worker процесс.
- [x] Worker concurrency 1..32 через env/CLI; default 1, отдельная настройка на машине.
- [x] Одно N для broker prefetch, handler/import slots и CPU processes.
- [x] Per-ID import gates, parallel different maps, bounded cache/admission.
- [x] TaskGroup shutdown/redelivery и fatal CPU restart, прежние leases/retry/budget.
- [x] PostgreSQL/RabbitMQ проверки двух consumers capacity 1+2, CPU results и shutdown.
- [x] Docker build/start с capacity 3 и живой batch двух IDs completed.
- [ ] Следующий срез: точный difficulty provider/component coverage и provenance/DDL.

Контракт: [runtime-workers](docs/architecture/runtime-workers.md),
[ADR-0009](docs/adr/0009-worker-concurrency.md),
проверки: [devlog](docs/devlog/2026-10-26-runtime-worker-concurrency.md).

## Уточнение M3 — определения тегов и compute budget

- [x] Общие difficulty/pp и компоненты, раздельные snapshots и score context обязательны.
- [x] Каталог immutable tag definitions/bundles; методы и scope map/segment отделены от measurements.
- [x] Typed feature families, sparse assignments и явная семантика unknown/partial coverage.
- [x] Providers/dependencies/profile identity с будущими timing/slider geometry/ML stages.
- [x] Мягкий target 30000 ms, отдельные queue/acquisition timings, будущие CPU/GPU capabilities.
- [x] Сохранены временные source/tensors; модель/пороги/preprocessing требуют provenance.
- [ ] Выбрать точную ревизию engine, проверить доступность компонентов и реализовать первый adapter/DDL.
- [ ] Реализовать providers/tag foundation и измерить pipeline до обещаний latency/throughput.

Контракт: [tag-pipeline](docs/architecture/tag-pipeline.md),
решение: [ADR-0008](docs/adr/0008-extensible-tags-and-compute-budget.md),
критерии: [M3](docs/milestones/003-feature-engineering.md).

## Завершение M2 — долговечные пакеты и worker

- [x] POST/GET `/analysis-batches`, UUID Idempotency-Key, 100 IDs, dedup/pins и cancel.
- [x] `0005_batch_jobs`: batch/jobs, bounded admission, outbox intent и provider budget.
- [x] RabbitMQ persistent/confirmed notifications, отдельные dispatcher/worker, fenced leases.
- [x] Пять попыток с backoff/Retry-After, partial success, expired leases и duplicate delivery.
- [x] Общий Hinamizawa pacing/cooldown для API и workers; официальный verify независим.
- [x] SHA-256 фиксируется до CPU и проверяется на retry; bytes только RAM, disk staging не нужен.
- [x] Algorithm/parser/config identity при acceptance; несовместимый pipeline не подменяется.
- [x] Целевые PostgreSQL/RabbitMQ/CPU проверки и Docker запуск; независимые unit пропущены.
- [x] Живой batch: два уникальных IDs, оба succeeded; analysis №1 переиспользован.

Решение: [ADR-0007](docs/adr/0007-durable-batch-delivery.md).
Контракт: [batch-processing](docs/architecture/batch-processing.md).
Проверки: [devlog](docs/devlog/2026-10-26-durable-batch-processing.md).

## Последний срез M2 — рабочий mirror import

- [x] ID-only batch metadata adapter: до 100 ID, dedup и полный partition response.
- [x] Bounded raw `.osu`, checksum pin, mode/encoding/body checks и source cooldown.
- [x] `POST /imports/hinamizawa/{id}`, 201/200 и get/list с отдельным source DTO.
- [x] `beatmap_sources` + Alembic `0004_sources`, atomic save и versioned observations.
- [x] Fresh known official checksum проверяется до download; mirror не создаёт official match.
- [x] 111 уникальных целевых cases проверены несколькими прогонами; независимые unit пропущены.
- [x] Docker и живой import одной `.osu` 112 844 bytes; SHA pin совпал, analysis №1 переиспользован.
- [x] Durable batch/jobs, RabbitMQ/worker, RAM input/retry и общий provider budget.

Контракт: [mirror-import](docs/architecture/mirror-import.md).
Проверки: [devlog](docs/devlog/2026-10-25-hinamizawa-import.md).

## Уточнение M2 — пакетный импорт через зеркала

- [x] Предложение владельца: batch input и дополнительный mirror source при official 429.
- [x] Проверены Hinamizawa metadata/raw/download/pack/rate-limit contracts.
- [x] Batch lookup до 100 ID/MD5 возвращает metadata; произвольный список raw files
  получается ограниченными отдельными запросами, не одним upstream batch body.
- [x] Принят ADR-0006: sources/provenance, отдельные cooldowns, partial items и staging.
- [x] Пункт 6 ADR-0005 частично заменён: mirror разрешён как самостоятельный источник,
  текущий официальный OAuth/verify-osu на него не перенаправляется.
- [x] Реализовать download adapter и HTTP import одной difficulty.
- [x] Реализовать M2 batch endpoint, durable jobs и worker.

Проект: [batch-import](docs/architecture/batch-import.md).
Проверки: [devlog](docs/devlog/2026-10-25-mirror-batch-plan.md).

## Последний срез M1a — явная сверка с osu! API

- [x] Optional OAuth client credentials/public, tokens в RAM, парные настройки и Compose.
- [x] `POST /analyses/{id}/verify-osu`, lookup только по сохранённому MD5.
- [x] Отдельная типизированная metadata-таблица с миграцией `0003_osu_metadata`.
- [x] `checksum_match`, API metadata/time, nullable сравнение file claims; исходные claims/results сохранены.
- [x] Positive TTL в БД, bounded memory cache, pacing, 401 retry один раз, 429 cooldown.
- [x] Body/time limits, безопасные 404/409/422/429/502/503/504; отмена/перегрузка.
- [x] 259 passed: 236 unit и 23 real PostgreSQL integration, без skip.
- [x] Ruff lint/format (последняя проверка: 83 файла), mypy (51 файл), locked offline sync.
- [x] Docker build/run, health 200; текущая БД на head, `alembic check` без drift.
- [x] Disabled OAuth в Docker даёт ожидаемый 503 `osu_not_configured`, анализ читается.
- [x] После обрыва восстановлен Docker Engine; повторно 23 PostgreSQL integration passed.
- [x] Download/attributes API исследованы: архивный lazer route не используется,
  количественные attributes не сохраняются до реализации ADR-0004.
- [x] Живая OAuth-сверка: анализ №1 → osu! beatmap 1960574, HTTP 200, IDs совпали.
- [x] Повтор и GET вернули тот же результат; metadata cache переиспользован,
  features/версии/время создания сохранены. Неизменённые unit-тесты не перезапускались.

Контракт: [osu-api](docs/architecture/osu-api.md),
[ADR-0005](docs/adr/0005-osu-checksum-metadata.md).
Фактические проверки: [devlog](docs/devlog/2026-10-25-osu-api-verification.md).

## Уточнение перед osu! API и metric engineering

- [x] Базой выбора difficulty/pp-метрик служат официальный код и релизы osu!.
- [x] Проверены текущие upstream difficulty/performance attributes и документация API.
- [x] Принят ADR-0004: отдельные семейства, engine/build/upstream/adapter/schema
  versions, явный score context и миграции новых типизированных полей.
- [x] Зафиксировано: текущий `basic-raw/1` — baseline, не финальный набор метрик.
- [x] Ближайший срез API выделен перед очередью; difficulty engine — начало M3,
  собственные метрики позже. Контракт difficulty/pp пока проектный.

Контракт: [metric-evolution](docs/architecture/metric-evolution.md).
История: [devlog](docs/devlog/2026-10-25-metric-evolution-plan.md).

## Последний срез M1 — компактный анализ через REST

- [x] Уточнение владельца: исходники и объекты временные; metadata и результаты постоянные.
- [x] Две таблицы с миграцией `0002_compact_analysis`, без raw/objects blobs.
- [x] SHA-256 входа и MD5, непроверенные claimed IDs; отсутствие ложной unique-связи с сайтом.
- [x] 22 математически определённых скалярных признака `basic-raw/1`.
- [x] Версии reader/алгоритма, canonical configuration hash, ограниченный JSONB конфигурации.
- [x] Атомарное сохранение и дедупликация, включая шесть одновременных транзакций.
- [x] Два CPU-процесса и два слота на экземпляр; отмена запроса не освобождает работающий CPU-слот.
- [x] Raw upload до 4 MiB, HTTP 201/200, чтение результата и cursor pagination.
- [x] Проверка NUL metadata, bigint HTTP IDs, 413/415/422/429/503 и отсутствия деталей БД.
- [x] 196 тестов passed: 178 unit и 18 real PostgreSQL integration, без skip.
- [x] Ruff lint/format, mypy (41 файл), `uv sync --locked --offline` — успешно.
- [x] Миграции upgrade/check/downgrade/repeat в изолированных схемах; рабочая БД на head.
- [x] Docker build/run; 33 реальные карты → 33 inputs + 33 results, 26 400 объектов.
- [x] Повтор upload возвращает прежний результат; GET сверены со всеми 33 ответами POST.
- [x] Замер PostgreSQL: строки 28 464 байта; таблицы с индексами 172 032 байта.
- [x] Исходный корпус и пользовательская правка `.gitignore` сохранены; push не выполнялся.

Контракты: [database](docs/architecture/database.md),
[basic-features](docs/architecture/basic-features.md),
[ADR-0003](docs/adr/0003-transient-inputs-compact-results.md).
Проверки: [devlog](docs/devlog/2026-10-25-compact-analysis-pipeline.md).

## Последний срез M1 — аналитические данные .osu

- [x] Чистый reader v14/UTF-8 для osu!standard, без зависимости от ORM/FastAPI.
- [x] Metadata/IDs, AR/OD/CS/HP, slider settings, stack leniency.
- [x] Red/green timing points; circles, slider anchors/spans/length, spinner end.
- [x] Медиа, samples и storyboard игнорируются; raw/effective значения разделены.
- [x] Version/limits/checksum, ошибки по строкам, стабильная сортировка объектов.
- [x] CLI `inspect-osu` для файла/каталога; JSON-сводки, explicit recursion.
- [x] 70 новых тестов: 67 parser + 3 CLI. Всего 126 unit passed, 4 integration deselected.
- [x] Ruff/format, mypy (26 файлов), актуальность lock; новых зависимостей нет.
- [x] Все 33 карты прочитаны: 26 400 объектов и 6 377 timing points, без warnings.
- [x] `data/map-summaries.jsonl` создан локально; в Git не включён.

Контракт: [osu-parser](docs/architecture/osu-parser.md).
История: [devlog](docs/devlog/2026-10-25-analytical-osu-reader.md).

## Предыдущий срез M1 — локальные архивы

- [x] CLI для одного `.osz` или каталога, без БД и HTTP.
- [x] Ограниченное извлечение только `.osu`, CRC и SHA-256, стабильный manifest.
- [x] Проверка опасных путей, duplicates, symlink/encrypted members и byte limits.
- [x] Публикация целого результата, проверка повторного запуска без перезаписи.
- [x] 35 новых тестов; общий unit-прогон: 56 passed, 4 integration deselected.
- [x] Ruff и форматирование; mypy: 21 файл без ошибок; lock актуален.
- [x] Локальный корпус: 12 `.osz` → 33 `.osu` (1 413 043 байта), 12 manifests.
- [x] Побайтовое сравнение со всеми исходными ZIP members; повтор: reused=true для 12.
- [x] Исходники и результаты исключены из Git; реальных карт в CI нет.

Контракт: [local-import](docs/architecture/local-import.md).
История: [devlog](docs/devlog/2026-10-25-local-osz-extraction.md).

## Завершённый M0

- [x] Компактный `src`-пакет, pyproject и Python 3.12+.
- [x] FastAPI factory, env-конфигурация, lifespan пула, live/ready endpoints.
- [x] SQLAlchemy 2 async, сессии с явными транзакциями, Alembic baseline.
- [x] Dockerfile, PostgreSQL Compose, отдельный migration service.
- [x] Unit-тесты, интеграционные тесты реального PostgreSQL, CI.
- [x] Архитектура, ADR, devlog, шаблоны исследований и публикаций.

## Результаты проверок M0

- [x] Сгенерировать `uv.lock` и установить проект из него (`uv sync --locked`).
- [x] Ruff и форматирование; mypy: 17 файлов без ошибок.
- [x] Pytest: 25 passed, в том числе 4 PostgreSQL integration; без skip.
- [x] Upgrade/current/check/downgrade/повторный upgrade через Alembic CLI.
- [x] Docker build и запуск API по README; HTTP 200 для health/docs/OpenAPI.
- [x] Реальный сбой БД: live=200, ready=503; после восстановления ready=200.
- [x] Повторный запуск Compose; migration service exit 0; API uid=10001.
- [x] Обновить фактические результаты в devlog и критериях M0.
- [x] Создать локальную историю: foundation `75af7c5`; результаты и решения в devlog.

## Ограничения среды

Блокеров локального запуска нет. uv 0.13.5 и рабочий Python 3.12.15 подготовлены
в игнорируемом `.tools`; Git доступен по полному пути. Сведения о вызове uv
в этой Windows-среде находятся в AGENTS.md. Для Docker Engine, сети и части
временных файлов Windows понадобился доступ вне sandbox. GitHub Actions
сконфигурирован, но удалённый запуск не подтверждён: push не выполнялся.

## Завершение M1a

Пользователь настроил OAuth application локально. После пересоздания API выполнена
сверка одной карты через настоящий osu! API; успех и повторное чтение подтверждены.
Значения credentials и token responses не выводились и не включались в Git.
On-demand file import выделяется отдельно после проверки подходящего источника;
автоматическое скачивание архива обычным API-токеном не предполагается.

## Выполненные задачи M2

1. Batch/items представлены batch и job rows; 202 следует после commit acceptance.
2. ADR-0007 определяет outbox intent, RabbitMQ confirms/ACK, leases и отдельный worker.
3. Проверены partial batch, redelivery, lease recovery, checksum mismatch, retry/cancel.
4. Версии/pins сохранены; RAM input заменяет disk staging, без source files/objects в БД.

## Следующий этап M3

До gameplay-признаков M3 нужны effective timing/SV, slider traversal,
нормализация координат, stacking и mods; текущие измерения намеренно raw.
Первый срез M3 — выбрать и проверить актуальный difficulty engine, реализовать
контракт ADR-0004 и сопоставление upstream полей; затем собственные признаки.
Подготовлен контракт tag registry/compute budget по ADR-0008. Timing/geometry tags
получат определения и тесты. Logistic baseline раннего M4 уже работает, но качество
skill classification на реальных данных ещё не установлено.

## Технический долг и открытые решения

- Нет лицензии: владелец должен выбрать лицензию до публичного релиза;
  текущий репозиторий не заявляет лицензионных прав сверх имеющихся.
- Контейнеры закреплены по версиям/веткам, не по digest; lock фиксирует Python
  зависимости, но не даёт побитовую воспроизводимость ОС. Потребуется политика обновлений.
- CI настроен, но удалённый запуск не подтверждён до разрешённого push.
- `BrokenProcessPool` в HTTP даёт 503 до перезапуска API. Worker сохраняет retry,
  выходит с ошибкой и пересоздаётся Compose restart policy; локальный CLI нужно перезапустить.
- Повтор upload может заново выполнить CPU-расчёт; дедуплицируется сохранение.
- Живая official checksum-сверка подтверждена для одной карты, mirror batch для двух;
  batch API и долговечный импорт реализованы; автоматического official→mirror fallback нет.
- Official pacing/cache/cooldown локальны одному API-процессу; общий client ID при
  масштабировании потребует распределённого бюджета запросов.
- После освобождения входа новый анализ требует upload либо повторного GET точных байтов;
  доступность исторической версии на сайте не гарантируется.

Решения: [ADR](docs/adr/README.md). Исследований пока нет:
[experiments](docs/experiments/README.md). История: [devlog](docs/devlog/README.md).
