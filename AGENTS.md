# Инструкции для работы над osu! Skill Lab

## Сначала восстановить контекст

Прочитайте этот файл, `TASKS.md`, `ROADMAP.md`, релевантные документы в
`docs/architecture/`, ADR и последнюю запись devlog. Проверьте `git status` и
последние коммиты. Не перезаписывайте чужую незавершённую работу.

## Назначение и ограничения

Сервис анализирует osu!standard. Разделяйте измеряемые признаки, эвристический
skill profile и контекстные турнирные слоты; difficulty и PP — отдельные величины.
Текущий объём определяется `TASKS.md`. Не переходите к следующему milestone,
пока не выполнены критерии текущего или владелец явно не изменил объём.

Модульный монолит, `src/osu_skill_lab`. HTTP — в `api/`, внешние адаптеры —
в `infrastructure/`. Добавляйте `domain/`, `application/`, `analysis/`, `workers/`
по мере появления работающего кода. Алгоритмы не зависят от FastAPI и ORM.
Длительные CPU-расчёты не выполняются в event loop HTTP. Версионируйте
алгоритмы, параметры и входные данные; не выдавайте эвристики за измерения.

Reader `.osu` целевой: metadata/settings, timing points и hit objects.
Медиа, storyboard и hitsounds не входят в его назначение. Не расширяйте его
до полного игрового decoder без отдельного сценария. Сырой input и effective
gameplay values различаются; контракт в `docs/architecture/osu-parser.md`.

Входные байты и массивы объектов нужны только на время расчёта. HTTP сейчас
обрабатывает `.osu` в RAM, без файлов; в PostgreSQL сохраняются fingerprint
входа, ограниченная metadata и versioned scalar results. Не добавляйте
постоянное хранение исходников/объектов без нового сценария. Малый JSONB —
только конфигурация; признаки — типизированные столбцы. IDs файла считаются
непроверенными claims до сверки с внешним источником. См. ADR-0003 и database.md.
Локальный исследовательский корпус `tests/unlabeled_osu_maps` и результаты
offline extraction принадлежат пользователю; сервис не должен удалять их
как свои временные upload-файлы.

При выборе метрик сначала сверяйтесь с официальным difficulty/performance code
и релизами osu!, затем с поддерживаемой ревизией выбранного port/binding.
Difficulty, score-dependent pp и будущие собственные признаки имеют отдельные
контракты. Версия wrapper не заменяет engine/upstream revision; обновление
вычислителя не перезаписывает старые результаты. План семейства/adapter/schema
versions и расширения столбцов — `docs/architecture/metric-evolution.md`, ADR-0004.
Этот контракт пока проектный: перед первым внешним расчётом реализуйте его
provenance/identity в коде и миграции, не назначайте выдуманные версии API-данным.

M3 учитывает отдельный каталог versioned tag definitions/bundles и assignments:
новый тег не требует столбца, новые числовые признаки остаются типизированными.
Rule/model outputs не смешиваются с measurements/skill profile/турнирными слотами.
Архитектурный ориентир — 30 s processing wall time от готового input до commit,
мягкий, не hard timeout; queue/acquisition и полная latency измеряются отдельно.
GPU — будущая capability отдельных stages после профилирования, не обязательная
зависимость CPU-сервиса. Контракт пока проектный: `docs/architecture/tag-pipeline.md`,
ADR-0008. Не создавать пустой framework/DDL или объявлять ML/GPU работающими заранее.
Первый runtime срез использует общую очередь M2 и configurable CPU worker:
`OSU_LAB_WORKER_CONCURRENCY=1..32` (default 1), CLI `worker --concurrency N`.
Capacity согласована с prefetch/import/CPU slots; provider budget остаётся общим.
Engine/tag/GPU ещё не подключены. См. `docs/architecture/runtime-workers.md`, ADR-0009.

