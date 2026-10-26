# 2026-10-26 — UI по обратной связи владельца

## Объём

Восстановлены AGENTS/HANDOFF/TASKS/ROADMAP, контракт workbench, ADR-0010 и devlog.
HEAD до изменений — `f628efe`; реализация workbench — `6c18723`.
Пользовательские три строки `.gitignore` оставлены отдельно. Владелец попросил
изменить UI до продолжения roadmap и отдельно подтвердил: настоящий SR подключать
следующим срезом, сейчас показывать `★ —`. Для локального osu! запрошено только
рассмотреть подход, без реализации запуска клиента.

## Реализация

- Выбор difficulty справа: карточки с активным состоянием, поиск/фильтры, клавиатура.
  На узком экране библиотека ниже рабочей области. Состояние карты общее двум видам.
- Отдельная «Аналитика»: score, распределение оценок, шесть наибольших локальных
  вкладов метрик со знаком, мини-гистограммы измерений и marker текущей карты.
  Вклады — слагаемые до sigmoid, не проценты важности; base и скрытые члены
  объяснены. Missing imputation/indicator не выданы за реальные наблюдения.
- Настройки и обучение свёрнуты; при загрузке выбирается последняя совместимая
  сохранённая версия правила/порога, при её отсутствии — модель с проверкой profile.
  Обучение по-прежнему явное, его CPU/admission/lineage контракт не менялся.
- «Разметка»: несколько тегов одной карте через click/drag-and-drop; явные no/unsure,
  control по выбранному тегу, снятие → unreviewed. Прогнозы и их сортировки скрыты.
- Read-only GET `/lab/api/analyses/{id}/labels` читает latest event каждого тега
  input. Записи используют прежние append-only events/optimistic guard. Undo
  привязан к собственному event ID; кеш и устаревшие ответы отделены по карте/generation.
- Светлая и тёмная темы с приглушённым зелёным акцентом и localStorage preference.
  Нет новых runtime зависимостей, миграций, API difficulty/pp или сохраняемых predictions.
- [Client handoff](../architecture/client-handoff.md) фиксирует ограничения
  документированных osu:// ссылок и гипотезу локального helper. Клиент не запускался,
  доступ к Songs и исходникам не добавлялся.

## Целевые проверки

```powershell
node --test tests/web/score-core.test.mjs
$env:OSU_LAB_TEST_DATABASE_URL='postgresql+asyncpg://osu_lab:osu_lab_local@127.0.0.1:5432/osu_skill_lab_test'
& .\.venv\Scripts\python.exe -m pytest tests/integration/test_lab.py --tb=short
& .\.venv\Scripts\ruff.exe check src/osu_skill_lab/api/lab.py src/osu_skill_lab/application/lab_service.py src/osu_skill_lab/infrastructure/lab_repository.py tests/integration/test_lab.py
& .\.venv\Scripts\ruff.exe format --check src/osu_skill_lab/api/lab.py src/osu_skill_lab/application/lab_service.py src/osu_skill_lab/infrastructure/lab_repository.py tests/integration/test_lab.py
& .\.venv\Scripts\mypy.exe src/osu_skill_lab/api/lab.py src/osu_skill_lab/application/lab_service.py src/osu_skill_lab/infrastructure/lab_repository.py
```

**5 Node tests passed**: прежний scoring/missing/control и новые проверки signed
contributions с восстановлением ручного/model score, imputation и missing indicators.
**4 PostgreSQL integration tests passed (7.85 s)** без skip: два независимых тега,
latest/revert/неизменность истории, 404/422, прежний полный train/lineage flow,
optimistic conflict/undo и cancellation admission. Ruff lint/format — passed;
mypy — 3 затронутых source files без ошибок. Независимые unit, broker delivery и
полный pytest не повторялись; провайдеры/DDL/очередь не менялись.

Первые Node/Chrome spawn и pytest temp/CPU IPC были запрещены sandbox; разрешённые
повторы прошли. Ruff исправил import formatting. Первый Chrome-прогон обнаружил
гонку отложенного preview: смена тега могла передать null specification в Worker.
Таймер отменяется, параметры отправляются снимком. Дополнительный сценарий нашёл
потерю клавиатурного фокуса после асинхронной перерисовки — фокус сохраняется.
Один промежуточный QA script получил timeout при выборе модели у тега без модели;
исправлена последовательность выбора тега в самом script.

## Chrome на изолированных данных

Ignored `.tools/lab_browser_app.py` и `.tools/run_lab_ui_qa.py` поднимают порт 8010
с собственной случайной схемой `_test` БД и 24 synthetic maps. Headless Chrome
запускается через Playwright из `.tools/browser-qa`; зависимости продукта не менялись.

```powershell
& .\.venv\Scripts\python.exe .tools/run_lab_ui_qa.py
node .tools/lab_ui_redesign_qa.mjs
node .tools/lab_ui_reload_qa.mjs
```

