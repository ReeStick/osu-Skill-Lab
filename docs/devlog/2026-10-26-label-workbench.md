# 2026-10-26 — Гибридный интерфейс разметки

## Цель и изменение порядка

Владелец согласовал предложенный гибрид: явная разметка карт, настройка правила
по имеющимся фичам и обучаемый baseline с быстрым preview. Это ранний срез M4,
а не закрытие M3 difficulty/pp или доказательство качества классификации.
Восстановлены AGENTS/TASKS/ROADMAP, архитектура/ADR, последний devlog и Git status.
HEAD до работы — `0c85098`; пользовательские три строки `.gitignore` оставлены отдельно.

## Реализация

- Buildless `/lab`: tag definitions, yes/no/unsure, контрольные карты, undo,
  фильтры/поиск/сортировка, веса/bias/threshold, histogram, версии и `.osu` upload.
- Human labels append-only, optimistic event ID; прогнозы и rules их не изменяют.
  Определение immutable и whole-map NM; для нового критерия нужен новый тег.
- `binary-logistic/1`: sklearn LogisticRegression liblinear/C=1/seed=0/max_iter=1000,
  median/standardization fit только на train, missing indicators, explicit classes.
  Контрольные claimed set groups исключаются из обучения; uncertain не negative.
- Отдельный CPU process/один admission slot. Cancel HTTP сохраняет слот до CPU;
  durable training jobs не заявляются. M2 worker queue анализа не менялась.
- Browser Web Worker кеширует последний scoring vector, threshold не входит в ключ.
  Показанное время относится только к scoring, не к полной реакции интерфейса.
- Migration `0006_label_lab`: пять используемых таблиц definitions/label events/
  rules/model metadata/model examples. Scalar features остаются колонками.
  Model weights/preprocessing — bounded JSON artifacts с hashes, отдельный Compose
  volume. No pickle/raw maps/object arrays/persistent prediction matrix.
- Добавлены NumPy/scikit-learn и lock; установлены NumPy 2.5.4/sklearn 1.9.1.
  Использована первичная [документация baseline](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).

Решение: [ADR-0010](../adr/0010-hybrid-label-workbench.md).
Контракт: [label-workbench](../architecture/label-workbench.md).

