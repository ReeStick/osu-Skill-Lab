# Changelog

Здесь отражаются возможности продукта. Процесс разработки — в `docs/devlog/`.

## Unreleased

### Added

- Offline CLI `osu-skill-lab extract-osz`: ограниченное извлечение `.osu`,
  checksums и manifest, повторная проверка без перезаписи существующих результатов.
- Основа API с `GET /health/live`, `GET /health/ready`, OpenAPI и Swagger UI.
- Валидируемые настройки окружения, async-пул PostgreSQL и управление сессиями.
- Alembic baseline, локальный Docker Compose и отдельный запуск миграций.
- Проверки качества, тесты и CI для Python 3.12 и PostgreSQL.
- Документация архитектуры, ADR, roadmap и постоянный журнал разработки.
