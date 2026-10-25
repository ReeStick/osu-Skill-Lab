# osu! Skill Lab

Backend для воспроизводимого анализа карт osu!standard: измеряемые признаки →
skill profile → контекстная классификация турнирных слотов. Эти уровни не заменяют
difficulty или PP и будут развиваться отдельно.

Реализован **Milestone 0 — Project Foundation**. Доступны FastAPI,
проверки состояния, PostgreSQL, SQLAlchemy async, Alembic, тесты и CI.
Начат Milestone 1: доступны локальная подготовка `.osz`, аналитический reader
`.osu` v14 и JSON-сводки через CLI. Импорт через REST, persistence результатов,
skill analysis и фоновые задания ещё не реализованы.

На M0 проверены установка из lock, 25 тестов (включая PostgreSQL), Ruff,
mypy, миграции и запуск Docker API. Подробности и реальные неудачные попытки —
в [devlog](docs/devlog/2026-10-25-project-foundation.md).
Удалённый запуск GitHub Actions ещё не выполнялся.

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
Текущий unit-прогон: 126 passed. Подробности:
[devlog парсера](docs/devlog/2026-10-25-analytical-osu-reader.md).

## Быстрый запуск в Docker

Нужны Git и работающий Docker Engine с Compose v2+. Команды выполняются из корня.

```powershell
Copy-Item .env.example .env
docker compose up --build --wait api
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
```

На Linux/macOS вместо `Copy-Item` используйте `cp`, вместо `Invoke-RestMethod` — `curl --fail`.
Compose дождётся PostgreSQL, выполнит миграции отдельным процессом и запустит API.
Повторный `docker compose up --build --wait api` безопасен для уже применённой миграции.

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
uv run --locked pytest
```

На Bash: `export OSU_LAB_TEST_DATABASE_URL='postgresql+asyncpg://…/osu_skill_lab_test'`.
Переменная тестов читается из **окружения процесса**, не из `.env`.
Без неё интеграционные тесты явно пропускаются; с недоступной или некорректной БД — падают.
Тестовый пользователь должен иметь право `CREATE SCHEMA` в тестовой БД.
Случайные схемы `test_<uuid>` удаляются после тестов; не направляйте тесты на рабочие данные.

## Миграции

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

Начальная ревизия `0001_foundation` создаёт только историю Alembic. Доменных таблиц
пока нет. При добавлении моделей импортируйте их в `migrations/env.py`, создавайте
`uv run --locked alembic revision --autogenerate -m "description"` и проверяйте SQL
и downgrade вручную. `create_all()` при старте API не используется.
Не выполняйте downgrade на ценных данных без анализа последствий.

## Структура и история

```text
src/osu_skill_lab/       FastAPI factory, config, CLI, api/, analysis/, infrastructure/
migrations/             Alembic env, template, versioned revisions
tests/unit/             reader, extraction, CLI, configuration, HTTP and lifecycle
tests/integration/      real PostgreSQL, migrations, transactions, readiness
docs/architecture/      architecture, diagrams and current/planned data model
docs/adr/               significant architecture decisions
docs/devlog/            factual development history and verification results
docs/experiments/       research hypotheses and measured results
docs/milestones/        acceptance criteria and actual progress
docs/articles/          source material for future technical publications
.github/workflows/      quality checks, PostgreSQL integration, Docker smoke test
```

Следующие шаги и ограничения: [TASKS.md](TASKS.md), [ROADMAP.md](ROADMAP.md).
Начните новую сессию с [AGENTS.md](AGENTS.md) и состояния Git.
Архитектура: [overview](docs/architecture/overview.md), [БД](docs/architecture/database.md).
Изменения продукта: [CHANGELOG.md](CHANGELOG.md); история решений: [devlog](docs/devlog/README.md).

Зависимости фиксируются в `uv.lock`; CI и Docker используют `--locked`
([семантика uv](https://docs.astral.sh/uv/concepts/projects/sync/)).
Async-миграции используют `run_sync` по [рекомендации Alembic](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).
Публикация и push требуют отдельного разрешения владельца.
