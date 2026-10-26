# M3 — Feature Engineering и расширяемые теги

Status: In progress; CPU runtime queue/concurrency implemented, engine/tags pending
Date: 2026-10-26

## Принятый объём

- [x] Official total/component difficulty/pp, раздельные семейства и score context.
- [x] Проект providers/dependencies, tag definitions/bundles и компактных assignments.
- [x] Мягкий target 30 s, раздельные timings и отдельная будущая GPU capability.
- [x] Границы хранения и unknown/partial semantics — ADR-0008.

## Критерии реализации

- [x] Runtime queue и отдельный CPU worker: configurable capacity 1..32, default 1.
- [x] Общий queue для разных capacities, bounded prefetch/import/CPU slots и recovery tests.
- [ ] Выбрать точные engine/binding/upstream revisions и проверить coverage компонентов, включая reading.
- [ ] Реализовать provider provenance/identity и миграции typed difficulty/performance.
- [ ] Проверить mods/score scenarios, components и отсутствие тихой подмены версии.
- [ ] Подключить registry/profile planner с versioned dependencies и capability checks.
- [ ] Первый собственный timing/geometry provider: определения, bounded outputs, synthetic tests.
- [ ] Первый детерминированный тег: definition revision, scope/evidence и sparse coverage semantics.
- [ ] Stage result/status: partial, unsupported, deferred_budget; бюджет не заменяет lease/timeout.
- [ ] PostgreSQL persistence, дедупликация и сохранение старых версий.
- [ ] Benchmark representative inputs: p50/p95/p99, throughput, memory, cold/warm и stage timings.
- [ ] Документация, devlog и локальные проверки затронутых сценариев.

GPU inference/training и качество ML не заявляются реализованными в M3 без
конкретной модели, данных и отдельного проверяемого среза. Их контракт учитывается
заранее; classification rollout относится к M4. 30 s — ориентир, не уже измеренный SLA.

Контракты: [metric-evolution](../architecture/metric-evolution.md),
[tag-pipeline](../architecture/tag-pipeline.md),
[ADR-0008](../adr/0008-extensible-tags-and-compute-budget.md).
Первый runtime срез: [runtime-workers](../architecture/runtime-workers.md),
[ADR-0009](../adr/0009-worker-concurrency.md).
