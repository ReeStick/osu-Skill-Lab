# ADR-0009: Одна runtime queue и настраиваемая capacity worker

Status: Accepted
Date: 2026-10-26
Supersedes: only the one-map/one-process worker capacity in ADR-0007 decision 6

## Context

Владелец разрешил runtime M3 и попросил сохранить простой pipeline: очередь,
отдельные workers и возможность одному экземпляру одновременно обрабатывать
одну либо несколько карт на машинах разной мощности. M2 уже предоставляет
durable jobs, RabbitMQ delivery и отдельный process worker; повторять этот слой
для будущих тегов сейчас не требуется.

## Decision

1. Переиспользовать `osu.analysis-items.v1` и текущие PostgreSQL job/outbox/lease
   contracts как работающую очередь CPU runtime. Одна job — одна карта; частичный
   успех и retry независимы. В этом срезе выполняется прежний basic pipeline.
2. Настройка `OSU_LAB_WORKER_CONCURRENCY` от 1 до 32, default 1; CLI
   `worker --concurrency N` переопределяет env на экземпляре. Workers разных
   мощностей слушают одну очередь, без dispatch policy по hostname и без нового
   сервиса-планировщика. Capacity — operational setting, не часть result identity.
3. Одно N задаёт consumer prefetch, bounded application slots, активные imports,
   CPU admission и максимум pool processes. Broker consumer заменяет polling
   basic.get; handlers работают в TaskGroup. Общий importer lock заменяется
   per-ID lock и semaphore, cache остаётся bounded. API defaults сохраняются.
4. ACK только после сохранённого перехода job. При cancel/fatal failure активные
   handlers завершают отмену, unacked deliveries остаются для redelivery. Fatal
   CPU pool error извлекается из ExceptionGroup и приводит к прежнему exit 1/restart.
5. Shared provider budget, hashes, receipt checks, runtime identity, leases и
   SQL constraints M2 сохраняются. Больше worker slots не означает больше
   разрешённых запросов к зеркалу. RAM/object arrays остаются временными.
6. Не добавлять сейчас stage DAG, новые job tables, GPU queues или metric versions
   без работающего provider. Registry/engine/GPU остаются следующими срезами M3
   по ADR-0004/0008. Мягкий target 30 s не превращается в timeout worker.

## Alternatives

- Отдельная очередь/пакет на каждый размер машины: лишняя маршрутизация и сложный retry.
- Только несколько replicas по одному process: допустимо, но не даёт requested
  capacity одного worker instance и увеличивает число соединений/процессов управления.
- Неограниченные coroutine tasks: переносит backlog в RAM и расходует leases.
- Только увеличить ProcessPoolExecutor: прежний importer lock сохранит сериализацию.

## Sources

- [RabbitMQ consumer prefetch](https://www.rabbitmq.com/docs/consumer-prefetch).
- [Python 3.12 TaskGroup](https://docs.python.org/3.12/library/asyncio-task.html#task-groups).

## Consequences

Capacity явно выбирается для ресурсов машины. Все instances используют общие DB
и broker; вычисления остаются в их CPU pools. Дублированная доставка не обещает
exactly-once CPU, но сохранение результата/job fenced как раньше. Реальная
пропускная способность требует benchmark, а не вывода из N.

Контракт: [runtime-workers](../architecture/runtime-workers.md).
