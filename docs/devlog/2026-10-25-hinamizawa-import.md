# 2026-10-25 — Адаптер Hinamizawa и импорт с provenance

## Объём

Первый рабочий срез M2: batch metadata по IDs, bounded raw download одной difficulty,
CPU-анализ и атомарное сохранение provenance. HTTP endpoint ждёт результат.
Batch jobs/RabbitMQ/worker не заявляются готовыми. Контракт:
[mirror-import](../architecture/mirror-import.md).

## Исследование и реализация

Повторно прочитаны provider [metadata](https://mirror.hinamizawa.ai/docs/beatmap-info)
и [raw file](https://mirror.hinamizawa.ai/docs/osu-file) docs. Один живой metadata batch для двух
известных IDs подтвердил envelope requested/results/missing/unresolved и разделение
local source labels. Полный output/PP не переносился в код или БД; fixtures synthetic.

Добавлены HinamizawaClient, DTO metadata/issues/receipt, MirrorImportService и
`POST /imports/hinamizawa/{id}`. Import не использует OAuth credentials.
Client валидирует полный batch partition и download checksum; имя файла/redirect/
forensics URL из ответа не используются как локальные пути или новые fetch targets.

Модель `BeatmapSource`, revision `0004_sources` сгенерирована Alembic и проверена.
Source и result сохраняются одной транзакцией. Версия source adapter/schema входит
в unique key; более старый observation не перезаписывает новый. API get/list
включают source DTO, официальный match остаётся независимым.

Перед download проверяется свежий известный official checksum из БД. Его конфликт
с mirror metadata даёт 409 без скачивания и новой записи. Raw bytes не трансформируются;
UTF-16 явно unsupported. Reader и вычисления не расширялись до полного decoder.

## Проверки и исправления

При mypy проверке SQLAlchemy Row unpack вместе с keyword `sources` определялся
как возможная повторная передача параметра. Использованы явные три ORM-элемента
Row. Других падений реализации в целевых прогонах не было. Первый sandbox pytest
с 25 adapter tests прошёл, но сообщил о недоступном pytest cache; дальнейшие
прогоны с PostgreSQL/CPU выполнены вне Windows sandbox.

Основной целевой прогон: **103 passed** (9.98 s): adapter, import HTTP, изменённые
analysis service/DTO/API и PostgreSQL persistence/flow/verification/migrations.
Затем 6 целевых проверок cancellation/admission и одновременного импорта — passed;
после добавления проверки known official MD5 — 18 passed по service/import/PG;
после явного UTF-16 отказа — 43 passed по двум изменённым client/HTTP модулям.
Всего затронуто 111 уникальных test cases; это несколько целевых команд, не
полный pytest. Независимые parser/features/osz/CLI и прочие unit не запускались.

Проверены: 100-ID boundary, dedup, missing/unresolved, malformed partitions/body,
размеры, hashes, no-auth headers, cooldown/timeout/cancellation; новый result/source,
одновременные повторы без повторной загрузки, PG rollback при source constraint,
source versions/latest observation и пагинация без дубликатов.

Команды использовали `.venv`, test URL с суффиксом `_test` и isolated Alembic schemas.
Основной прогон:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_hinamizawa.py tests/unit/test_mirror_http.py tests/integration/test_mirror_import.py tests/unit/test_analysis_service.py tests/unit/test_analysis_api.py tests/integration/test_analysis_persistence.py tests/integration/test_analysis_flow.py tests/integration/test_osu_verification.py tests/integration/test_migrations.py --tb=short
```

Последний целевой прогон после UTF-16 guard:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/unit/test_hinamizawa.py tests/unit/test_mirror_http.py --tb=short
```

Финальные `ruff check .`, `ruff format --check .` и `mypy` через `.venv` — passed:
99 файлов форматирования, 61 source file. `uv sync --locked --offline` с локальными
UV cache/install directories проверил 39 packages. Новых зависимостей нет; lock
не менялся. Локальный `.tools/check_metric_docs.py` проверил 22 Markdown files и
121 относительную ссылку. `git diff --check` прошёл; Git предупредил о CRLF в
пользовательском незакоммиченном `.gitignore`, который не включён в этот срез.

## Живой сценарий

`docker compose up --build --wait api` выполнил build/migrate/start. Рабочая БД:
`0004_sources (head)`; `alembic check` — `No new upgrade operations detected`.
Локальный `.tools/check_mirror_import.py` (игнорируется Git) запросил одну карту
1960574 с SHA-256 pin ранее сохранённого input. Получен raw `.osu` **112 844 bytes**;
hash совпал. API вернул 200 и переиспользовал analysis №1, сохранив одну source
observation: provider hinamizawa, metadata layer local_duckdb, file layer local_corpus.
Freshness header отсутствовал и сохранён как null, без заявления о его значении.

Повтор import и GET — 200 с тем же результатом/observation. Features, settings,
версии, created_at, SHA-256 и прежняя официальная metadata остались прежними.
Health live/ready — 200. Массового download не было; исходные корпуса не изменялись.
После явной классификации UTF-16 актуальный image пересобран. Повторная команда
`python .tools/check_mirror_import.py` прошла: 200 import/repeat/GET, одна source
observation, `file_fetched_at=2026-10-25T20:25:14.976790Z`. Наличие нового guard
подтверждено внутри контейнера; повторные `docker compose exec -T api alembic current`
и `docker compose exec -T api alembic check` — head и отсутствие drift. Первый
`compose exec` был отклонён sandbox при доступе к Docker pipe, повтор с разрешением
выполнен успешно.

## Остаток M2

Работает импорт одной difficulty; batch metadata client уже пригоден для resolver.
Долговечные batch/items/jobs, broker/worker, ACK/retry/outbox, disk staging cleanup
и распределённый budget не реализованы. Это следующий ограниченный этап по
[критериям M2](../milestones/002-batch-background.md).