## Целевые проверки

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_lab.py --tb=short
$env:OSU_LAB_TEST_DATABASE_URL='postgresql+asyncpg://osu_lab:osu_lab_local@127.0.0.1:5432/osu_skill_lab_test'
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_lab.py tests/integration/test_migrations.py tests/integration/test_analysis_persistence.py::test_actual_schema_has_only_digest_bytes_and_configuration_json tests/integration/test_analysis_flow.py tests/unit/test_api_health.py tests/unit/test_config.py --tb=short
node --test tests/web/score-core.test.mjs
```

Unit: **7 passed (1.42 s)**. Целевой PG/HTTP/CPU/lifespan/config прогон:
**40 passed (6.92 s)**. Всего 47 уникальных Python cases, без skip; Node —
**3 passed**. Неизменённые parser/features/osz/CLI и другие независимые unit
не запускались. Python test проверил portable scoring обученной модели в Node
с допуском 1e-12; это согласованность вычисления, не метрика качества.

PostgreSQL проверяет: latest labels, concurrent conflict, compensating undo,
выбор текущего profile, immutable rules/hash identity, train на настоящем process,
lineage до точных events, отсутствие перезаписи labels, tampered artifact → 503.
Отдельно проверены отмена/удержание admission, upgrade/check/downgrade/re-upgrade,
отсутствие feature blobs и массивов во всех 12 таблицах. Unit проверяют train-only
preprocessing, same-set exclusion, uncertain/missing и model artifact I/O guards.

## Браузер

Локальный ignored `.tools/lab_browser_app.py` поднял API на 8010 с отдельной
случайной схемой `_test` БД и 24 синтетическими картами. Playwright из ignored
`.tools/browser-qa` использовал headless Google Chrome. Node не нужен продукту.
`.tools/lab_browser_qa.mjs` проверил создание тега, ручные labels, undo/control,
live weights, reuse cache при threshold, сохранение/перезагрузку rule, реальный
CPU train/model reload, фильтры, `.osu` upload и ширины 1024/768/390 px.
Последние полные прогоны — passed, page errors отсутствуют. Скриншоты просмотрены.

Первые прогоны выявили сброс checkbox во время сохранения и overflow на 390 px;
оба исправлены. Добавлена защита устаревших ответов при смене тегов/моделей.
QA-сервер остановлен; после проверки отсутствия owner PID удалена только его
схема, сопоставленная с собственным artifact-каталогом. Fake labels/models в
обычную dev БД не записывались. Это не latency benchmark на 1000 реальных карт.

## Ошибки среды и Docker

Первый `uv sync` не получил зависимости через sandbox proxy; повтор вне sandbox
успешен. Первые pytest tmp/cache и Node spawn/IPC заблокированы sandbox; целевые
повторы с разрешением прошли. Mypy сначала нашёл четыре ошибки narrowing nullable
floats; исправлены. Ruff отформатировал новые Python файлы. Frontend приведён
к читаемому виду локальным Prettier из ignored tooling, без project Node deps.

Первый `docker compose up --build --wait api dispatcher worker` успешно собрал
image, применил миграцию и поднял сервисы. После финальных UI правок повторная
сборка прошла, но Docker оставил migration-контейнер в `running` без процессов:
`docker top` пуст, exec ответил `cannot exec in a stopped state`, PG connections/
blockers отсутствовали. Контейнер явно остановлен и пересоздан:

```powershell
docker compose stop -t 5 migrate
docker compose up --no-deps --force-recreate migrate
docker compose up --wait api dispatcher worker
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

Пересозданный migrate завершился 0; API/worker/dispatcher healthy. Старый compose
wait завершился ошибкой отсутствующего заменённого container ID; новый up passed.
Контейнер API подтвердил `0006_label_lab (head)`, отсутствие schema drift,
UID 10001 и writable model directory. Credential/config dumps не выполнялись.

Локальный `.tools/check_lab_docker.py --corpus` прочитал только пользовательские
уже распакованные 33 `.osu`, передавая bytes существующему REST-анализу.
Sandbox не разрешал чтение каталогов; разрешённый запуск дошёл до одного 503
во время пересборки. Финальный повтор после восстановления Docker:
**33 × 200**, данные переиспользованы, в workbench **34 analyses**, **0 human tags**.
`/health/live`, `/health/ready`, `/lab`, JS/worker/favicon — 200. Corpus не изменён
и не удалён, metadata/features сохранены, фальшивая человеческая разметка не создана.

## Проверки качества и ограничения

`ruff check .` — passed; `ruff format --check .` — 139 files; `mypy` — 88 source
files без ошибок; `uv sync --locked --offline` — 52 packages checked.
Локальная проверка ссылок — 37 Markdown files / 205 relative links; `git diff
--check` passed (CRLF warning только у пользовательского `.gitignore`). Финальный
read-only Chrome smoke упакованного Docker UI на 34 analyses — passed, page errors
отсутствуют, human tags по-прежнему 0. Browser QA helpers/artifacts остались ignored.
В CI добавлены JS scoring tests и Docker static UI checks; удалённый запуск не
выполнялся. Зависимости и wheel/static packaging проверены реальным Docker build.

Нет реальной labeled выборки, baseline качества, calibration или доказанной
latency на большой библиотеке. Контроль для настройки не final test. Workbench
пока ограничен первыми 1000 analyses, 200 тегами и 100 versions на тег; нет
multi-annotator/auth или durable training recovery. Несколько API replicas требуют
shared artifacts и общего training budget. M3 engine/components/providers и полный
M4 остаются открытыми; следующий полезный шаг — human labels и расширенные фичи.
