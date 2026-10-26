# osu! Skill Lab

Backend для воспроизводимого анализа карт osu!standard: измеряемые признаки →
skill profile → контекстная классификация турнирных слотов. Эти уровни не заменяют
difficulty или PP и будут развиваться отдельно.

Реализованы **M0 — Project Foundation** и **M1 — Beatmap Analysis MVP**:
локальная подготовка `.osz`, reader `.osu` v14, расчёт 22 базовых признаков
в отдельных процессах, REST upload и сохранение результатов в PostgreSQL.
Постоянно хранятся компактные metadata, checksums и скалярные результаты;
загруженный файл и разобранные объекты используются только в памяти.
Skill profile и турнирные слоты — следующие этапы.
В M1a добавлена явная сверка загруженной карты с metadata osu! API по checksum.
Первый срез M2 добавил raw import из Hinamizawa и отдельное хранение происхождения файла.
M2 завершён: пакетные задания сохраняются в PostgreSQL и исполняются через RabbitMQ
отдельным worker с retry/cancel и получением прогресса.

На M0 проверены установка из lock, 25 тестов (включая PostgreSQL), Ruff,
mypy, миграции и запуск Docker API. Подробности и реальные неудачные попытки —
в [devlog](docs/devlog/2026-10-25-project-foundation.md).
Удалённый запуск GitHub Actions ещё не выполнялся.

## Загрузка и сохранённый анализ

После запуска API отправьте исходные байты одного `.osu`, без multipart:

```powershell
curl.exe --fail --header "Content-Type: application/octet-stream" --data-binary "@tests/fixtures/analytic-v14.osu" http://localhost:8000/analyses
Invoke-RestMethod http://localhost:8000/analyses
```

В Bash используйте `curl` вместо `curl.exe`. Ответ содержит `id`, `beatmap`,
версии алгоритма/reader, конфигурацию, исходные difficulty settings и `features`.

- `POST /analyses`: `201` для нового результата, `200` для той же комбинации
  байтов, версий и конфигурации. Повтор сохраняет прежние `id` и время создания.
- `GET /analyses/{id}`: сохранённый результат или `404`.
- `GET /analyses?limit=20&after_id=0`: страницы по возрастанию ID;
  `next_after_id=null` означает конец. Допустим `limit` от 1 до 100.
  Необязательный `claimed_beatmap_id` фильтрует IDs, заявленные в файле.
- Максимум 4 MiB на `.osu`; больший вход — `413`, неверный формат — `422`,
  неподходящий Content-Type — `415`. При занятых двух слотах обработки на
  экземпляр API — `429` с `Retry-After: 1`; при недоступности БД/процессов — `503`.

Это синхронный HTTP-сценарий с ожиданием CPU-процесса, без долговечной очереди.
Он не пишет исходники на диск. Диагностический `inspect-osu` выводит сводки,
а анализ получает реальные объекты reader в памяти. Свои локальные архивы и
файлы команды `extract-osz` HTTP-сервис не удаляет.

SHA-256 обозначает точные исходные байты, MD5 сохраняется для совместимого
checksum lookup. IDs из upload остаются claims:
`identity_status="unverified"` до явной сверки через `verify-osu`.
Для повторного расчёта новым алгоритмом нужно
снова передать файл с соответствующим SHA-256; metadata не восстанавливает объекты.

Определения измерений: [basic-features](docs/architecture/basic-features.md).
Схема хранения: [database](docs/architecture/database.md), решение:
[ADR-0003](docs/adr/0003-transient-inputs-compact-results.md).
Последняя проверка: 259 тестов, включая 23 интеграционных с PostgreSQL.
Проверки M1a: [devlog](docs/devlog/2026-10-25-osu-api-verification.md).
Для M1 также проверен Docker API на 33 локальных картах. Детали и замер хранения —
в [devlog M1](docs/devlog/2026-10-25-compact-analysis-pipeline.md).

## Сверка с osu! API

В локальном `.env` задайте `OSU_LAB_OSU_CLIENT_ID` и `OSU_LAB_OSU_CLIENT_SECRET`
из зарегистрированного OAuth application osu!, затем пересоздайте API.
Секрет остаётся локально; endpoint его не принимает. Настройки опциональны:
без них raw upload и чтение анализов работают, свежая внешняя сверка даёт 503.

