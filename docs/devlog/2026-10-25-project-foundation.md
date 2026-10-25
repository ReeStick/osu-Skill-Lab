# 2026-10-25 — Project Foundation

## Цель

Подготовить законченный M0 без импорта карт и анализа, с воспроизводимым запуском
и документами для продолжения работы в следующей сессии.

## Исходная проблема

В рабочем каталоге были только `.git` и стандартный Python `.gitignore`.
В Git уже существовал коммит `2964a23` (`Initial commit`); изменений пользователя
не было. README, приложения, тестов и проектной конфигурации не было.

## Рассмотренные решения

1. Сразу создать все слои и доменные таблицы из ТЗ.
2. Создать минимальный работающий срез и добавлять границы по мере необходимости.
3. Проверять persistence на SQLite либо настоящем PostgreSQL.

## Принятое решение

Вариант 2 с PostgreSQL integration. Выделены транспорт, конфигурация и адаптер БД;
доменные слои отложены. Начальная миграция без DDL фиксирует lineage Alembic.
Приняты [ADR-0001](../adr/0001-modular-monolith.md) и
[ADR-0002](../adr/0002-postgresql-async.md).

## Реализация

Первоначальный план: структура и uv → FastAPI/config → БД/Alembic/Compose →
тесты/CI → документация → проверка полного запуска → локальные коммиты.

