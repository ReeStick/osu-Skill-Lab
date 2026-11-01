# Тестовые данные

Unit-тесты создают маленькие синтетические `.osz` в `tmp_path`. Для них не нужны
загрузки, реальные карты или доступ к osu! API. Интеграционные тесты БД описаны
в корневом README и не используют локальный корпус.

`unlabeled_osu_maps/` — необязательный, игнорируемый Git каталог реальных `.osz`,
предоставленных владельцем для ручных проверок. Это не размеченный датасет:
из него нельзя делать выводы о качестве skill/slot classification. Карты, аудио,
изображения и manifests не включаются в коммиты.

```powershell
uv run --locked osu-skill-lab extract-osz tests/unlabeled_osu_maps
```

Извлечённые `.osu` и manifests находятся в игнорируемом `data/unpacked_osu_maps/`.
Контракт и ограничения: [local-import](../docs/architecture/local-import.md).

`fixtures/analytic-v14.osu` — созданный в проекте синтетический пример с circles,
slider и spinner, tempo/SV points и ссылками на несуществующие медиа. Реальные
assets не нужны; ignored поля намеренно могут содержать неигровые значения.
Тестируется аналитический reader, не полная валидация client-формата.

```powershell
uv run --locked osu-skill-lab inspect-osu tests/fixtures/analytic-v14.osu
uv run --locked osu-skill-lab inspect-osu data/unpacked_osu_maps --recursive
```

Сводки реальных карт остаются в `data/`; CI запускает только синтетические случаи.

Workbench: `tests/unit/test_lab.py`, `tests/integration/test_lab.py`,
`node --test tests/web/score-core.test.mjs` (Node 22+ только для разработки/CI).
Python/JS parity test использует Node при наличии; без Node он skip.
PostgreSQL tests проверяют labels/optimistic conflict, версии, настоящий CPU train,
model lineage и повреждённый artifact; синтетические labels не записываются в dev БД.

Новый основной экран:

```sh
node --test tests/web/*.test.mjs
# Только dev/CI; Node не нужен запущенному приложению.
npm install --prefix .tools/browser --no-audit --no-fund playwright@1.56.1
node .tools/browser/node_modules/playwright/cli.js install chromium
NODE_PATH="$PWD/.tools/browser/node_modules" node tests/web/workbench-browser.cjs
```

Browser smoke использует настоящий Chromium, статические assets приложения,
настоящий parser Web Worker и **синтетический HTTP API**, без пользовательских
данных. Это проверка UI, не замена PostgreSQL integration. Проверяются разметка,
конфликты, undo, импорт/preview checksum, перемотка, поиск/пагинация, смена карты,
темы и ширины 1280/768/390/320. Скриншоты опционально:
`OSU_LAB_SCREENSHOT_DIR=.tools/ui-qa`. Для имеющегося Chromium можно задать
`OSU_LAB_BROWSER_EXECUTABLE`. В CI браузерная проверка — отдельная job.

`test_collection_paginates_searches_and_preserves_research_endpoint` в
`integration/test_lab.py` требует настоящую PostgreSQL `_test` БД и проверяет
cursor/search (включая буквальные `%`/`_`), совместимость профиля и старый API.
