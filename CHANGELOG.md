# Changelog

Здесь отражаются возможности продукта. Процесс разработки — в `docs/devlog/`.

## Unreleased

### Added

- Основной `/lab` переработан вокруг выбранной карты: локальный preview с checksum,
  playback/seek/speed/audio, теги и отдельная последовательная проверка тега.
- Полный paginated/search каталог совместимых анализов. Предыдущие аналитика,
  правила и обучение сохранены в `/lab/research`.
- Автоматический выбор train/validation для новых групп в основном UI; ранее
  сохранённые роли и append-only история решений остаются неизменными.

- Два вида `/lab`: аналитика с локальными вкладами метрик и мини-гистограммами,
  отдельная разметка нескольких тегов кликом/drag-and-drop, выбор difficulty справа.
- Светлая и спокойная тёмная темы; настройки и обучение свёрнуты, сохранённая
  совместимая версия правила/порога восстанавливается при загрузке.
- Локальный `/lab`: ручная разметка тегов, история/undo, контрольная выборка,
  ползунки правила, версии и быстрый Web Worker preview без повторного анализа карт.
- Обучаемый logistic baseline в отдельном CPU-процессе, train-only preprocessing,
  исключение контрольных сетов, immutable model artifacts и lineage до label events.
- Migration `0006_label_lab` и отдельный Compose volume для JSON artifacts моделей.
- Worker concurrency 1..32 через env/CLI: общая runtime queue, bounded consumer
  prefetch, параллельные imports/CPU slots и возврат unacked jobs при остановке.
- Долговечные пакеты `POST/GET /analysis-batches`, Idempotency-Key, per-item status,
  checksum pins и cancel; RabbitMQ dispatcher/worker с leases и ограниченными retry.
- Общий Hinamizawa pacing/cooldown в PostgreSQL, RAM-only input с SHA pin на retry.
- Hinamizawa metadata batch adapter и `POST /imports/hinamizawa/{beatmap_id}`:
  raw download с checksum/SHA pin, независимая provenance, cache и source limits.
- Явная сверка сохранённого анализа с osu! API: OAuth public lookup по checksum,
  отдельная metadata, статус `checksum_match`, cache/rate limits и сетевые ошибки.
- REST-анализ `.osu`: `POST /analyses`, чтение результата и список с пагинацией.
- 22 базовых scalar features: counts, red BPM, start span, интервалы и raw
  расстояния heads с математическим контрактом `basic-raw/1`.
- Компактные PostgreSQL metadata/results, версии и checksums; атомарная
  дедупликация повторных и конкурентных сохранений.
- Ограниченная обработка входа в RAM и CPU-процессах, без сохранения файлов;
  контролируемые ошибки размера, формата, перегрузки и доступности.
- Аналитический reader osu!standard v14: difficulty settings, timing points,
  circles/sliders/spinners и CLI `inspect-osu` с JSON-сводками и ошибками по строкам.
- Offline CLI `osu-skill-lab extract-osz`: ограниченное извлечение `.osu`,
  checksums и manifest, повторная проверка без перезаписи существующих результатов.
- Основа API с `GET /health/live`, `GET /health/ready`, OpenAPI и Swagger UI.
- Валидируемые настройки окружения, async-пул PostgreSQL и управление сессиями.
- Alembic baseline, локальный Docker Compose и отдельный запуск миграций.
- Проверки качества, тесты и CI для Python 3.12 и PostgreSQL.
- Документация архитектуры, ADR, roadmap и постоянный журнал разработки.
