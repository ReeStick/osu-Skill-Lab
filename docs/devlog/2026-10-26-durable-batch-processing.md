# 2026-10-26 — Долговечные batch jobs и RabbitMQ worker

## Результат

M2 доведён до пакетного API, отдельных dispatcher/worker, восстановления job и
частичных результатов. Runtime: [batch-processing](../architecture/batch-processing.md).
Решение: [ADR-0007](../adr/0007-durable-batch-delivery.md). Difficulty/pp engine
не подключался, это следующий M3. Работа началась 25 октября, завершение отражено
датой владельца 26 октября после смены суток Europe/Moscow.

## Реализация

Добавлены `analysis_batches`, `analysis_jobs`, `provider_budgets` и Alembic
`0005_batch_jobs`. Job одновременно представляет item и delivery intent; отдельный
payload/outbox JSON не нужен. HTTP 202 следует только после commit. UUID idempotency
key, request hash, 100-entry limit, dedup/pins и глобальная квота 1000 unfinished jobs.

RabbitMQ получает только version/item_id, persistent с publisher confirm. Dispatcher
держит короткий row lock на одну публикацию; восстановление delivery/leases через
PostgreSQL. Worker использует 90 s lease/15 s heartbeat, fenced updates, ACK после
сохранённого перехода, максимум пять попыток. Ошибки отдельных карт не откатывают
успешные; cancel отзывает unfinished leases. Result/source commit и job success —
две транзакции, поэтому повтор CPU возможен; результат дедуплицируется.

Перед CPU job фиксирует SHA-256. В отличие от первоначального проекта disk staging
не создаётся: retry делает новый GET с pin, исчезнувшая редакция не восстанавливается.
Приём также фиксирует algorithm/parser/config identity. Общий PostgreSQL budget
Hinamizawa подключён к API и worker. Official verify/fallback не изменялись.

Добавлен aio-pika 9.6.2, lock обновлён с шестью новыми транзитивными/runtime packages.
Compose поднимает RabbitMQ volume, dispatcher и worker; CI настроен на real broker,
удалённо не запускался. Сломанный CPU pool сохраняет retry и завершает worker с
exit 1 для Compose restart policy; HTTP сохраняет 503 contract.

## Проверки

Использовались `.venv`, PostgreSQL `_test` с isolated Alembic schemas и локальный
RabbitMQ через `OSU_LAB_TEST_RABBITMQ_URL`. Команды из корня:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_config.py tests/unit/test_preparation.py tests/unit/test_analysis_service.py tests/unit/test_analysis_api.py tests/unit/test_hinamizawa.py tests/unit/test_mirror_import.py tests/integration/test_mirror_import.py tests/integration/test_analysis_persistence.py --tb=short
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_batches.py tests/integration/test_batches.py tests/integration/test_batch_worker.py tests/integration/test_migrations.py --tb=short
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_batch_worker.py tests/unit/test_analysis_service.py tests/unit/test_analysis_api.py --tb=short
```

Результаты: **117 passed (8.34 s)**, **39 passed (10.86 s)**,
после CPU restart правки **45 passed (6.86 s)**. Совокупно 157 уникальных cases;
это целевые прогоны с пересечением, не полный pytest. Неизменённые parser/features/
osz/CLI и независимые official API unit не перезапускались.

Проверены concurrent idempotency/admission, replay conflict, cancel, versions,
shared pacing/cooldown, five-attempt exhaustion, due times, stale lease fencing,
source pins между попытками и rollback intent при publish failure. Real RabbitMQ:
consumer connection закрыт без ACK, delivery переотдан; lease expiration инъецирован
в БД, новый worker продолжил job. Другой тест публикует с confirm, инъецирует ошибку
до DB commit, публикует повтор и проверяет единственного владельца job. Это
управляемые crash injections, не заявление о нагрузочном тесте или HA.

Первый прогон новых модулей: 25 passed/1 failed, причина — Windows sandbox запретил
multiprocessing pipe в lifespan. Повтор этого HTTP-теста вне sandbox — passed;
финальные целевые команды выше также вне sandbox. Первоначальный uv sync не смог
достучаться до PyPI через sandbox proxy; повтор с разрешением установил dependency.
Сгенерированные составные unique names имели коллизию, она исправлена при review
до миграционных тестов. Mypy указал optional bool в RabbitMQ test — исправлено.

Финальные `ruff check .`, `ruff format --check .`, `mypy` — passed: 116 файлов
форматирования, 75 source files. `uv sync --locked --offline` проверил 45 packages.
Локальный `.tools/check_metric_docs.py` проверил 26 Markdown files/144 relative links.
`git diff --check` прошёл; предупреждение CRLF касается пользовательского `.gitignore`,
который не включается в коммит.

## Docker и живой batch

`docker compose up -d --wait rabbitmq db` и первый
`docker compose up --build --wait api dispatcher worker` прошли. Локальный
`.tools/check_batch_import.py` отправил три entries: 1960574 с прежним SHA pin,
658127 и повтор 1960574. Получены 202 и повторный 202 с тем же batch UUID
`c9eb7307-6a5f-4131-9951-3d8fc9fd69cf`; dedup оставил два items.

Оба items succeeded за одну попытку. Analysis №1 переиспользован, для второго
получен analysis №72 (sequence gaps не означают число скачанных карт). Прежние
features/settings/версии/created_at и official observation №1 сохранены. Raw файлы
и media на диск не записывались. Номер карты, hashes и metadata здесь не заменяют
официальную сверку второго input.

Во время завершающей сверки Docker Engine оказался остановлен. `docker desktop start`
восстановил daemon, `compose up -d --wait db rabbitmq` — сервисы. Повтор полной
сборки получил TLS handshake timeout Docker Hub при HEAD python base; повтор вне
sandbox также не помог. Успешную чистую сборку после последней CPU restart правки
не заявляем. Для runtime проверки использована уже собранная locked база:

```text
docker build --pull=false -f .tools/Dockerfile.batch-smoke -t osu-skill-lab:local .
docker compose up --no-build --wait api dispatcher worker
```

Игнорируемый вспомогательный Dockerfile копирует актуальный пакет и migrations
поверх прежнего локального image с теми же dependencies. Основной Dockerfile/lock
не изменялись ради обхода registry; обычная чистая сборка потребует доступного Hub.
`compose up --no-build --wait` завершился успешно. `alembic current` в API:
`0005_batch_jobs (head)`, `alembic check`: `No new upgrade operations detected`.
SHA-256 текстов application.service, workers.import_worker, workers.__main__
совпали в checkout и контейнере. Повтор GET прежнего batch после восстановления:
completed, оба succeeded, analysis №1 и official observation сохранились. Это
проверка актуального runtime из локальной базы; живой download двух files выполнен
до последнего изменения CPU restart ветки, сама ветка проверена целевым тестом.

## Ограничения и следующий этап

Нет публичной auth, HA, полного журнала попыток, хранения исторических input bytes
или автоматического official→mirror fallback. Official budgets ещё локальны одному
API-процессу. Эти ограничения отражены в контрактах. M3 начнётся с проверки upstream
и port difficulty engine, точного provenance ADR-0004 и отдельных scalar snapshots;
в этом изменении M3 не начат.