- Созданы `src`-пакет, FastAPI factory, настройки и live/ready.
- Добавлены SQLAlchemy async, сессии и Alembic baseline без бизнес-таблиц.
- Добавлены Dockerfile и Compose с migration service, тесты и CI.
- Созданы roadmap, задачи, инструкции агентам, ADR и разделы журнала исследований.
- Создан `uv.lock`; runtime и dev зависимости устанавливаются с `--locked`.
- Для типизации добавлены маркер `py.typed`, Pydantic mypy plugin и asyncpg stubs
  (последние только в dev). GitHub Actions закреплены на SHA по официальному
  [руководству uv](https://docs.astral.sh/uv/guides/integration/github/).
- Актуальные исходники: [main.py](../../src/osu_skill_lab/main.py),
  [database.py](../../src/osu_skill_lab/infrastructure/database.py),
  [tests](../../tests), [Compose](../../compose.yaml).

## Проблемы

- `git` отсутствовал в PATH. Найден установленный Git, использован полный путь.
- `python` запускал 3.11.9; `py -0p` показывал 3.12, но путь был нерабочим.
  Решение: локальный uv и управляемый Python внутри игнорируемого `.tools`.
- Docker CLI установлен, но первая попытка не нашла pipe daemon; после команды
  `docker desktop start` движок доступен. Sandbox запрещал доступ к pipe и сети;
  для реального запуска и установки uv запрошено разрешение выхода из sandbox.
- Первая установка uv в sandbox завершилась `No matching distribution found`.
  Повтор с доступом к сети установил uv 0.13.5. Это ограничение среды,
  а не несовместимость зависимостей проекта.
- Загрузка управляемого Python внутри sandbox завершилась сетевой ошибкой.
  Повтор с разрешённым сетевым доступом установил Python 3.12.15.
- Первый Ruff нашёл вложенные context managers и две длинные строки тестов.
  Исправлены структура и форматирование.
- Первый mypy не связывал imports с `src`-пакетом. Указаны `mypy_path`,
  `explicit_package_bases`, добавлен `py.typed`. Затем обнаружилась необходимость
  Pydantic plugin для env-полей BaseSettings; включён plugin с типизированным init.
  Ошибки не скрывались общим `ignore_missing_imports`.
- Первый Pytest: 20 passed, 1 error — sandbox запретил временный каталог Windows.
  В том запуске появилась и ошибка доступа к pytest cache; повтор с доступом
  вне sandbox прошёл. Две оставшиеся временные папки удалены по точным проверенным
  путям внутри workspace. Проверки Git после уборки не сообщают об этих папках.
- Новый Starlette предупреждал об устаревающем HTTPX-адаптере TestClient.
  Тесты переведены на HTTPX AsyncClient + ASGITransport с явным lifespan.
- Один запуск Ruff в sandbox сообщил access denied и завершился panic
  `Expected a ruff source file`. Повтор вне sandbox прошёл; внутреннюю причину
  panic отдельно не исследовали.
- Первая Docker-сборка прервалась на TLS handshake timeout при получении uv
  из GHCR. Повтор той же сборки сработал, Dockerfile менять не потребовалось.
- Первый ручной probe сбоя БД не выполнился: PowerShell убрал кавычки из
  `python -c`. Блок finally восстановил БД. Повтор через временный `.py`-файл
  в `.tools` подтвердил ожидаемые HTTP-коды.

## Проверки

Среда: Windows, Python 3.12.15, uv 0.13.5, Docker Engine 29.3.1,
Compose 5.1.1, PostgreSQL 17. Версии Python-зависимостей — в `uv.lock`.
Для команд uv в этой среде использован `.tools/Scripts/uv.exe`,
`UV_CACHE_DIR=<repo>/.tools/uv-cache` и `UV_PYTHON_INSTALL_DIR=<repo>/.tools/python`.

| Команда / сценарий | Фактический итог |
| --- | --- |
| `uv sync --locked`, `uv lock --check` | Установка и актуальность lock подтверждены |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 33 files already formatted |
| `uv run --locked mypy` | Success: no issues found in 17 source files |
| `uv run --locked pytest` с `OSU_LAB_TEST_DATABASE_URL` | 25 passed, без skip; финальный прогон 27.72s |
| `alembic upgrade head`, `current`, `check`, `downgrade base`, `upgrade head` | Head `0001_foundation`, drift не обнаружен, цикл успешен |
| `docker compose config --quiet` | Конфигурация корректна |
| `docker compose up --build --wait api` | Сборка успешна; БД/API healthy, migrate exit 0 |
| HTTP host-запросы `/health/live`, `/health/ready`, `/docs`, `/openapi.json` | Все HTTP 200 |
| `docker compose stop db` и host HTTP probe | live=200, ready=503 |
| `docker compose up -d --wait db` и повторный probe | ready=200 без перезапуска API |
| `docker compose up --wait api`, `docker compose exec -T api id` | Повторный запуск успешен; uid=10001(app) |
| `git diff --check`, `git check-ignore .env .tools .venv` | Whitespace errors не найдены; локальные данные исключены |

21 unit-тест проверяет настройки, env precedence, защиту DSN от вывода,
HTTP-контракты, ожидаемые классы сбоев, общий timeout и закрытие пула.
4 integration-теста проверяют реальный PostgreSQL, commit/rollback, миграции
в изолированной схеме и readiness без mock. Для них создана отдельная
локальная БД `osu_skill_lab_test`.

Alembic CLI выполнялся напрямую через `.venv/Scripts/alembic.exe`; та же
конфигурация запускается в Docker migration service. Начальный baseline без DDL
не проверяет будущую бизнес-схему. Удалённые GitHub Actions не запускались;
push не выполнялся. После проверок контейнеры API и БД оставлены работающими
на loopback-портах 8000 и 5432, данные — в named volume.

## Что я узнал

Наличие интерпретатора в выводе launcher не доказывает, что он запускается.
Проверки инфраструктуры должны включать реальное подключение, а не только
наличие клиентских программ. Пустая baseline-миграция не проверяет будущие
ограничения бизнес-таблиц.

## Что можно улучшить

Определить лицензию с владельцем. Перед публичным релизом закрепить образы
по digest и принять политику обновлений. Добавлять новые гарантии очереди и
версий только вместе с реализованным сценарием и его тестами.

## Следующие шаги

M0 завершён. Код, проверки и исходные документы сохранены локальным коммитом
`75af7c5b9f00d7bc827f80add2bfc62fcbc3780f`
(`chore: initialize verified FastAPI and PostgreSQL foundation`).
Просмотр: `git show 75af7c5`. Ссылка на удалённый коммит не публикуется:
push не выполнялся. Закрытие checklist и привязка devlog к этому коммиту
оформляются отдельным документационным коммитом.

Следующая отдельная итерация — контракт
безопасного локального импорта и независимый parser с синтетическими `.osu`
fixtures. В этой итерации M1 не начинался.
