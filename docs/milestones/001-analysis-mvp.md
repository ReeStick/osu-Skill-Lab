# M1 — Beatmap Analysis MVP

Status: Complete
Started: 2026-10-25
Completed: 2026-10-25

## Критерии приёмки

- [x] Подготовка локальных `.osz`: ограниченное извлечение `.osu`, manifest,
  checksum, повторный запуск, синтетические тесты и проверка реального корпуса.
- [x] Независимый аналитический reader v14/UTF-8 standard, синтетические fixtures,
  ошибки некорректных/неподдержанных файлов, проверка 33 локальных карт.
- [x] Временный input и persistence metadata/checksums; постоянное хранение
  исходников отменено владельцем, решение зафиксировано в ADR-0003.
- [x] 22 базовых математически определённых признака и versioned результаты.
- [x] Вычисления в CPU-процессах вне HTTP event loop, ограничение параллельности.
- [x] REST upload, получение сохранённого результата, API/БД интеграция.
- [x] Сценарий загрузка → анализ → удаление временного исходника → чтение;
  повтор upload сохраняет identity и не создаёт дубликат результата.
- [x] 196 тестов, включая 18 PostgreSQL integration; миграции, Docker API и
  реальный корпус 33 карт проверены локально.

RabbitMQ и надёжные задания — M2. Эти измерения не заявляют skill classification.
Контракты: [БД](../architecture/database.md),
[признаки](../architecture/basic-features.md),
[ADR-0003](../adr/0003-transient-inputs-compact-results.md).
История и ограничения: [итоги M1](../devlog/2026-10-25-compact-analysis-pipeline.md).
