# Ранний M4 — Label Workbench

Status: первый срез реализован; полный M4 открыт.
Scope change: владелец разрешил UI/разметку до завершения difficulty engine M3.

- [x] Локальный `/lab`, создание immutable definitions, yes/no/unsure и undo.
- [x] Человеческие решения отделены от версий правил и model scores.
- [x] Preview готовых raw features в Web Worker, threshold использует кеш оценок.
- [x] Logistic baseline на явных labels, preprocessing fit только на train.
- [x] Контрольные карты и их claimed set groups исключены из train.
- [x] CPU process, bounded training admission и корректная отмена HTTP.
- [x] PostgreSQL migration/lineage, portable artifacts/hash guards и Compose volume.
- [x] Целевые CPU/PostgreSQL/JS тесты и сценарий в Chrome, включая мобильную ширину.
- [ ] Реальная human разметка, независимый grouped test и анализ ошибок.
- [ ] Подтверждённая полезность признаков/калибровка/качество, UI latency benchmark.
- [ ] Массовые tag providers, расширенные признаки и difficulty components M3.

Контракт: [label-workbench](../architecture/label-workbench.md),
решение: [ADR-0010](../adr/0010-hybrid-label-workbench.md).
