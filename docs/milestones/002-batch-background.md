# M2 — Batch Import & Background Processing

Status: Complete — local validation and live two-item import
Date: 2026-10-26

## Критерии

- [x] Прикладной сценарий: список difficulty IDs, mirror metadata/raw files и per-item results.
- [x] Источники, доверие, cooldown и ограничения закреплены в ADR-0006.
- [x] Hinamizawa adapter: ID-only metadata batch, bounded raw `.osu`, missing/unresolved/errors.
- [x] DTO/миграция download provenance без подмены официального match.
- [x] Сквозной single-file HTTP import, atomic persistence, повтор/GET и живой raw file.
- [x] Batch API 202, durable batch/jobs и получение прогресса/analysis IDs.
- [x] RabbitMQ и отдельный worker; atomic acceptance, outbox/ACK/retry — ADR-0007.
- [x] Shared mirror budget, bounded downloads и защита job/result от дубликатов.
- [x] RAM input вместо disk staging: observed SHA pin на retry, без source files/orphans (ADR-0007).
- [x] Partial success, cancellation, duplicate delivery и lease recovery после consumer crash проверены.
- [x] Контракт источника, checksum/ruleset/format и отсутствие raw files в БД проверены.
- [x] Реальные PostgreSQL/RabbitMQ/CPU, целевые тесты и воспроизводимый Docker сценарий.
- [x] Живой import двух уникальных IDs без массового сканирования зеркала.

Batch API/jobs/broker/worker реализованы. Подключение difficulty/pp — M3.
Контракт: [batch-processing](../architecture/batch-processing.md),
проверки: [devlog M2](../devlog/2026-10-26-durable-batch-processing.md).
Первый срез: [mirror-import](../architecture/mirror-import.md),
проверки: [devlog](../devlog/2026-10-25-hinamizawa-import.md).
Проект: [batch-import](../architecture/batch-import.md),
решение: [ADR-0006](../adr/0006-mirror-batch-import.md).
