# M2 — Batch Import & Background Processing

Status: Not started — design accepted
Date: 2026-10-25

## Критерии

- [x] Прикладной сценарий: список difficulty IDs, mirror metadata/raw files и per-item results.
- [x] Источники, доверие, cooldown и ограничения закреплены в ADR-0006.
- [ ] Hinamizawa adapter: metadata batch, bounded raw `.osu`, missing/unresolved/error contracts.
- [ ] DTO/миграция download provenance без подмены официального match.
- [ ] Batch API 202, durable batch/items/jobs и получение прогресса/analysis IDs.
- [ ] RabbitMQ и отдельный worker; atomic acceptance/delivery, ACK/retry strategy в отдельном ADR.
- [ ] Shared provider budget, bounded downloads и защита от повторной обработки.
- [ ] Временный staging, сохранность на retry, очистка после завершения и orphan TTL.
- [ ] Partial success, cancellation, duplicate delivery и worker restart проверены.
- [ ] Контракт источника, checksum/ruleset/format и отсутствие raw files в БД проверены.
- [ ] Реальные PostgreSQL, broker/worker, целевые тесты и воспроизводимый Docker сценарий.
- [ ] Ограниченный живой import одного малого batch без массового сканирования зеркала.

План не означает наличие этих API/таблиц. Подключение difficulty/pp — M3.
Проект: [batch-import](../architecture/batch-import.md),
решение: [ADR-0006](../adr/0006-mirror-batch-import.md).
