# M0 — Project Foundation

Status: Complete (locally verified)
Date: 2026-10-25

## Критерии приёмки

- [x] Структура, env example, документация запуска и архитектурная схема.
- [x] FastAPI factory, liveness/readiness и конфигурация.
- [x] PostgreSQL Compose, SQLAlchemy async и Alembic baseline.
- [x] Ruff/mypy/Pytest и конфигурация GitHub Actions.
- [x] Devlog, ADR, TASKS, AGENTS и roadmap.
- [x] Установка через uv из lock воспроизведена.
- [x] Ruff и форматирование прошли; mypy: 17 файлов без ошибок.
- [x] Pytest: 25 passed (21 unit + 4 PostgreSQL integration), без пропусков.
- [x] Миграции upgrade/current/check/downgrade/upgrade прошли.
- [x] Docker build, запуск по README и HTTP-проверки прошли.
- [x] Реальная остановка БД: live=200, ready=503; восстановление: ready=200.
- [x] Повторный запуск Compose и выполнение API от uid=10001 подтверждены.
- [x] Локальная история создана (`75af7c5`); push не выполнялся.

Ограничение: baseline без доменного DDL. Удалённое выполнение CI требует push
и не является локально выполненной проверкой.

Подробности: [devlog](../devlog/2026-10-25-project-foundation.md).