Основной финальный сценарий — passed, page errors `[]`: библиотека справа,
свёрнутые controls, drag и click нескольких тегов, снятие → unreviewed, cross-tag undo,
map cache, yes/no/unsure/control, signed contributions и histograms, threshold cache,
версии, реальный CPU train, model reload, обе темы, upload, responsive **1024/768/390**
для обоих видов. Отдельный финальный read-only сценарий после auto-restore — passed,
page errors `[]`: восстановление модели/порога и manual version, refresh, фокус,
отсутствие записей от label hotkeys в аналитике, гонка preview при смене тега.
Скриншоты светлой/тёмной тем и mobile просмотрены. Это не latency/ML-quality benchmark.

Первый QA процесс 20076 завершён; его единственная схема
`test_lab_browser_ad8da45b4fce49c1ba36ddd9c7351ef3` удалена после проверки отсутствия
PID и собственного artifact directory. Второй QA server завершился штатно с cleanup.

## Docker и рабочие данные

Перед обновлением API read-only снимок подтвердил **34 inputs/analyses, 1 human tag,
6 label events, 1 rule, 1 model**. Для этих шести таблиц сняты fingerprints строк.
Реальные карты, label events и artifacts не использовались как QA fixtures.

```powershell
docker compose up -d --build --no-deps --wait api
```

Первая сборка не завершилась: uv install сообщил invalid RECORD / I/O error,
затем BuildKit — `write /var/lib/docker/buildkit/metadata_v2.db: input/output error`.
После этого Docker Desktop перестал отвечать, прежний API /health/ready дал timeout.
Read-only диагностика: диски доступны, свободно около 3.46 GB на C:, 141.86 GB на E:,
198.22 GB на H:. Это не устанавливает причину сбоя виртуального Docker disk.
Очистка images/cache/volumes и удаление пользовательских данных не выполнялись.
Для восстановления вызван штатный `docker desktop restart --detach`.

Штатный restart завис. `wsl --list --verbose` показал остановленный docker-desktop;
его `/bin/true` запустился (с предупреждениями о старых D: PATH entries). Завершены
только процессы с проверенными путями Docker Desktop/backend, Desktop запущен
через `Start-Process ... -WindowStyle Hidden`. Другие WSL-дистрибутивы не завершались,
reset/prune/fsck не выполнялись. После этого Docker снова ответил.

```powershell
docker compose up -d --wait db rabbitmq
docker compose up -d --no-build --no-deps --wait api
```

PostgreSQL/RabbitMQ healthy, прежний API восстановлен. Counts и fingerprints
всех шести проверенных таблиц **полностью совпали** со снимком до сбоя. Ещё две
попытки обычной сборки закончились TLS handshake timeout registry: сначала ghcr.io,
затем registry-1.docker.io. Это внешняя недоступная проверка, не успешная сборка wheel image.
Последний build log — ignored `.tools/ui-docker-build.log`.

Для локального просмотра применён ignored `.tools/ui-dev.compose.yaml`: read-only
mount `./src:/workspace/src:ro` и `PYTHONPATH=/workspace/src` только для API.
Существующие image dependencies, configuration и общий volume model artifacts сохранены;
Dockerfile/Compose продукта не изменялись. Воспроизведение текущего режима:

```powershell
docker compose -f compose.yaml -f .tools/ui-dev.compose.yaml up -d --no-build --no-deps --force-recreate --wait api
node .tools/lab_ui_docker_smoke.mjs
```

API healthy, `osu_skill_lab.api.lab.__file__` — `/workspace/src/osu_skill_lab/api/lab.py`.
DB/RabbitMQ healthy, dispatcher/worker running. Финальный read-only Chrome smoke
**passed**, **34 analyses / 1 tag / 0 backend writes / page errors []**: обновлённые
оба вида/темы, пользовательская сохранённая модель/порог и mobile layout. Сценарий
блокировал все non-GET/HEAD backend requests. Финальные fingerprints после smoke
снова полностью совпали; пользовательская разметка/правило/модель сохранены.
При доступном registry обычная успешная сборка вернёт стандартный image mode.

Последний QA процесс 14684 был остановлен до восстановления Docker; graceful
shutdown не смог удалить схему из-за недоступности PostgreSQL и завершился с
TimeoutError. После проверки отсутствия owner PID и собственного artifact directory
удалена только его схема `test_lab_browser_10da128b94734db6807c107ba4ea8527` в `_test` БД.
Реальная рабочая БД при QA cleanup не использовалась; QA server 8010 остановлен.

Финальные Ruff/format и Prettier check затронутых файлов — passed; `git diff --check`
без пользовательского `.gitignore` — passed. Проверены 77 относительных ссылок в
7 затронутых Markdown файлах. Push/публикация не выполнялись. M3 и полный M4 остаются
открытыми; настоящего SR, оценки ML-качества и интеграции editor здесь не добавлено.
