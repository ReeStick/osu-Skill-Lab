# 2026-10-26 — Runtime queue и worker capacity

## Объём и решение

Владелец разрешил runtime и попросил простой механизм очереди/отдельных workers,
чтобы экземпляр мог одновременно выполнять одну или несколько карт на машинах
разной мощности. Перечитаны AGENTS/TASKS/ROADMAP, ADR-0007/0008 и tag/batch contracts;
HEAD до изменений `77fd015`, чужое изменение `.gitignore` не включается в срез.

Повторно использованы PostgreSQL jobs/outbox/leases и очередь M2, без второго
планировщика или новых таблиц. Принят [ADR-0009](../adr/0009-worker-concurrency.md),
контракт: [runtime-workers](../architecture/runtime-workers.md).

## Реализация

`OSU_LAB_WORKER_CONCURRENCY` 1..32, default 1, CLI `worker --concurrency N` имеет
приоритет. Одно N задаёт AMQP prefetch, handler slots, активные imports и CPU pool.
Прежний polling заменён consumer iterator и bounded TaskGroup. ACK следует за job
transition; cancellation/fatal error отменяет siblings, unacked redelivered после
закрытия соединения. Fatal restart не теряется внутри ExceptionGroup.

Один глобальный lock MirrorImportService сериализовал и CPU, поэтому заменён
per-ID gates и semaphore. Результат кешируется/переиспользуется для того же ID;
разные карты могут находиться в CPU одновременно. Gate references удаляются после
последнего пользователя, cache bounded. Сетевой Hinamizawa client по-прежнему
сериализован и использует shared PostgreSQL budget, так что N не отменяет pacing.
HTTP default остаётся один активный/один ожидающий import; worker capacity отдельна.

Исполняется текущий reader/basic-raw, не выдуманный difficulty provider. Engine/tag
registry/GPU/ML и soft-budget telemetry — следующие срезы M3. Concurrency не меняет
математическую identity; migrations/dependencies/lock не менялись.

Проверены первичные источники по
[RabbitMQ prefetch](https://www.rabbitmq.com/docs/consumer-prefetch) и
[TaskGroup Python 3.12](https://docs.python.org/3.12/library/asyncio-task.html#task-groups).

## Целевые тесты

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_runtime_worker.py tests/unit/test_config.py tests/unit/test_mirror_import.py --tb=short
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_config.py::test_environment_overrides_dotenv --tb=short
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_worker.py tests/integration/test_batch_worker.py tests/integration/test_mirror_import.py --tb=short
```

Первый прогон: **47 passed**, один setup error — Windows sandbox запретил pytest
temp directory. Повтор единственного затронутого fixture-теста вне sandbox:
**1 passed (0.35 s)**. PostgreSQL/RabbitMQ/CPU прогон вне sandbox:
**22 passed (8.66 s)**. Всего 70 уникальных cases, не полный pytest. Неизменённые
parser/features/osz/CLI и прочие независимые unit не запускались.

Новые реальные проверки: два consumers capacities 1+2 на одном тестовом хосте,
шесть разных jobs, максимум 1/2 активных на CPU boundary, реальные process-pool
вычисления и шесть сохранённых результатов; shutdown/requeue двух unacked slots;
дедуп одного ID параллельно с другим без сериализации CPU. Это не multi-host
benchmark и не доказательство линейного ускорения.

Unit проверяют bounded capacity/ACK order, poison messages, idle receive при fatal
error, sibling cancellation, CLI/env precedence и согласованность pool/import slots.
Mypy сначала потребовал явный re-export перенесённого WorkerRestartRequired;
совместимость прежнего импорта сохранена. Ruff форматирование исправлено.

## Docker и живой сценарий

Первый доступ к Docker был отклонён sandbox, повтор с разрешением прошёл.
`OSU_LAB_WORKER_CONCURRENCY=3 docker compose up --build --wait api dispatcher worker`
(в PowerShell env задавался отдельно) — обычный build/migrate/start passed. В этом
срезе registry доступен, fallback image из прошлого этапа не понадобился.
Контейнер и лог подтвердили capacity 3, без вывода credentials/config.

Локальный ignored `.tools/check_batch_import.py submit/poll` проверил batch
`23505c47-f0ed-4e5c-a752-bdc764da28b7`: 202 acceptance/replay, два unique IDs,
оба succeeded за одну попытку. Analysis №1 и №72 переиспользованы; features/settings/
версии/official observation №1 сохранились. Media/source files не записывались.

## Проверки качества и остаток

Финальные `ruff check .`, `ruff format --check .` — passed, 126 files formatted;
`mypy` — 78 source files без ошибок. `uv sync --locked --offline` проверил 45 packages.
Локальный `.tools/check_metric_docs.py`: 33 Markdown files и 188 relative links
проверены. `git diff --check` прошёл, CRLF warning касается пользовательского `.gitignore`.
GPU/model code и schema не добавлены. M3 не завершён: следующий срез — проверенный difficulty engine,
component coverage и versioned provider provenance/DDL.
