# 2026-10-25 — Компактное хранение и REST-анализ

## Цель и уточнение требований

Замкнуть M1: локальные байты `.osu` → reader → измерения → сохранение → чтение
через REST. Владелец уточнил жизненный цикл: карты не нужно хранить постоянно;
нужны metadata для сопоставления с сайтом и результаты. Это меняет прежний
план storage abstraction и предварительных Beatmap/BeatmapSet таблиц.

CLI-сводка не содержит объектов и не используется как вход feature extraction.
Reader уже возвращает `ParsedBeatmap` с timing points и circles/sliders/spinners.
Теперь extractor получает эту структуру внутри CPU-процесса, затем она выходит
из области обработки. Из CPU-процесса возвращаются только компактные данные.

## Решение

[ADR-0003](../adr/0003-transient-inputs-compact-results.md) определяет две таблицы:
`beatmap_inputs` — fingerprint точных байтов и ограниченная metadata;
`analysis_results` — исходные settings, 22 типизированных измерения, версии и
малый JSONB конфигурации. Objects/timings, raw bytes и пути к файлам не сохраняются.
Миграция `0002_compact_analysis` сгенерирована Alembic и проверена вручную.

SHA-256 уникально идентифицирует input внутри сервиса; MD5 — неуникальный
совместимый checksum. IDs из пользовательского файла — claims, а не проверенная
связь с официальным сайтом. API возвращает `identity_status="unverified"`.
Результат уникален по input, algorithm/parser versions и canonical config hash.
Конкурентная вставка использует `ON CONFLICT DO NOTHING` и отдельный SELECT
при READ COMMITTED; повтор не перезаписывает metadata и время результата.

`basic-raw/1` измеряет counts, extrema red BPM, span начал объектов,
интервалы и евклидовы расстояния circle/slider heads. Формулы, единицы и пустые
случаи описаны в [basic-features](../architecture/basic-features.md).
Это raw измерения, без mods, stacking, slider traversal, SR/PP и skill оценок.

HTTP принимает raw body до 4 MiB. Два слота резервируются до чтения входа;
два процесса выполняют reader/extraction вне event loop. Исходник находится
только в RAM, поэтому удалять временный файл сервису сейчас не требуется.
После расчёта открывается одна транзакция для metadata и результата.
POST возвращает 201 или 200 при повторе; GET читает результат/список из БД.

## Найденные проблемы и проверки границ

- Windows sandbox блокирует IPC-каналы `ProcessPoolExecutor` (`WinError 5`).
  Прогоны с процессами повторены вне sandbox; это не заменялось фиктивным executor
  в полном API/БД сценарии.
- Исключение reader имеет конструктор, неудобный для межпроцессного pickle.
  Ожидаемая ошибка возвращается как `PreparationFailure`; настоящий process pool
  проверен на корректном и некорректном входе.
- Отмена HTTP-запроса не останавливает уже работающий процесс. Слот остаётся
  занят до завершения future; поведение закреплено управляемым executor-тестом.
- Ревью обнаружило NUL в сохраняемой metadata и HTTP ID за диапазоном bigint.
  Оба случая теперь дают 422 до DB-записи вместо ошибки доступности.
- Для повторного POST в OpenAPI добавлена явная схема ответа 200.
- Первый общий прогон: 186 passed, 1 failed. Тест миграции ошибочно предполагал
  порядок `get_table_names()`; список перед сравнением сортируется. При правке
  возник лишний отступ, обнаруженный сборкой pytest и сразу исправленный.

## Проверки

Команды выполнялись из корня с проектной `.venv`; для uv использован локальный
`.tools/Scripts/uv.exe` и игнорируемые cache/python dirs из AGENTS.md.

```text
ruff check .
ruff format --check .
mypy
pytest --tb=short
alembic current
alembic check
docker compose up --build --wait api
```

`pytest` с `OSU_LAB_TEST_DATABASE_URL` прошёл: **196 passed**, включая 178 unit
и 18 integration с PostgreSQL 17, без skip (5.88 s в итоговом прогоне).
Интеграционные схемы изолированы; проверены upgrade/check/downgrade/repeat,
rollback без orphan input, шесть конкурентных транзакций, различия версий/config,
неуникальные claimed IDs и MD5, pagination, nullable поля и лимит JSONB.

Отдельный сквозной тест отправляет synthetic fixture в настоящий CPU-процесс,
сохраняет через PostgreSQL, удаляет собственную временную копию исходника,
проверяет GET и повторный POST. Пользовательский корпус этот тест не меняет.
Рабочая локальная БД имеет head `0002_compact_analysis`; `alembic check`:
`No new upgrade operations detected`.

Ruff lint/format прошли (66 файлов форматированы), mypy — 41 файл без ошибок.
`uv sync --locked --offline` подтвердил актуальность lock и 39 пакетов;
новых зависимостей в этом срезе нет.

CI дополнен Docker POST синтетического fixture. Конфигурация CI обновлена,
но удалённый GitHub Actions запуск не заявляется: push не выполнялся.

## Проверка реального корпуса и объёма

Локальный helper `.tools/check_compact_storage.py` (игнорируется Git) отправил
33 ранее извлечённых `.osu` в Docker API. Для каждой карты GET совпал с POST;
всего учтены **26 400 objects и 6 377 timing points**. Первые POST дали 33 новых
результата; повтор первого файла вернул 200 с прежним результатом. В БД осталось
33 inputs и 33 results. Исходные архивы и offline extraction сохранены.

После повторного Docker build/recreate проверка всех 33 карт выполнена ещё раз:
0 created, 33 reused, размеры и количество строк прежние. Health live/ready —
200; повторный migration service завершился успешно, API работает с uid 10001.

Размеры измерены в PostgreSQL после загрузки и одного повторного POST:

| Представление | Байты |
| --- | ---: |
| Исходные 33 `.osu` | 1 413 043 |
| `sum(pg_column_size(b))`, `beatmap_inputs b` | 6 552 |
| `sum(pg_column_size(a))`, `analysis_results a` | 21 912 |
| Строки обеих таблиц | 28 464 |
| `pg_total_relation_size('beatmap_inputs')` | 81 920 |
| `pg_total_relation_size('analysis_results')` | 90 112 |
| Обе таблицы с индексами | 172 032 |

Это малый корпус, одна версия алгоритма и конкретное состояние PostgreSQL.
`pg_column_size` не включает всю стоимость хранения; `pg_total_relation_size`
включает индексы и служебные relation pages, но не всю БД/WAL/backups.
Замер не является прогнозом производительности или объёма на миллионах карт.
Результаты и отчёт локально сохранены в игнорируемых
`data/analysis-results.jsonl` и `data/compact-storage-check.json`.

## Ограничения и следующий шаг

Новый анализ после освобождения входа требует повторного получения тех же
байтов. Один BeatmapID не гарантирует ту же редакцию; SHA-256 не восстанавливает
файл. Проверка официальной identity и сетевой импорт ещё не реализованы.

Дедуплицируется сохранение, а не каждый CPU-вызов. Нет надёжной очереди,
автоматических retry и восстановления `BrokenProcessPool`: до перезапуска API
он возвращает 503. Лимиты процесса локальны одному экземпляру API, не всему кластеру.
M2 должен определить задания, доставку, staging на время retry и очистку.
Постоянное хранение исходников ради очереди не возвращается автоматически.
