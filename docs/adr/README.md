# Architecture Decision Records

Значимые решения фиксируются отдельно, мелкие изменения — в devlog.
Принятое решение не переписывается задним числом: новое ADR ссылается на прежнее,
а статус прежнего меняется на Superseded.

- [0001 — Модульный монолит](0001-modular-monolith.md).
- [0002 — PostgreSQL и async persistence](0002-postgresql-async.md).
- [0003 — Временные входы и компактные результаты](0003-transient-inputs-compact-results.md).
- [0004 — Версии вычислителей и семейства метрик](0004-versioned-metric-families.md).

## Шаблон

```markdown
# ADR-NNNN: Название
Status: Proposed | Accepted | Superseded
Date: YYYY-MM-DD

## Context
## Decision
## Alternatives
## Consequences
## Revisit conditions
```
