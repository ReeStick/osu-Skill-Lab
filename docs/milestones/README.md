# Milestones

Этап закрывается по фактическим проверкам, а не по количеству файлов.

- [M0 — Project Foundation](000-foundation.md).
- [M1 — Beatmap Analysis MVP](001-analysis-mvp.md) — завершён: transient upload,
  измерения в CPU-процессах и компактные сохранённые результаты через REST.
- [M1a — osu! API metadata/identity](001a-osu-api.md): завершён с локальными
  тестами и живой OAuth-сверкой одной карты.
- [M2 — Batch Import & Background Processing](002-batch-background.md):
  завершён: durable batch, RabbitMQ/worker, retry/cancel и живой импорт двух IDs.
- [M3 — Feature Engineering и теги](003-feature-engineering.md): CPU runtime queue
  и worker capacity готовы; difficulty/tag providers и GPU пока в проекте.
- Остальные этапы пока только в [ROADMAP](../../ROADMAP.md).
- [Ранний M4 — Label Workbench](004-label-workbench.md): ручные решения,
  настройка правила и logistic baseline; полный M4 не завершён.
