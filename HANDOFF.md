# Продолжение osu! Skill Lab в новом чате

Снимок контекста: 2026-10-26. Рабочая папка `H:\Desktop\osu-Skill-Lab`, Windows/PowerShell.
Это навигация для следующего чата; актуальные код, Git status, AGENTS/TASKS важнее снимка.

## Ближайший запрос владельца

Владелец переносит обсуждение из-за большого контекста и **хочет сначала дать
замечания к интерфейсу**. Восстановить контекст и работать по этим замечаниям.
Если комментарии ещё не приложены, коротко сообщить готовность их обсудить.
Самостоятельно начинать следующий срез difficulty engine вместо обсуждения UI
сейчас не требуется. Детали замечаний пока неизвестны: не выдумывать их.

## Что уже завершено

- M0/M1/M1a/M2 завершены: reader osu!standard v14, 22 raw scalar features,
  PostgreSQL, явная official checksum verification, mirror import и durable batch.
- M3: общая RabbitMQ queue, отдельные CPU workers с concurrency 1..32, bounded
  prefetch/import/CPU capacity. SR/pp engine, расширенные geometry/timing providers,
  автоматический tag pipeline и GPU пока не подключены.
- По явному согласию владельца раньше завершения M3 реализован ранний M4:
  гибридный интерфейс ручной разметки, настройки правила и logistic baseline.
  **Полный M3 и M4 не закрыты.**
- Коммит реализации: `6c18723 feat: add hybrid labeling workbench and logistic baseline`.
  Предыдущий: `0c85098 feat: run bounded concurrent map jobs per worker`.
  Последующие docs-коммиты передачи смотреть в `git log`.
- При восстановлении этого снимка единственная незакоммиченная правка —
  **пользовательские три строки `.gitignore`**. Оставить их отдельно; не откатывать
  и не включать в свои коммиты. Снова проверить status перед изменениями.

## Работающий интерфейс

Адрес локального Docker API: **http://localhost:8000/lab**; OpenAPI — `/docs`.
В конце реализации Docker API/dispatcher/worker были healthy, migration
`0006_label_lab (head)`, `alembic check` без drift. Наличие запущенных сервисов
в новом чате проверяется отдельно; это не обещание их текущего состояния.

- Каталог immutable тегов: имя, критерий положительного примера, whole-map NM.
- Ручные `yes/no/unsure`, неразмеченные отдельно; клавиши 1/2/3, ↑/↓, одно undo.
  Сохраняется append-only история с optimistic event ID; прогнозы — отдельные данные.
- Контрольная выборка, исключение связанных claimed set groups из train.
  Контроль служит настройке, не независимому final test.
- Вторая вкладка: weights/bias/threshold, histogram, поиск/фильтры/сортировка,
  сохранение и загрузка immutable версий правила/порога модели.
- Preview Web Worker по уже рассчитанным features в RAM. Порог переиспользует
  scoring cache; slider debounce 35 ms. «Скоринг … ms» не измеряет полный UI render.
- Logistic baseline `binary-logistic/1`: liblinear, C=1, max_iter=1000, seed=0;
  median/standardization fit только на train, missing indicators. Нужно минимум
  два yes и два no вне контрольных сетов. Unsure/unreviewed не negative examples.
- Обучение в отдельном CPU process, один admission slot на API process. HTTP ждёт
  результат; это не durable training queue. Cancel удерживает слот до конца CPU.
- Upload `.osu` через прежний REST-анализ (до 100 файлов последовательно, 4 MiB каждый).

Текущие ограничения: первые 1000 совместимых analyses, до 200 тегов и 100 версий
на тег; нет полного проигрывания/медиа, SR/pp или оценки качества на реальной разметке.
Model score не объявляется калиброванной вероятностью. Интерактивность на большой
библиотеке не измерена; 100–200 ms — ориентир, не установленная характеристика.

В конце реализации в dev БД было **34 analyses**, включая все 33 локальные карты,
и **0 human tags**. Пользователь мог уже добавить собственную разметку после этого:
сохранить её. QA labels/models создавались только в отдельных test-схемах.

## Где менять UI и backend

Frontend — обычные HTML/CSS/ES modules, без сборки и runtime Node, отдаётся FastAPI
из Python wheel. Имеющийся стек подходит для следующих правок интерфейса.

| Файлы | Назначение |
| --- | --- |
| `src/osu_skill_lab/web/index.html`, `lab.css` | Разметка, тексты, адаптивные стили |
| `src/osu_skill_lab/web/lab.js` | Состояние UI, API, labels/rules/models, event handlers |
| `src/osu_skill_lab/web/preview-worker.js`, `score-core.js` | Cache и portable scoring/контрольные метрики |
| `src/osu_skill_lab/api/lab.py`, `main.py` | `/lab`, `/lab/api/*`, assets и сборка приложения |
| `application/lab_contracts.py`, `application/lab_service.py` внутри пакета | DTO, version identity, use cases/транзакции/admission |
| `analysis/label_baseline.py` внутри пакета | CPU training без ORM/FastAPI |
| `infrastructure/lab_models.py`, `lab_repository.py`, `model_artifacts.py` внутри пакета | Таблицы, latest labels, version metadata и artifacts |

