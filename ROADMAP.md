# Roadmap

Этапы проходят последовательно. План не означает, что функционал реализован.

| Этап | Результат и критерий приёмки | Состояние |
| --- | --- | --- |
| 0 — Project Foundation | Установка по lock, API, реальная БД, миграции, тесты, CI, документация | Завершён 2026-10-25; CI настроен, удалённо не запускался |
| 1 — Beatmap Analysis MVP | Локальная `.osu` → проверка входа → измеряемые признаки → сохранённый результат через REST | Завершён 2026-10-25; вход временный, metadata и результаты постоянные |
| 1a — osu! API integration | Metadata/identity загруженной карты, checksum verification, OAuth, cache/rate limits | Завершён 2026-10-25; живая сверка и повторное чтение проверены |
| 2 — Batch Import & Background Processing | Пакет ID → mirror metadata/raw files → RabbitMQ/worker → результаты по каждому элементу; retry и временные исходники | Завершён 2026-10-26: durable jobs, retry/cancel, shared mirror budget; живой batch проверен |
| 3 — Feature Engineering | Versioned difficulty/pp components, собственные признаки, tag providers/definitions и сегменты | В работе: CPU runtime queue/worker capacity готовы; engine/tags/GPU впереди |
| 4 — Skill Classification | Размеченный набор, baseline, оценка ошибок и ограничений; ML только при достаточных данных | Не начат |
| 5 — Tournament Pool Classification | Контекст турнира, multi-label слоты, история разметки, поиск | Не начат |
| 6 — Public Release | Интерфейс, эксплуатация, мониторинг, развёртывание, публичная документация | Не начат |

Точный статус: [TASKS](TASKS.md), критерии [M0](docs/milestones/000-foundation.md)
и [M1](docs/milestones/001-analysis-mvp.md).

## Зависимости этапов

Для M1 длительный анализ должен выполняться вне HTTP event loop. До RabbitMQ
реализован ограниченный вызов в отдельном процессе с ожиданием результата
(два слота на экземпляр API). Не следует маскировать
недолговечные `BackgroundTasks` под надёжную очередь заданий.

NumPy, SciPy, rosu-pp-py, HTTPX в runtime, RabbitMQ и Redis добавляются только
под конкретные сценарии. На M0 HTTPX нужен исключительно для тестов API.
Локальные `.osu` поддержаны; M1a добавил явную checksum-сверку с metadata API v2.
Живая авторизованная сверка одной карты и переиспользование metadata проверены.
Download `.osz` в документации помечен lazer и недоступен обычному client credentials
grant. Для M2 выбран кандидат Hinamizawa: batch metadata и отдельные raw `.osu`.
Adapter и endpoint импорта одной difficulty реализованы и проверены на живом файле.
Доступны локальный upload, raw mirror import и долговечный batch через очередь.
Контракт: [osu-api](docs/architecture/osu-api.md).

Предложение владельца превращает M2 в прикладной batch-сценарий: durable items,
частичный успех и bounded загрузки вместо привязки всего пакета к HTTP-запросу.
Mirror fallback сохраняет provider provenance и официальный cooldown по 429.
Проект: [batch-import](docs/architecture/batch-import.md),
решение: [ADR-0006](docs/adr/0006-mirror-batch-import.md),
критерии: [M2](docs/milestones/002-batch-background.md).
Первый рабочий срез: [mirror-import](docs/architecture/mirror-import.md).
Полный M2: [batch-processing](docs/architecture/batch-processing.md),
доставка и RAM input на retry: [ADR-0007](docs/adr/0007-durable-batch-delivery.md).

Уточнение владельца на M1: постоянно хранятся только metadata и результаты,
исходник существует во время обработки. Для M2 потребуется определить временный
staging и очистку с учётом retry; долговечная очередь сама не хранит исходный файл.

Базой выбора метрик служит официальный difficulty/performance calculation osu!.
Состав полей и формулы могут меняться: отдельно фиксируются engine/upstream,
adapter/schema versions, mods/settings и score context. История не перезаписывается.
План до подключения первого внешнего вычислителя:
[metric-evolution](docs/architecture/metric-evolution.md),
[ADR-0004](docs/adr/0004-versioned-metric-families.md).

Уточнение M3: tags отделены от числовых measurements, их определения и методы
версионируются. Timing/slider geometry и будущие ML providers включаются в граф
зависимостей profile; GPU — опциональная capability. Ориентир обработки одной
карты — 30 s от готового input до commit, без жёсткого обрыва. Полная latency и
throughput проверяются отдельно, достигнутые показатели пока не заявляются.
Контракт: [tag-pipeline](docs/architecture/tag-pipeline.md),
[ADR-0008](docs/adr/0008-extensible-tags-and-compute-budget.md),
критерии: [M3](docs/milestones/003-feature-engineering.md).
Первый runtime срез: [runtime-workers](docs/architecture/runtime-workers.md),
одна очередь и мощность worker 1..32 по [ADR-0009](docs/adr/0009-worker-concurrency.md).
