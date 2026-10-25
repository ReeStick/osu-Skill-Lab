# 2026-10-25 — OAuth и сверка checksum с osu! API

## Цель и граница

Продолжить M1a по roadmap: связать локально загруженные inputs с metadata сайта.
Проверены актуальные API v2 docs, официальный lookup controller и routes.
Документированный archive download помечен lazer и не подходит обычному
client credentials grant. Поэтому реализован законченный metadata/identity
сценарий для уже загруженной карты; downloader и количественные attributes
не добавлялись. Границы описаны в [osu-api](../architecture/osu-api.md).

В локальном `.env` не найдены OAuth credentials. В начале работы пользователю
запрошена настройка двух значений локально, без передачи secret в chat.
Независимая реализация/локальные проверки продолжены без реальных токенов.

## Реализация

- HTTPX перенесён из dev в runtime; lock обновлён offline, версии 39 пакетов прежние.
- Optional paired Settings и Compose env для client ID/secret, timeout/TTL.
- Собственный async adapter: guest OAuth/public, selected bounded DTO, checksum-only
  lookup, lazy token, один повтор GET после 401 и общий cooldown по 429/auth errors.
- 1.05 s pacing, TTL/LRU на 256 checksum, ошибки/отмена кешируются на 60 s.
  Результат прерванного обращения не вызывает немедленный повторный опрос.
- `POST /analyses/{id}/verify-osu`, два слота, безопасные HTTP error contracts.
- Третья таблица `osu_beatmap_matches`, миграция `0003_osu_metadata`, optional
  LEFT JOIN metadata в GET/list и отдельное отображение file claims/API identity.
- Checksum проверяется до записи; upsert не позволяет старому `fetched_at`
  заменить новое. Это обновляемый metadata cache, не quantitative result history.
- ADR-0005, architecture, README/TASKS/ROADMAP и критерии M1a обновлены.

## Проблемы и исправления

Первый локальный pytest внутри Windows sandbox встретил ограничения доступа
к временным файлам. Параметр теста с большим bytes body также создал огромный
case ID и шумный вывод; параметрам присвоены короткие `ids`. Прогон повторён
вне sandbox, а не заменён проверкой без процессов/БД.

При mypy проверке тест blank Settings первоначальный `type: ignore` оказался
на другой строке после formatter. Вместо подавления типов тест проверяет
реальный путь через пустые env vars Compose.

Обнаружено при ревью: auth cooldown не должен отображаться как upstream 429.
Сохраняется причина паузы, поэтому неправильные credentials дают 503 и для другого
checksum. Для отмены запроса сохранена краткая пауза по ключу, чтобы не опрашивать
тот же ресурс сразу после неизвестного результата отменённого exchange.

## Проверки

```text
uv lock --offline
uv sync --locked --offline
ruff check .
ruff format --check .
mypy
pytest --tb=short
docker compose up --build --wait api
alembic current
alembic check
```

Итоговый pytest с `OSU_LAB_TEST_DATABASE_URL`: **259 passed**, включая 236 unit
и 23 integration с настоящим PostgreSQL, без skip (7.71 s). Промежуточный полный
прогон до тестов cancellation/cooldown: 253 passed. Ruff успешен, format —
79 файлов; mypy — 51 файл без ошибок; lock/sync — 39 пакетов, без смены версий.

Сквозной тест использует настоящие CPU-процессы upload и PostgreSQL с synthetic
HTTPX transport для OAuth/API. Он сверяет metadata, GET, повторную verify и
новый экземпляр приложения без credentials с кешем БД. Отдельно проверены
missing/wrong checksum без записи, четыре конкурентных metadata refresh,
сохранность claims/results, stale cache при timeout и отсутствие raw/JSON blobs.

Migration upgrade/check/downgrade/repeat проверены в изолированных schemas.
Docker build/start прошёл; рабочая БД — `0003_osu_metadata (head)`, check:
`No new upgrade operations detected`. Health live/ready вернули 200.

Локальный `.tools/check_osu_runtime.py` (игнорируется Git) проверил контейнер:
credentials configured=false, verify существующего анализа вернула ожидаемый
503 `osu_not_configured`; GET анализа и OpenAPI остались доступны. Ни одного
авторизованного обращения к реальному osu! API в этом срезе не выполнено.
Наличие живого match на пользовательском корпусе не заявляется.

## Состояние перед живой проверкой

После прерывания связи работа возобновлена без изменения runtime-кода.
Docker Engine оказался остановлен: HTTP и PostgreSQL сначала отклонили соединения.
`docker desktop start` и `docker compose up -d --wait api` восстановили контейнеры.
Повторная проверка: live/ready 200, `0003_osu_metadata (head)`, Alembic без drift,
`pytest -m integration --tb=short` — 23 passed, 236 deselected (6.53 s).
Ruff lint/format (83 файла), mypy (51 файл), locked offline sync успешны;
16 Markdown-документов и 84 относительные ссылки проверены локальным helper.
Credentials по-прежнему отсутствуют; disabled verify вернула ожидаемый 503.

На этом этапе M1a оставался In progress до живой проверки после локальной настройки
OAuth application. Секреты не коммитятся, `.env` не перезаписывался, пользовательская
правка `.gitignore` остаётся отдельно. Удалённый CI/push не выполнялись.

До нескольких API-процессов нужен общий request budget по OAuth application;
текущий limiter/cache локален. Metadata cache хранит последнее наблюдение,
не полную историю сайта. После M1a — M2, затем versioned difficulty/pp по ADR-0004.

## Живая OAuth-проверка и завершение M1a

Пользователь настроил env credentials и разрешил их проверку. Значения секретов
и OAuth responses не выводились. `docker compose up -d --wait api` пересоздал
API с актуальным окружением. Локальный `.tools/check_osu_live.py` выбрал анализ
без прежнего API match, поэтому успешный ответ не мог прийти из сохранённой
положительной metadata для этого input.

25.10.2026 в 21:50:29 МСК `POST /analyses/1/verify-osu` вернул 200:
получен API match с beatmap 1960574, MD5 совпал, `claimed_ids_match=true`.
Сразу проверены повторный POST и GET: оба 200, metadata и `fetched_at` прежние.
Features, difficulty settings, stack leniency, версии, configuration hash,
ID и время создания анализа совпали с исходным ответом. Health live/ready — 200.
Проверена одна карта; массового опроса корпуса не было.

Runtime-код не менялся, поэтому unit/pytest harness повторно не запускались:
проверялся только живой API-сценарий. По пожеланию пользователя правило выбора
тестов затронутых модулей/сценариев добавлено в AGENTS.md.
M1a закрыт в TASKS/ROADMAP/milestone; следующий этап — M2, ещё не начат.