Migration `0006_label_lab`: `lab_tags`, `lab_label_events`, `lab_rules`,
`lab_models`, `lab_model_examples`; вместе с прежними — 12 предметных таблиц.
Features по-прежнему типизированные столбцы; JSONB rule recipe ограничен 8192 bytes.
Малые неисполняемые JSON artifacts моделей (до 64 KiB) хранятся отдельно с SHA-256:
`OSU_LAB_MODEL_ARTIFACT_DIRECTORY`, default `data/model_artifacts`; в Compose —
volume `model_artifacts`. Backup БД и artifacts согласованный. Исходников карт там нет.

## Неизменные требования владельца

- Только osu!standard; целевой reader settings/metadata/timing/hit objects,
  без расширения до decoder медиа/storyboard/hitsounds.
- `.osu` bytes и object arrays временные, в RAM. Постоянно — fingerprints,
  bounded metadata и versioned scalar results. Малый JSONB только для конфигурации.
- `tests/unlabeled_osu_maps` и `data/unpacked_osu_maps` — пользовательский корпус;
  не удалять, не коммитить и не считать сервисным temp storage.
- File IDs — claims; official lookup только checksum и явный `verify-osu`.
  Mirror observations не подменяют official verification. Автоматический fallback
  official → mirror не реализован; текущие sources выбираются явно.
- Следующие difficulty/performance metrics сверять с official osu! code/releases:
  нужны total и компоненты stars/pp, отдельные difficulty и score contexts,
  точная engine/upstream identity и сохранение старых revisions.
- Расширяемые теги и ML/geometry позже: новый тег не требует нового столбца,
  новые measured features — typed family migration. 30 s обработки карты — мягкий
  архитектурный ориентир, GPU после профилирования.
- Целевые тесты затронутых сценариев; независимые неизменённые unit повторять
  не нужно. При docs-only передаче unit не запускались.
- `.env` уже настроен и содержит реальные credentials: не печатать его,
  OAuth responses, tokens или `docker compose config`; не затирать.
- Локальные осмысленные коммиты разрешены AGENTS. Push/публикация требуют отдельного
  разрешения. Git identity не менять. Новая UI обратная связь важнее прежнего плана.

## Проверки, уже выполненные для 6c18723

- 7 cases `tests/unit/test_lab.py`; 40 cases целевого PG/HTTP/lifespan/config прогона.
  Точные команды в devlog. Это 47 уникальных Python cases, не полный pytest.
- `node --test tests/web/score-core.test.mjs`: 3 passed; Python → Node parity
  обученного artifact с допуском 1e-12. Это согласованность вычисления, не качество ML.
- PostgreSQL: optimistic conflict/undo, versions/profile, real process training,
  lineage, cancel admission, повреждение artifact → 503, migration up/check/down/up.
- Chrome/Playwright: полный UI сценарий на синтетической test-БД и responsive
  1024/768/390 px; отдельный read-only smoke Docker UI на 34 реальных analyses.
  Page errors отсутствовали. QA server 8010 остановлен, его схема удалена.
- Ruff lint/format, mypy, locked/offline uv sync, Docker wheel/assets/migration,
  non-root writable model volume. CI обновлён, удалённо не запускался.

Windows: Python/ruff/mypy в `.venv/Scripts`; uv в `.tools/Scripts/uv.exe` с
`UV_CACHE_DIR=.tools/uv-cache`, `UV_PYTHON_INSTALL_DIR=.tools/python` (абсолютные пути).
Git: `C:\Program Files\Git\cmd\git.exe`. Chrome:
`C:\Program Files\Google\Chrome\Application\chrome.exe`.
Ignored `.tools/browser-qa` содержит Playwright/Prettier; `.tools/lab_browser_app.py`
и `lab_browser_qa.mjs` — локальные вспомогательные QA скрипты. Старые cleanup helpers
привязаны к прошлому запуску: проверять владение PID/schema перед любым повтором.
Docker/temp/spawn/IPC иногда требуют sandbox escalation; прошлые сбои описаны
в devlog. Один Docker migrate однажды остался running без процесса: пересоздание
только migrate восстановило запуск; не применять этот workaround без диагностики.

## Минимальные документы для следующего чата

1. [AGENTS](AGENTS.md), [TASKS](TASKS.md), [ROADMAP](ROADMAP.md).
2. [Контракт workbench](docs/architecture/label-workbench.md),
   [ADR-0010](docs/adr/0010-hybrid-label-workbench.md),
   [devlog реализации](docs/devlog/2026-10-26-label-workbench.md).
3. Для затронутого хранилища/метрик — [database](docs/architecture/database.md),
   [metric evolution](docs/architecture/metric-evolution.md),
   [tag pipeline](docs/architecture/tag-pipeline.md).
