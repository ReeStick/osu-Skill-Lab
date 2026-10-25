# M1a — osu! API metadata/identity

Status: Complete
Started: 2026-10-25
Completed: 2026-10-25

## Критерии

- [x] Optional OAuth application settings, public guest token, lifecycle и скрытые секреты.
- [x] Explicit checksum lookup для загруженной карты, без доверия file IDs.
- [x] Отдельная типизированная API metadata и время наблюдения; raw results неизменны.
- [x] Проверка missing/different checksum, nonstandard mode, неизвестного результата.
- [x] Cache после restart, pacing, token expiry/401 retry, upstream errors/cooldown.
- [x] Ограничение конкуренции/отмена, time/body limits, отсутствие утечки секретов.
- [x] Реальная PostgreSQL migration/rollback/concurrency и HTTP → transport → DB сценарий.
- [x] 259 tests passed, quality/lock и Docker smoke без OAuth credentials.
- [x] Download/attributes boundaries проверены: archive lazer route не используется;
  текущий file input — локальный upload, quantitative attributes — будущий сценарий.
- [x] Живая авторизованная сверка с настоящим osu!: анализ №1 → beatmap 1960574,
  HTTP 200; повтор и GET подтвердили сохранённую metadata и прежние features.

Реализация проверена локально и одним авторизованным обращением к сайту после
настройки credentials пользователем. M2 не начат. On-demand file source требует
отдельной проверки. При живой проверке неизменённые unit-тесты не перезапускались.
Контракт: [osu-api](../architecture/osu-api.md),
решение: [ADR-0005](../adr/0005-osu-checksum-metadata.md),
проверки: [devlog](../devlog/2026-10-25-osu-api-verification.md).
