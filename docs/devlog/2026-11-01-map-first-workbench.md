# 2026-11-01 — Интерфейс вокруг карты и простой разметки

## Объём

Основа `78b5d3f`, отдельная ветка `ui/map-first-workbench`. Владелец разрешил полную
переработку после интерактивного концепта и прототипа браузерного просмотра.
Цель — полезность продукта, не демонстрация инфраструктуры. Рабочие данные,
реальные карты и существующие версии моделей не использовались в проверках.

## Реализация

- Новый `/lab`: выбранная карта, preview, теги, отдельная последовательная проверка
  одного тега. Без weights, thresholds и train/validation checkbox в ежедневной работе.
- Старый UI и функции сохранены в `/lab/research`; ссылка обратно в коллекцию.
- Backend collection с cursor и поиском по всей совместимой библиотеке, отдельно
  от нормализованного исследовательского dataset до 1000 строк.
- Parser/geometry Web Worker + canvas player, checksum matching, pause/seek/speed,
  отдельное audio; исходники только в RAM браузера, bounded File cache.
- Модули API, labels/partition, parser, player; optimistic undo и reconciliation
  после любой ошибки POST. Текстовые no/unsure различаются с неразмеченным состоянием.
- Автоматическая group partition только для новых решений; прошлые роли сохранены.
- Светлая/тёмная темы, отдельная прокрутка каталога, narrow layout, keyboard 1/2/3
  в проверке и Space для playback вне полей/кнопок.

## Проверки

- `uv sync --locked` — успешно; runtime зависимости/lock не изменялись.
- `node --test tests/web/*.test.mjs` — 12 passed: scoring, parser, labels.
- `uv run pytest tests/unit/test_lab.py tests/integration/test_lab.py -q` —
  7 passed, 5 skipped: PostgreSQL URL отсутствует. Skip не означает успешную БД-проверку.
- Финальный `uv run pytest -m "not integration" -q` — 335 passed,
  57 integration cases deselected.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` — успешно
  (88 source files в mypy на момент проверки).
- Chromium smoke `tests/web/workbench-browser.cjs` — passed, page errors `[]`:
  catalogue paging/search, tag creation, yes→unreviewed, review/skip, cross-map undo,
  409 reconciliation, mismatched checksum, parser worker, play/pause/seek, upload,
  stale labels/preview, светлая/тёмная темы, widths 1280/768/390/320 без overflow.
  API теста синтетический; серверное обучение/БД этим smoke не проверяются.
- Скриншоты в ignored `.tools/ui-qa`; visual review выявил слишком длинную страницу
  каталога — добавлены отдельная прокрутка и более компактный playfield.

Playwright browser download вернул повреждённый/пустой архив. Для локального smoke
использован Chromium 133 из временного npm `@sparticuz/chromium`, распакованный
без изменения владельцев файлов (архивный chown недоступен в среде). В репозиторий
бинарник не включён. CI устанавливает pinned Playwright 1.56.1 и штатный Chromium.
Первый browser smoke обнаружил ошибку самого fixture: все разные карты имели один
SHA, поэтому корректно переиспользовался их preview. Исправлены synthetic identities.

Docker/PostgreSQL в среде отсутствуют. Попытка установки PostgreSQL остановилась
на ограничениях смены UID/GID; сервис не запускался. Миграций нет. Docker images,
volumes и пользовательские данные не удалялись. Новая PostgreSQL проверка и browser
job включены в CI; удалённый результат будет отмечен отдельно после запуска.

## Ограничения

Preview не является игровым decoder: без stacking/ticks/hitsounds/mods. Нужен
исходный .osu и отдельно аудио; mirror reacquisition/архивы не добавлены.
ML-качество, SR/pp, старые feature profiles, публичная auth и production deployment
не входят в переработку. Подробнее: ADR-0011.

## Удалённая проверка

Первый Actions run `41294735213` завершился до запуска jobs: при добавлении browser
job замена текста также затронула вложенный service PostgreSQL. Workflow восстановлен
из исходной версии с единственной вставкой на уровне jobs; это ошибка CI-конфига,
не результат исполнения тестов. Повторная проверка выполняется в PR #1.
