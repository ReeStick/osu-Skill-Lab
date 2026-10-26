# Milestones

Этап закрывается по фактическим проверкам, а не по количеству файлов.

- [M0 — Project Foundation](000-foundation.md).
- [M1 — Beatmap Analysis MVP](001-analysis-mvp.md) — завершён: transient upload,
  измерения в CPU-процессах и компактные сохранённые результаты через REST.
- [M1a — osu! API metadata/identity](001a-osu-api.md): завершён с локальными
  тестами и живой OAuth-сверкой одной карты.
- [M2 — Batch Import & Background Processing](002-batch-background.md):
  завершён: durable batch, RabbitMQ/worker, retry/cancel и живой импорт двух IDs.
- [M3 — Feature Engineering и теги](003-feature-engineering.md): проектирование,
  versioned providers, мягкий budget 30 s и будущая GPU capability; runtime ещё нет.
- Остальные этапы пока только в [ROADMAP](../../ROADMAP.md).
