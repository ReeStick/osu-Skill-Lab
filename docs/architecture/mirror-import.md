# Hinamizawa: рабочий импорт одной difficulty

Первый срез M2 реализует адаптер и законченный HTTP-сценарий загрузка → CPU-анализ →
транзакция input/result/source → чтение. Batch metadata поддержана адаптером;
долговечный сценарий M2 описан отдельно в [batch-processing](batch-processing.md).

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/imports/hinamizawa/1960574
```

`POST /imports/hinamizawa/{beatmap_id}` ждёт результат и возвращает 201 для нового
versioned анализа или 200 для переиспользованного. Опциональный query
`expected_sha256` — ровно 64 lowercase hex символа, для фиксации точных bytes.
ID — difficulty, не set. Это отдельный endpoint; будущий `POST /analysis-batches`
с ответом 202 реализован отдельно и не меняет ожидание этого endpoint.

## Получение и проверка входа

Client отправляет в metadata batch от 1 до 100 ID, удаляя повторы. Проверяет полное
разбиение ответа на results/missing/unresolved, неизвестные/повторные/пропущенные IDs.
`unresolved` остаётся retryable, а не превращается в отсутствие карты.
MD5 selectors пока не поддержаны нашим адаптером. Raw download — отдельный GET.

Импорт требует mode osu и checksum в metadata. Свежий официальный MD5, если
он уже известен из `osu_beatmap_matches` в пределах настроенного official TTL,
сравнивается с metadata зеркала до скачивания. Новый официальный запрос для
импорта не выполняется; данные зеркала не становятся официальным match.

Raw response ограничен 4 MiB. По точным bytes считаются MD5/SHA-256; MD5 должен
совпасть с metadata, SHA-256 — с query pin, если он задан. ID/set ID в parsed
файле, когда присутствуют, должны совпасть с запросом и metadata. Формат и
encoding — прежний reader contract: standard v14, UTF-8/BOM; UTF-16 отклоняется
явно, без transcoding. HTTP 200 с JSON/пустым body не принимается как карта.

## Происхождение

`beatmap_sources` хранит отдельные типизированные observations, связанные с input.
В них provider, requested ID, set ID/checksum metadata, adapter/schema versions,
время карты из metadata, время её получения и время загрузки файла. Слои источника,
freshness и ETag nullable: отсутствие header не подменяется предположением о свежести.

Ключ observation: `(input_id, provider, requested_beatmap_id, adapter_version,
metadata_schema_version)`. Повтор в этой версии обновляет observation только при
не более старом `file_fetched_at`; другая adapter/schema version остаётся отдельной
строкой. Это история версий адаптера с последним наблюдением для каждой комбинации,
не полный журнал всех HTTP-попыток. Другая редакция bytes даёт другой input.

Source и результат сохраняются одной транзакцией. Repository дополнительно
сверяет receipt с SHA-256/MD5 и file claims input; при ошибке source откатываются
новые input/result. Ни raw bytes, ни API output/enrichment/PP не сохраняются.
`beatmap.sources` возвращается в GET/list; источники страницы читаются одним
дополнительным запросом без умножения строк пагинации.

`identity_status` сохраняет прежнюю семантику: без официальной сверки `unverified`,
при ранее наблюдавшемся official checksum match — `checksum_match`. Наличие
mirror observation само по себе статус не меняет. Исходные file metadata и
claimed IDs не переписываются.

## Лимиты и lifetime

Настройки: `OSU_LAB_MIRROR_TIMEOUT_SECONDS=20` (до 30 s) и
`OSU_LAB_MIRROR_CACHE_TTL_SECONDS=600` (60–86400 s). Host фиксирован;
redirects выключены, credentials/cookies официального API не передаются.
User-Agent — `osu-skill-lab/0.1.0`. Metadata response ограничен 2 MiB.
429/503/transport failure включают cooldown, `Retry-After` поддерживает seconds/date.
После завершения M2 реальные HTTP дополнительно используют общий PostgreSQL
Hinamizawa pacing/cooldown для API и workers; cache/admission по-прежнему локальны.
Одна metadata/file HTTP-операция имеет общий timeout; pacing — 1.05 s между запросами.

Client кеширует metadata/issues до 256 ID (issues на 60 s), успех — на TTL.
Отдельно ограничивается повтор raw запроса одного ID на 60 s. Готовый результат
хранится в bounded memory cache import service без исходных bytes; повтор в этом
процессе переиспользует analysis ID. После restart cache пуст и файл может быть
загружен снова, а сохранение результата/source остаётся идемпотентным.

В HTTP import service допускаются два запроса: один выполняется, второй может
ждать; остальные получают 429. Worker использует свои N parallel slots и per-ID
gates по [runtime-workers](runtime-workers.md). Это лимиты одного процесса,
не распределённая очередь. Отмена освобождает admission slot; уже работающий
CPU-процесс удерживает свой analysis slot до завершения по существующему контракту.

Файлов на диске нет, raw bytes живут в памяти на время импорта. Если запрос/процесс
завершился до сохранения, для этого синхронного endpoint долговечного retry нет.
Jobs и shared provider budgets реализованы в [batch-processing](batch-processing.md); disk staging
заменён RAM retry с SHA pin по ADR-0007.

Ошибки metadata/файла дают структурированный `detail` с code/message/retryable:
404 missing, 409 checksum missing/mismatch, 422 unsupported mode/encoding или
parser input, 429 capacity/cooldown, 502 invalid response/body, 503 unavailable/
unresolved, 504 timeout. Ошибки CPU/БД используют существующий analysis contract.

Проверки и живой импорт: [devlog](../devlog/2026-10-25-hinamizawa-import.md).
Следующий сценарий: [batch-import](batch-import.md), решение:
[ADR-0006](../adr/0006-mirror-batch-import.md).
