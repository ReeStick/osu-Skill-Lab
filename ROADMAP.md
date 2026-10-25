# Roadmap

Этапы проходят последовательно. План не означает, что функционал реализован.

| Этап | Результат и критерий приёмки | Состояние |
| --- | --- | --- |
| 0 — Project Foundation | Установка по lock, API, реальная БД, миграции, тесты, CI, документация | Завершён 2026-10-25; CI настроен, удалённо не запускался |
| 1 — Beatmap Analysis MVP | Локальная `.osu` → проверка входа → измеряемые признаки → сохранённый результат через REST | Завершён 2026-10-25; вход временный, metadata и результаты постоянные |
| 1a — osu! API integration | Metadata/identity загруженной карты, checksum verification, OAuth, cache/rate limits | Реализовано и проверено локально; живая OAuth-проверка ожидает credentials |
| 2 — Background Processing | RabbitMQ, отдельный worker, состояния, retry, идемпотентность, версии | Не начат |
| 3 — Feature Engineering | Сначала versioned osu! difficulty engine и upstream метрики, затем собственные определения, тесты и сегменты | Не начат; контракт эволюции принят в ADR-0004 |
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
Авторизованный запрос к настоящему сайту пока не выполнен: нужны локальные credentials.
Download `.osz` в документации помечен lazer и недоступен обычному client credentials
grant. On-demand file import требует отдельного проверенного источника;
текущий законченный сценарий использует локальный upload.
Контракт: [osu-api](docs/architecture/osu-api.md).

Уточнение владельца на M1: постоянно хранятся только metadata и результаты,
исходник существует во время обработки. Для M2 потребуется определить временный
staging и очистку с учётом retry; долговечная очередь сама не хранит исходный файл.

Базой выбора метрик служит официальный difficulty/performance calculation osu!.
Состав полей и формулы могут меняться: отдельно фиксируются engine/upstream,
adapter/schema versions, mods/settings и score context. История не перезаписывается.
План до подключения первого внешнего вычислителя:
[metric-evolution](docs/architecture/metric-evolution.md),
[ADR-0004](docs/adr/0004-versioned-metric-families.md).
