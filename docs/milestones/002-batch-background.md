# M2 — Batch Import & Background Processing

Status: In progress — adapter and single-file import implemented
Date: 2026-10-25

## Критерии

- [x] Прикладной сценарий: список difficulty IDs, mirror metadata/raw files и per-item results.
- [x] Источники, доверие, cooldown и ограничения закреплены в ADR-0006.
- [x] Hinamizawa adapter: ID-only metadata batch, bounded raw `.osu`, missing/unresolved/errors.
- [x] DTO/миграция download provenance без подмены официального match.
- [x] Сквозной single-file HTTP import, atomic persistence, повтор/GET и живой raw file.
- [ ] Batch API 202, durable batch/items/jobs и получение прогресса/analysis IDs.
- [ ] RabbitMQ и отдельный worker; atomic acceptance/delivery, ACK/retry strategy в отдельном ADR.
- [ ] Shared provider budget, bounded downloads и защита от повторной обработки.
- [ ] Временный staging, сохранность на retry, очистка после завершения и orphan TTL.
- [ ] Partial success, cancellation, duplicate delivery и worker restart проверены.
- [ ] Контракт источника, checksum/ruleset/format и отсутствие raw files в БД проверены.
- [ ] Реальные PostgreSQL, broker/worker, целевые тесты и воспроизводимый Docker сценарий.
- [ ] Ограниченный живой import одного малого batch без массового сканирования зеркала.

Batch API/jobs/broker/worker ещё не реализованы. Подключение difficulty/pp — M3.
Первый срез: [mirror-import](../architecture/mirror-import.md),
проверки: [devlog](../devlog/2026-10-25-hinamizawa-import.md).
Проект: [batch-import](../architecture/batch-import.md),
решение: [ADR-0006](../adr/0006-mirror-batch-import.md).
