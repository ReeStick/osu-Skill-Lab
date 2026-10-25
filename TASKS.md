# Текущее состояние

**Milestone 0 — Project Foundation завершён** (2026-10-25).
**Milestone 1 — Beatmap Analysis MVP завершён** (2026-10-25).
Следующий этап — M2: долговечные фоновые задания, пока не начат.

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

## Следующие задачи M2

1. Определить AnalysisJob, состояния и жизненный цикл временного staging:
   вход должен оставаться доступным до завершения допустимых retry, затем очищаться.
2. Принять ADR RabbitMQ delivery/ack/retry, отдельного worker и атомарной постановки задания.
3. Проверить повторную доставку, падение worker и частично завершённые операции.
4. Сохранить version/config/input identity и ограничение постоянного хранения;
   задачи и транспорт не должны переносить весь parsed object graph в PostgreSQL.

До gameplay-признаков M3 нужны effective timing/SV, slider traversal,
нормализация координат, stacking и mods; текущие измерения намеренно raw.

## Технический долг и открытые решения

- Нет лицензии: владелец должен выбрать лицензию до публичного релиза;
  текущий репозиторий не заявляет лицензионных прав сверх имеющихся.
- Контейнеры закреплены по версиям/веткам, не по digest; lock фиксирует Python
  зависимости, но не даёт побитовую воспроизводимость ОС. Потребуется политика обновлений.
- CI настроен, но удалённый запуск не подтверждён до разрешённого push.
- Нет долговечной очереди и автоматического восстановления сломанного process pool:
  `BrokenProcessPool` даёт 503 до перезапуска экземпляра API. Состояния/retry — M2.
- Повтор upload может заново выполнить CPU-расчёт; дедуплицируется сохранение.
- IDs карты не сверены с osu! API; сетевой импорт пока отсутствует.
- После освобождения входа новый анализ требует повторного upload точных байтов;
  доступность исторической версии на сайте не гарантируется.

Решения: [ADR](docs/adr/README.md). Исследований пока нет:
[experiments](docs/experiments/README.md). История: [devlog](docs/devlog/README.md).
