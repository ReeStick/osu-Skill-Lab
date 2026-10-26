# ADR-0008: Расширяемые теги и бюджет обработки M3

Status: Accepted
Date: 2026-10-26
Extends: ADR-0004, ADR-0007

## Context

Владелец уточнил M3: кроме общего difficulty/pp нужны компоненты и в будущем
сложные теги на основе red timing points, slider anchors/геометрии и ML. Система
должна обрабатывать большой корпус; ориентир — до 30 s на карту, мягкий, с
возможным использованием GPU для подходящих вычислений. Текущий runtime считает
только basic-raw и поддерживает batch/worker, внешнего engine/ML пока нет.

## Decision

1. Разделить typed measurements/difficulty/performance, определения тегов и
   интерпретацию skill/tournament. Tag assignment с method/revision не является
   измерением или ground truth по умолчанию.
2. M3 проектирует registry providers и граф зависимостей analysis profile. Providers
   объявляют версии, capabilities, feature schemas, scope и CPU/GPU requirement.
   Общие измерения/модель вычисляются один раз на нужный набор выходов. Runtime
   registry создаётся вместе с первым работающим provider, не как пустой framework.
3. Числовые features остаются типизированными по семействам; новый показатель —
   миграция/schema version. Теги — каталог immutable definitions/bundles и
   реляционные assignments. Новый тег не требует отдельного столбца. EAV feature
   values, произвольный output JSON и массивы input objects не вводятся.
4. Разреженные assignments не заполняют весь декартов продукт карты×теги.
   Полнота run/bundle определяет, означает ли отсутствие assignment «не назначен»;
   невычисленные/отложенные/неподдержанные теги — unknown. Confidence/score сохраняется
   только с определённой семантикой; heuristic score не объявляется вероятностью.
5. Версионировать вход/feature dependencies, определение, пороги, model artifact,
   preprocessing, label mapping, calibration и существенный execution profile.
   Изменения создают новые snapshots; история не перезаписывается. Source/engine
   versions соблюдают ADR-0004, API не получает выдуманную upstream revision.
6. Заложить мягкий target 30000 ms processing wall time: от готовых bytes до commit
   выбранного профиля. Queue/acquisition/cooldown и полное time-to-result измерять
   отдельно. Это принятая начальная трактовка ориентира владельца, не жёсткое SLA.
   Обязательная стадия может завершиться с budget_exceeded; необязательная — стать
   deferred_budget. Не выдавать partial/unsupported за полный результат или отсутствие тега.
7. CPU/GPU routing и capacity отдельны от HTTP и leases. GPU применяется после
   профилирования, с учётом transfers/warmup/batching. CUDA не обязательна для
   базового deployment. Непроверенный CPU fallback/смена precision не скрываются.
8. Input bytes, parsed geometry и tensors временные в RAM/VRAM. Отдельная стадия
   может повторить GET с SHA pin. Через RabbitMQ идут job IDs/references; в PostgreSQL
   — metadata, typed snapshots, stage status/timings и tags. Сохранение raw корпуса
   или обучения ML в M3 автоматически не разрешает постоянное хранение maps.

Подробные семантика, предлагаемые таблицы и критерии:
[tag-pipeline](../architecture/tag-pipeline.md).

## Alternatives

- Столбец на каждый тег: смешивает рост vocabulary и schema метрик.
- Общий JSON/EAV для всех features: теряет типизацию и противоречит ADR-0003/0004.
- Полная матрица отрицательных assignments: дорогая на большом корпусе и путает
  отсутствие результата с проверенным неназначением.
- Жёсткий kill всей обработки через 30 s: не соответствует мягкому ориентиру и
  уничтожает полезные частичные результаты.
- Любые вычисления сразу на GPU: выбор ускорения без measurements и профиля нагрузки.

## Consequences

Расширяемость задают contracts/provenance и отдельные стадии, не заранее заполненные
пустые таблицы. M3 начинается с official components и первого adapter, затем
детерминированных providers и tag foundation. Будущая ML стадия встраивается в тот
же контракт; её dataset/качество/training и GPU rollout требуют работающего сценария.
Существующие API/jobs/basic-raw не меняют поведение от принятия этого ADR.

## Revisit conditions

Первый provider и benchmark, необходимая persistent feature sequence, новый scope
тегов, выбранная ML-модель, доказанная выгода GPU либо новая трактовка latency target.
