# ADR-0007: Долговечные задания, доставка и временный input

Status: Accepted
Date: 2026-10-25
Refines: ADR-0006, lifecycle section of batch-import
Partially superseded: one-map worker capacity in decision 6 by ADR-0009

## Context

Приём пакета и отправка в RabbitMQ не образуют общую транзакцию. Сообщения могут
повторяться, соединение worker может оборваться после сохранения результата.
Нужны частичный успех, ограниченные retry и возможность отмены. Первый import уже
умеет работать в RAM; постоянное хранение исходников не требуется.

## Decision

1. PostgreSQL хранит `analysis_batches`, `analysis_jobs` и намерение доставки
   `delivery_after` в строке job. Отдельная job на каждый уникальный difficulty ID.
   Приём атомарен, ограничен 100 items/request и 1000 незавершённых jobs глобально.
   UUID `Idempotency-Key` и hash нормализованного запроса защищают повторный приём.
2. Dispatcher выбирает due jobs через `FOR UPDATE SKIP LOCKED`, публикует persistent
   notification в durable RabbitMQ queue с publisher confirm и только затем
   переносит `delivery_after` на 30 s. Сбой между confirm и commit даёт повтор;
   источник истины остаётся в БД. Очередь ограничена 2000 ready messages,
   overflow отклоняет публикацию. Задержки/retry находятся в БД, не в requeue loop.
3. Worker берёт job короткой транзакцией, увеличивает attempts и получает UUID lease
   на 90 s. Heartbeat каждые 15 s продлевает его. Изменения job требуют текущий token
   и непросроченный lease. Dispatcher восстанавливает истёкшие leases. ACK следует
   после сохранённого перехода либо распознавания duplicate/terminal job.
4. At-least-once execution: запись анализа/source и завершение job — две транзакции.
   Сбой между ними может повторить CPU/download; unique identity анализа защищает
   результат. Это не exactly-once расчёт. Старый worker не завершает job нового lease.
5. Пять попыток максимум; retryable transport/429/503/unresolved/CPU-storage failure
   задают `run_after` с backoff и учётом Retry-After. Постоянные input/checksum ошибки
   завершают элемент. Пользователь может повторить неудачные IDs новым пакетом/key.
   Algorithm/parser/configuration identity фиксируются при приёме; несовместимый
   worker возвращает `pipeline_version_mismatch`, не подменяет версию расчёта.
   Сломанный CPU pool сохраняет retry и завершает worker с exit 1: Compose
   restart policy создаёт новый процесс/pool. HTTP возвращает прежний 503 contract.
6. Один CPU-процесс и один активный item на worker. Metadata resolution прогревает
   cache для оставшихся IDs batch (до 100); файлы скачиваются по одному. PostgreSQL
   `provider_budgets` задаёт общий Hinamizawa pacing 1.05 s и cooldown для API/workers.
   Official verify сохраняет свой прежний контракт; общий official budget ещё нужен
   перед масштабированием этого endpoint.
7. Вместо disk staging из исходного проекта M2 используем временные bytes в RAM.
   Перед CPU фиксируем observed SHA-256 в job. После аварии/retry выполняется полный
   GET с этим pin; другая редакция отклоняется. До первого наблюдения ID означает
   доступную редакцию на момент обработки. Disk cleanup/orphan TTL не нужны, потому
   что сервис не создаёт source files. Историческая редакция может исчезнуть у
   provider: такой retry не гарантирован. Это осознанный компромисс вместо хранения
   карт и последующей файловой очистки. Пользовательские корпуса не затрагиваются.
8. Cancel атомарно переводит незавершённые элементы в cancelled и отзывает leases;
   завершённые items сохраняются. Остановка работы кооперативна. Уже запущенный CPU
   может закончить и сохранить валидный дедуплицированный analysis, но отменённый
   item не получит поздний success. HTTP API остаётся локальным, без пользовательской auth.

## Alternatives

- Commit DB, затем одиночная отправка без outbox/reconciliation: потеря доставки.
- ACK до сохранённого состояния: потеря job при аварии.
- Неограниченный requeue: повторная нагрузка без Retry-After.
- Disk staging: сохранит доступность конкретных bytes между retry, но добавит
  хранение, shared volumes, управление квотой и cleanup. Вернуться при таком сценарии.
- Отдельная outbox table: потребуется при нескольких независимых событиях job;
  сейчас одна повторяемая notification полностью выводится из её состояния.

## Sources

- [RabbitMQ acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms).
- [aio-pika work queues](https://docs.aio-pika.com/rabbitmq-tutorial/2-work-queues.html).
- [aio-pika API](https://docs.aio-pika.com/apidoc.html).

## Consequences

При недоступном broker API продолжает принимать ограниченные пакеты в PostgreSQL;
без dispatcher/worker прогресс не обещается. Single-node RabbitMQ с volume не
заявляется HA. Ошибочные notifications без job не исполняются; malformed messages
отбрасываются, due jobs будут опубликованы снова. Восстановление после потери broker
volume возможно из jobs БД, при сохранности самой БД и доступности input у зеркала.

## Revisit conditions

Нужны сохранённые исторические bytes, несколько событий на job, другой provider,
публичный multi-user API, HA или измеренная необходимость большей пропускной способности.
