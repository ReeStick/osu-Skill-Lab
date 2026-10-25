# Пакетный импорт карт из зеркал

Status: Accepted design; adapter/single-file import implemented, durable batch not implemented
Date: 2026-10-25

## Проверенный контракт кандидата

Пользователь предложил Hinamizawa для пакетного получения карт и как дополнительный
источник при 429 официального API. По документации провайдера:

| Возможность | Контракт |
| --- | --- |
| Batch lookup | `GET /v3/osu/beatmaps/batch`, до 100 ID/MD5 суммарно, metadata |
| Raw file | `GET /api/osu/{beatmap_id}`, одна difficulty как `.osu` |
| Map pack | Загрузка набора по pack tag; это отдельный сценарий, не произвольный список ID |

Batch response различает `missing` и `unresolved`: последнее не означает отсутствие
карты. Документирован предел 10 upstream MD5 lookups на один batch. Часть запросов
может обращаться к официальному upstream, поэтому зеркало не гарантирует успех
во время его перегрузки. Здесь проверена документация, не фактические ответы API.

## Наш batch-сценарий M2

Один запрос клиента будет создавать пакет до 100 difficulty IDs. Предлагаемый
endpoint — `POST /analysis-batches`, ответ 202 с `batch_id`; это пока проект,
его нет в текущем OpenAPI. Set IDs должны передаваться отдельным явным сценарием:
численно похожие IDs нельзя автоматически считать difficulty IDs.

```mermaid
flowchart LR
    Client[Client: list of beatmap IDs] --> Batch[Batch API]
    Batch --> Jobs[Durable batch and item jobs]
    Jobs --> Queue[RabbitMQ]
    Queue --> Worker[Worker with source budgets]
    Worker --> Metadata[Batch metadata resolution]
    Metadata --> Files[Bounded per-file downloads]
    Files --> Analysis[Versioned local analysis]
    Analysis --> Results[PostgreSQL results and per-item status]
```

Наш batch является координацией нескольких операций. Он не обещает скачать
произвольные `.osu` одним upstream response. Начальная стратегия — batch metadata,
затем отдельные raw `.osu` с ограниченной конкуренцией; медиа/`.osz` не нужны.
После принятия задания клиент сможет получить статус каждого элемента и analysis ID.
Ошибка одной карты не откатывает успешно обработанные элементы.

При реализации нужны dedup IDs внутри запроса, защита повторной постановки,
ограничение общего объёма работ и числа одновременно скачиваемых файлов.
Фиксация намерения job по ID не фиксирует исторические байты: желаемый checksum
нужно задавать явно, если требуется конкретная редакция. После скачивания
локальная identity всегда определяется SHA-256 точных байтов.

## Источники, 429 и происхождение

Downloader и metadata lookup — отдельные адаптеры с явным provider. Hinamizawa
рассматривается как самостоятельно выбранный источник raw файлов, а не как иной
адрес нашего официального OAuth client. Official ID/secret/token туда не передаются.

429 включает cooldown соответствующего provider с учётом `Retry-After`.
Бюджеты и circuit breakers источников независимы; общий лимит worker сохраняется.
Во время official cooldown разрешается работа с выбранным mirror/cache, но это
не сбрасывает официальный таймер. Если зеркало сообщает upstream pressure или
неразрешённый lookup, элемент переходит в ожидание retry; не запускается цикл
переключений, повторно нагружающий один upstream через разные адреса.

Текущий `verify-osu` сохраняет только наблюдение настоящего osu! API. Mirror metadata
нельзя записывать в `osu_beatmap_matches` как официальный match. Для первого
mirror-сценария потребуются DTO/миграция provenance: provider, requested ID,
время получения, hashes, известная свежесть и источник связи с картой. Download
source и identity verification source могут различаться. Ответ с зеркала сам
по себе не получает официальный статус `checksum_match`.

Если официальный checksum уже известен, скачанные байты проверяются против него.
При несовпадении результат для ожидаемой редакции не создаётся. Без официального
подтверждения сохраняются provider claims и явный статус происхождения; ID из
файла не превращается в доказанный внешний ключ. Разные bytes под одним ID дают
разные inputs. Внешние rosu/pp/enrichment значения автоматически не импортируются.

## Жизненный цикл и ошибки

Используется существующий reader contract и лимит `.osu` 4 MiB. Валидируются байты,
формат/ruleset, requested/file identity и допустимый checksum. Неподдержанная
версия/кодировка даёт ошибку элемента; transcoding и расширение parser не
добавляются молча. Raw bytes/hash считаются до любых преобразований.

Скачивание выполняется по мере готовности worker, а не всего пакета в RAM.
Временный staging живёт до завершения нужных retry, затем очищается. После
аварии orphan staging должен убираться по TTL. В PostgreSQL — jobs, provenance,
metadata и результаты, без raw files/objects. После удаления исходника ETag/304
не заменяют bytes: для нового расчёта нужны доступный staging либо полный GET.

При реализации проверяются: частичный batch, `unresolved`, 404/429/503, timeout,
несовпадение checksum/ID, некорректный body, повторная доставка и падение worker.
Metadata cache учитывает provider/freshness; старый или неразрешённый ответ не
объявляется подтверждённым отсутствием карты. Для зеркал задаются свой pacing,
bounded responses и User-Agent проекта. Allowlist hosts/redirect policy определяются
адаптером; запрос клиента содержит IDs, не произвольные URL.

## Источники, 2026-10-25

- [Batch metadata](https://mirror.hinamizawa.ai/docs/beatmap-info).
- [Raw .osu](https://mirror.hinamizawa.ai/docs/osu-file).
- [Packs](https://mirror.hinamizawa.ai/docs/map-packs).
- [Provider limits/caching](https://mirror.hinamizawa.ai/docs/rate-limits).
- [Official API terms](https://osu.ppy.sh/docs/).

Решение: [ADR-0006](../adr/0006-mirror-batch-import.md).
Первый срез реализован: metadata adapter, raw single-file import и `beatmap_sources`.
Контракт: [mirror-import](mirror-import.md). Durable batch endpoint/jobs/queue
ещё не реализованы; схема выше описывает целевой полный сценарий M2.
