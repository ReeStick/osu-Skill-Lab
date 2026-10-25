# Changelog

Здесь отражаются возможности продукта. Процесс разработки — в `docs/devlog/`.

## Unreleased

### Added

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
