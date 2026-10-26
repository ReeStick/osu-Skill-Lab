# Runtime queue и мощность worker

Status: Implemented for current basic analysis; difficulty/tag providers pending
Date: 2026-10-26

Используется существующая долговечная очередь M2 `osu.analysis-items.v1` и PostgreSQL
jobs/outbox/leases. Dispatcher отправляет ID job, отдельный worker получает задания
и исполняет текущий reader/basic pipeline. Новая очередь на каждую мощность машины
или второй orchestrator не нужны. Решение: [ADR-0009](../adr/0009-worker-concurrency.md).

## Настройка

```text
uv run --locked python -m osu_skill_lab.workers worker
uv run --locked python -m osu_skill_lab.workers worker --concurrency 4
```

По умолчанию одна карта. `OSU_LAB_WORKER_CONCURRENCY=1..32` задаёт capacity экземпляра;
CLI `--concurrency N` имеет приоритет. Аргумент применим только к worker, для
dispatcher/выхода за диапазон CLI завершается до запуска ресурсов. Compose передаёт
ту же env setting; существующий `.env` автоматически не меняется.
Capacity выбирается на старте; для изменения нужно перезапустить экземпляр.

```powershell
$env:OSU_LAB_WORKER_CONCURRENCY='3'
docker compose up --build --wait api dispatcher worker
```

На разных машинах workers подключаются к одной PostgreSQL БД и тому же RabbitMQ
vhost/queue через `OSU_LAB_DATABASE_URL` / `OSU_LAB_RABBITMQ_URL`; каждому процессу
можно задать свой N. Сетевые адреса DSN должны быть доступны с соответствующей
машины. В локальном Compose порты остаются loopback. API/dispatcher не обязаны
находиться на каждом worker host. Можно запускать несколько экземпляров worker.

Одна job всегда одна карта. N — число одновременно обрабатываемых jobs, не размер
неделимого пакета. У каждого элемента свои lease, retry, cancel и analysis ID.
Capacity машины не включается в identity математического расчёта.

## Backpressure и CPU

Одно значение N настраивает:

- RabbitMQ consumer prefetch (до N unacked messages);
- application slots исполнения (до N обработчиков);
- admission/активные импорты разных карт;
- `AnalysisService` CPU slots и максимум процессов `ProcessPoolExecutor`.

Используется настоящий broker consumer с bounded prefetch и TaskGroup/semaphore.
Свободный slot берётся до чтения следующего message; leases создаются только при
claim job, а не для неограниченного локального backlog. Каждая завершённая job
ACK-ается после своего сохранённого перехода. Невалидный message отклоняется без
исполнения; duplicate/terminal job распознаётся по БД.

Mirror import использует lock по map ID и общий semaphore активных импортов вместо
одного lock вокруг всех CPU-расчётов. Одинаковые IDs в одном процессе могут
переиспользовать свежий cached result, разные карты не ждут его CPU завершения.
На разных workers возможен повтор CPU для одинакового input, сохранение защищено
прежними unique constraints. Общий PostgreSQL provider budget Hinamizawa действует
для всех экземпляров; рост N не увеличивает разрешённую частоту upstream запросов.
Внутри HTTP client сетевые операции по-прежнему сериализованы, CPU — параллелен.

CPU pool ограничен N, вход каждой карты — прежние 4 MiB. RAM/parsed data и CPU
нагрузка растут с выбранной capacity; автоподбор N по числу ядер не вводится.
HTTP синхронный import сохраняет прежние defaults: один активный import и один
ожидающий. Настройка worker не меняет количество CPU-процессов API.

## Остановка и восстановление

При завершении/ошибке TaskGroup отменяет активные handlers; unacked messages
возвращаются после закрытия канала/соединения. Работающий native CPU не считается
мгновенно остановленным: прежний analysis slot удерживается до завершения future,
pool при shutdown дожидается процессов. Lease recovery остаётся в dispatcher.

Фатальный отказ CPU pool внутри группы сохраняет retry текущей job, отменяет
соседние handlers и доходит до exit 1 worker. Compose restart создаёт новый pool;
ошибка не теряется внутри ExceptionGroup с бесконечным reconnect старого pool.
Ранее завершённые job/results сохраняются независимо от соседей.

## Границы этого среза

Runtime consumer реально выполняет существующий basic pipeline. Новый difficulty
engine, registry tag definitions, stage DAG и GPU dispatch пока не реализованы.
Будущие providers подключаются к независимому обработчику job; отдельные resource
очереди появятся при первом работающем GPU/ином stage, не заранее.
30 s остаются мягким ориентиром [tag-pipeline](tag-pipeline.md), не новым timeout.
Ни ускорение, ни линейное масштабирование, ни latency на большой библиотеке пока
не измерены. Проверенные сценарии: [devlog](../devlog/2026-10-26-runtime-worker-concurrency.md).