osu! API сверка явная: `POST /analyses/{id}/verify-osu`. Lookup отправляет только
checksum; file IDs не являются fallback. Выбранная metadata хранится отдельно
в `osu_beatmap_matches`, статус `checksum_match` означает наблюдение MD5 на
`fetched_at`, не гарантию текущей редакции. Claims и features не обновляются.
`OSU_LAB_OSU_CLIENT_ID/SECRET` опциональны вместе; не печатайте credentials,
OAuth responses или `docker compose config` с секретами. Нет eager OAuth на старте.
Лимиты official HTTP/cache действуют на один процесс: перед масштабированием
verify-osu нужен общий бюджет запросов. Hinamizawa использует общий PostgreSQL
pacing/cooldown для API/workers. Контракт: `docs/architecture/osu-api.md`.

Первый прикладной сценарий M2 — batch import через явно выбранные sources.
Проект: `docs/architecture/batch-import.md`, ADR-0006. Mirror metadata/download
не подменяют официальный `verify-osu`; бюджеты/cooldowns источников отдельные.
Первый срез уже работает: `POST /imports/hinamizawa/{id}`, один HTTP import с
ожиданием результата, source observations в `beatmap_sources`.
Batch уже работает: POST/GET `/analysis-batches`, Idempotency-Key UUID, per-item
states/cancel, PostgreSQL outbox/leases, RabbitMQ dispatcher и worker. Raw bytes
только RAM; retry повторяет GET с observed SHA-256 pin. Disk staging не создаётся.
Контракты: `docs/architecture/batch-processing.md`, ADR-0007. Автоматического
official→mirror fallback нет; sources по-прежнему выбираются явно.

## Команды из корня

```text
uv sync --locked
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked uvicorn osu_skill_lab.main:create_app --factory --reload
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
uv run --locked osu-skill-lab extract-osz tests/unlabeled_osu_maps
uv run --locked osu-skill-lab inspect-osu data/unpacked_osu_maps --recursive
docker compose up --build --wait api dispatcher worker
```

Сначала скопируйте `.env.example` в `.env`, если файла ещё нет. Не затирайте
существующий `.env`. Интеграционные тесты требуют переменную процесса
`OSU_LAB_TEST_DATABASE_URL`, БД с суффиксом `_test`, права создания схем;
инструкция в README. Без переменной они skip, это не проверка PostgreSQL.
RabbitMQ delivery tests дополнительно требуют `OSU_LAB_TEST_RABBITMQ_URL`;
без неё соответствующие проверки skip, это не проверка broker.

В исходной среде Windows `git.exe` доступен по
`C:\Program Files\Git\cmd\git.exe`, но отсутствовал в PATH. Вспомогательный uv
установлен в `.tools/Scripts/uv.exe`; `.tools` игнорируется и не является частью сборки.
При использовании этого uv задавайте `UV_CACHE_DIR=.tools/uv-cache` и
`UV_PYTHON_INSTALL_DIR=.tools/python` (абсолютные пути относительно корня).
Проверьте актуальность этих сведений: среда может измениться.

## Дисциплина изменений

- Выполняйте небольшой законченный объём, объясняйте существенные компромиссы.
- Пишите осмысленные тесты поведения; для БД используйте PostgreSQL.
- В локальных проверках запускайте тесты затронутых модулей и сценариев.
  Не повторяйте независимые неизменённые unit-тесты при настройке `.env`
  или изменениях документации. Полный прогон нужен при обоснованных сквозных
  изменениях или в CI; живую проверку интеграции проводите целевым сценарием.
- Миграции — Alembic, транзакции завершаются явно в use case; не добавляйте
  `create_all()` на старте и не выполняйте автоматический commit в зависимости HTTP.
- Обновляйте `uv.lock` при изменении зависимостей; проверяйте `uv sync --locked`.
- После существенного этапа обязательны devlog, `TASKS.md`, при необходимости
  CHANGELOG, milestone и ADR. Пишите реальные команды и результаты, включая
  ошибки и недоступные проверки. Никогда не выдумывайте успешные проверки,
  эксперименты, метрики качества или подтверждённые гипотезы.
- Devlog описывает процесс, CHANGELOG — возможности продукта. Исследования
  оформляются в `docs/experiments/` с baseline, данными и ограничениями.
- Секреты, токены, реальные загруженные карты и персональные данные не коммитить.
  Синтетические небольшие fixtures допустимы. Не доверять входным путям и именам.
- Делайте небольшие осмысленные локальные коммиты. Push и публикация требуют
  разрешения пользователя. Не меняйте Git identity без согласования.