```powershell
docker compose up -d --wait api
Invoke-RestMethod -Method Post http://localhost:8000/analyses/1/verify-osu
```

Укажите ID своего анализа. Успех возвращает тот же анализ с
`beatmap.identity_status="checksum_match"`, отдельным `beatmap.osu` и сравнением
claimed IDs. Метаданные файла остаются прежними; сохраняется выбранная metadata
сайта и время наблюдения. GET не обращается к внешнему API.

Есть OAuth token cache, TTL/cache в БД, pacing и обработка rate limit/timeout.
Подробный контракт и настройка: [osu-api](docs/architecture/osu-api.md).
Живая авторизованная проверка выполнена: checksum совпал, повторная сверка
переиспользовала cache, GET вернул сохранённые metadata.
Текущий сценарий использует загруженный `.osu`; архивы через API не скачиваются.

## Импорт одной карты из Hinamizawa

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/imports/hinamizawa/1960574
```

Укажите beatmap ID отдельной difficulty. Endpoint получает metadata и raw `.osu`
без медиа, проверяет MD5, выполняет локальный CPU-анализ и сохраняет result/source
атомарно. Ответ — 201 или 200 при переиспользовании. `beatmap.sources` содержит
provider, версии адаптера, checksum и времена наблюдений. Официальная сверка
в `beatmap.osu` остаётся независимой. Опциональный `expected_sha256` фиксирует bytes.

Этот endpoint ждёт результат в HTTP; для фонового пакета используйте API ниже.
Контракт и ограничения: [mirror-import](docs/architecture/mirror-import.md).
Живая загрузка одной `.osu` 112 844 bytes и повтор/GET проверены:
[devlog M2](docs/devlog/2026-10-25-hinamizawa-import.md).

## Пакетный анализ в фоне

Запустите `docker compose up --build --wait api dispatcher worker`, затем:

```powershell
$key = [guid]::NewGuid().ToString()
$body = @{items=@(@{beatmap_id=1960574}, @{beatmap_id=658127})} | ConvertTo-Json -Depth 4
$batch = Invoke-RestMethod -Method Post http://localhost:8000/analysis-batches -ContentType application/json -Headers @{'Idempotency-Key'=$key} -Body $body
Invoke-RestMethod "http://localhost:8000/analysis-batches/$($batch.id)"
```

202 подтверждает сохранённое задание. До 100 entries, одинаковые ID/pin удаляются;
на item можно передать `expected_sha256`. Повтор с тем же key/body возвращает тот же
пакет; другой body — 409. Ответ содержит статус, attempts и analysis ID каждого item,
частичная ошибка сохраняет успешные результаты. Отмена:
`POST /analysis-batches/{id}/cancel`. До 1000 unfinished jobs; перегрузка — 429.

При недоступном broker задания остаются в БД до восстановления dispatcher/worker.
Bytes только RAM; retry повторяет загрузку с observed SHA-256, поэтому историческая
редакция должна оставаться доступной у зеркала. Официальная сверка независима,
автоматического переключения с official API на mirror нет. Контракт:
[batch-processing](docs/architecture/batch-processing.md), проверенный живой batch:
[devlog](docs/devlog/2026-10-26-durable-batch-processing.md).

## Мощность worker

По умолчанию worker обрабатывает одну карту. Для нескольких одновременно:

```text
uv run --locked python -m osu_skill_lab.workers worker --concurrency 4
```

Или задайте `OSU_LAB_WORKER_CONCURRENCY=4` в окружении экземпляра (1..32).
CLI имеет приоритет над env. В Compose передаётся та же настройка. Она согласует
broker prefetch, активные imports и CPU processes; API pool от неё не меняется.
На разных машинах можно запускать workers с разными N, подключённые к общей БД
и RabbitMQ. Каждая job — одна карта со своими retry/status, не неделимый пакет.
Общий budget запросов к зеркалу сохраняется при масштабировании.
Контракт и ограничения: [runtime-workers](docs/architecture/runtime-workers.md).

## Извлечение .osu из локальных .osz

После `uv sync --locked` можно подготовить предоставленные локальные карты:

```powershell
uv run --locked osu-skill-lab extract-osz tests/unlabeled_osu_maps
```

БД и запущенный API для этой команды не нужны. Результат:
`data/unpacked_osu_maps/<archive-sha256>/*.osu` и `manifest.json` с исходными
именами, размерами и checksums. Извлекаются только `.osu`. Исходные архивы
не меняются; повторный запуск проверяет и переиспользует совпадающий результат.
Можно передать один `.osz` и `--output-dir`. Подробности, лимиты и коды возврата:
[контракт локального импорта](docs/architecture/local-import.md).
Скачанные карты и выходные файлы исключены из Git; CI использует синтетические ZIP.
Проверки этого среза: 56 unit-тестов; на локальном корпусе извлечены и побайтово
сверены 33 карты из 12 архивов. Итоги — в
[devlog](docs/devlog/2026-10-25-local-osz-extraction.md).

## Чтение параметров карты

```powershell
uv run --locked osu-skill-lab inspect-osu data/unpacked_osu_maps --recursive
```

Команда читает metadata, AR/OD/CS/HP, настройки слайдеров, timing points и
hit objects. Аудио, видео, фон, storyboard и samples не загружаются.
Результат — JSON Lines с исходными параметрами, counts и BPM extrema.
Это исходные настройки без модификаторов; star rating и PP пока не вычисляются.

Поддержан osu!standard v14/UTF-8. Контракт и ограничения:
[osu-parser](docs/architecture/osu-parser.md). Все 33 локальные карты успешно
прочитаны; локальные сводки сохранены в `data/map-summaries.jsonl` и исключены из Git.
На этапе reader проверены 126 unit-тестов. Подробности:
[devlog парсера](docs/devlog/2026-10-25-analytical-osu-reader.md).

## Быстрый запуск в Docker

Нужны Git и работающий Docker Engine с Compose v2+. Команды выполняются из корня.

```powershell
Copy-Item .env.example .env
docker compose up --build --wait api dispatcher worker
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
```

На Linux/macOS вместо `Copy-Item` используйте `cp`, вместо `Invoke-RestMethod` — `curl --fail`.
Compose дождётся PostgreSQL/RabbitMQ, выполнит миграции отдельным процессом и
запустит API, dispatcher и worker. Повторный запуск безопасен для применённой миграции.

- Swagger UI: <http://localhost:8000/docs>.
- `GET /health/live` → `200 {"status":"ok"}` без подключения к БД.
- `GET /health/ready` → `200` при успешном `SELECT 1`, иначе `503` без деталей подключения.
  Это проверка доступности БД, а не актуальности её схемы; миграции запускаются отдельно.
- `docker compose logs api migrate db` — журналы.
- `docker compose down` — остановка; данные остаются в named volume.

Порты привязаны к `127.0.0.1`. Учётные данные в примере публичные, только для локальной
разработки. Это не конфигурация публичного развёртывания. Меняя пароль, используйте
URL-safe значение в Compose; в собственном DSN спецсимволы необходимо URL-кодировать.
Меняя `POSTGRES_PORT`, измените также порт host DSN в `OSU_LAB_DATABASE_URL`.
Внутри Compose API всегда использует `db:5432`.
Переменные `POSTGRES_*` инициализируют только новый volume; смена их значений
не изменяет пользователей и пароли существующей БД.

## Локальная разработка с uv

Нужны [uv](https://docs.astral.sh/uv/getting-started/installation/) и Python 3.12+
(uv умеет установить Python). Python проекта закреплён в `.python-version`.

```powershell
Copy-Item .env.example .env
uv python install 3.12
uv sync --locked
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked uvicorn osu_skill_lab.main:create_app --factory --reload
```

Не запускайте локальный API и Compose API на одном порту одновременно.
`OSU_LAB_DATABASE_URL` обязателен: читается из окружения или `.env` относительно
текущего каталога. Окружение имеет приоритет. Драйвер — только `postgresql+asyncpg`.
`OSU_LAB_ENVIRONMENT`: `local`, `test`, `production` (по умолчанию `local`);
`OSU_LAB_DATABASE_TIMEOUT_SECONDS`: общий лимит readiness от >0 до 30 секунд (по умолчанию 3).
API создаёт пул в lifespan и закрывает его при остановке. Импорт модулей не подключается к БД.

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -m "not integration"
```

Интеграционные тесты используют **настоящий PostgreSQL**, отдельную БД с суффиксом
`_test` и временные схемы. SQLite не проверяет поведение PostgreSQL.
Один раз создайте тестовую БД (команда ниже соответствует `.env.example`):

```powershell
docker compose exec db createdb -U osu_lab osu_skill_lab_test
$env:OSU_LAB_TEST_DATABASE_URL = "postgresql+asyncpg://osu_lab:osu_lab_local@localhost:5432/osu_skill_lab_test"
$env:OSU_LAB_TEST_RABBITMQ_URL = "amqp://osu_lab:osu_lab_local@localhost:5672/"
uv run --locked pytest
```

На Bash: `export OSU_LAB_TEST_DATABASE_URL='postgresql+asyncpg://…/osu_skill_lab_test'`.
Переменная тестов читается из **окружения процесса**, не из `.env`.
Без неё интеграционные тесты явно пропускаются; с недоступной или некорректной БД — падают.
Тестовый пользователь должен иметь право `CREATE SCHEMA` в тестовой БД.
Случайные схемы `test_<uuid>` удаляются после тестов; не направляйте тесты на рабочие данные.
RabbitMQ tests требуют `docker compose up -d --wait rabbitmq` и переменную
`OSU_LAB_TEST_RABBITMQ_URL`. Без неё delivery tests skip; очереди тестов имеют
случайные имена `test.<uuid>` и удаляются после проверки.

## Миграции

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

Начальная ревизия `0001_foundation` создаёт только историю Alembic;
`0002_compact_analysis` добавляет `beatmap_inputs` и `analysis_results`,
`0003_osu_metadata` — `osu_beatmap_matches` для выбранной внешней metadata.
`0004_sources` добавляет `beatmap_sources` с версионируемыми download observations.
`0005_batch_jobs` добавляет `analysis_batches`, `analysis_jobs` и `provider_budgets`.
При добавлении моделей импортируйте их в `migrations/env.py`, создавайте
`uv run --locked alembic revision --autogenerate -m "description"` и проверяйте SQL
и downgrade вручную. `create_all()` при старте API не используется.
Не выполняйте downgrade на ценных данных без анализа последствий.

## Структура и история

```text
src/osu_skill_lab/       factory, config, CLI, api/, application/, analysis/, infrastructure/, workers/
migrations/             Alembic env, template, versioned revisions
tests/unit/             reader, features, extraction, CLI, HTTP, capacity and cancellation
tests/integration/      real PostgreSQL, concurrency, migrations and full upload flow
docs/architecture/      architecture, diagrams and current/planned data model
docs/adr/               significant architecture decisions
docs/devlog/            factual development history and verification results
docs/experiments/       research hypotheses and measured results
docs/milestones/        acceptance criteria and actual progress
docs/articles/          source material for future technical publications
.github/workflows/      quality checks, PostgreSQL integration, Docker smoke test
```

Следующие шаги и ограничения: [TASKS.md](TASKS.md), [ROADMAP.md](ROADMAP.md).
M1a — osu! API metadata/identity завершён с живой OAuth-проверкой.
M2 — [пакетный импорт через очередь](docs/architecture/batch-processing.md) завершён.
Следующий этап — M3: versioned difficulty engine, затем собственные признаки.
Для дальнейших метрик принят [контракт эволюции](docs/architecture/metric-evolution.md):
официальный difficulty/pp — первая основа, точные версии вычислителей и отдельные
семейства результатов; собственные показатели добавляются позднее.
Для M3 также приняты [контракты тегов и обработки](docs/architecture/tag-pipeline.md):
версионируемые определения/методы, timing/slider geometry и будущие ML providers,
мягкий budget около 30 s и возможные GPU stages. Это архитектурный план, не уже
реализованные классификаторы или измеренная производительность.
CPU runtime queue и регулируемая capacity worker уже работают на basic pipeline;
новый difficulty engine и tag providers подключаются следующими срезами M3.
Начните новую сессию с [AGENTS.md](AGENTS.md) и состояния Git.
Архитектура: [overview](docs/architecture/overview.md), [БД](docs/architecture/database.md).
Изменения продукта: [CHANGELOG.md](CHANGELOG.md); история решений: [devlog](docs/devlog/README.md).

Зависимости фиксируются в `uv.lock`; CI и Docker используют `--locked`
([семантика uv](https://docs.astral.sh/uv/concepts/projects/sync/)).
Async-миграции используют `run_sync` по [рекомендации Alembic](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).
Публикация и push требуют отдельного разрешения владельца.
