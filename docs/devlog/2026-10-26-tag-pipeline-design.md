# 2026-10-26 — Архитектура тегов, мягкий compute budget и GPU stages

## Объём

Владелец уточнил M3: официальные компоненты метрик, затем более сложные теги
по red BPM timing points, slider anchors/геометрии и будущему ML. Для большой
библиотеки ориентир — не более 30 s обработки карты, мягкий; часть вычислений
можно будет вынести на GPU. Выполнен архитектурный срез, не engine/ML implementation.

## Решение

Принят [ADR-0008](../adr/0008-extensible-tags-and-compute-budget.md), создан
[tag-pipeline](../architecture/tag-pipeline.md) и [M3 milestone](../milestones/003-feature-engineering.md).
Числовые measurements остаются typed families, теги — immutable definitions/bundles
и sparse assignments. Run coverage отличает «не назначен конкретной версией метода»
от unknown/deferred/unsupported. Rule/model score не превращается в ground truth.

Предусмотрены registry providers, dependency/profile identity, stage status/timings,
model/preprocessing/threshold provenance и capability routing CPU/GPU. Для rule/ML
на одном наборе входов общий producer не запускается заново на каждый выходной тег.
Объекты/feature sequences/tensors временные, числовой output не прячется в tag EAV/JSON.

30 s трактуются как wall time от проверенных bytes до commit выбранного профиля,
включая preprocessing/transfers/persistence. Queue/acquisition и полный time-to-result
измеряются отдельно. Это выбранная начальная трактовка мягкого ориентира, не SLA.
Дорогая optional stage может отложиться; отсутствие tag result не становится отрицанием.
Бюджет не меняет существующие HTTP timeouts, lease 90 s или worker retry.

Перечитаны текущие ADR-0004/0007, metric/database/job contracts, TASKS/ROADMAP и
предыдущий devlog; Git HEAD `99d1513`, пользовательский `.gitignore` остаётся отдельно.
Для принципов GPU profiling/timing просмотрен официальный
[CUDA Best Practices Guide](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html#timing):
учитывать transfers и завершение асинхронной работы при замерах. CUDA/ML библиотека
не выбиралась, GPU hardware проекта не проверялся, ускорение/latency не измерялись.

## Проверки и границы

Изменения только в документации. Runtime, миграции, dependencies и lock не менялись;
пустые схемы и неиспользуемый plugin framework не добавлялись по ADR-0004.
Pytest и прежний Docker harness не запускались: затронутых исполняемых модулей нет.
Локальный `.tools/check_metric_docs.py`: 30 Markdown files, 168 относительных ссылок
проверены. `git diff --check` прошёл; Git предупредил о CRLF пользовательского
`.gitignore`, он не включается в этот коммит. CHANGELOG продукта не расширялся
без новой runtime возможности.

Следующий рабочий срез — точный engine/upstream и component coverage, adapter,
provenance/DDL и tests; затем первый timing/geometry provider и deterministic tag.
Benchmark потребует отдельного эксперимента с данными/hardware/versioned profile.
M3 целиком не объявляется завершённым, M4 training/classification не начат.
