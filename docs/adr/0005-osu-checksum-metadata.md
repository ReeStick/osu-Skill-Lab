# ADR-0005: Явная сверка checksum и отдельный кеш metadata osu!

Status: Accepted
Date: 2026-10-25

Decision 6 superseded by [ADR-0006](0006-mirror-batch-import.md): mirror допускается
как самостоятельный источник для M2; остальные решения M1a сохраняют силу.

## Context

После M1 имеются точные input digests и непроверенные IDs файла. M1a должен
связать их с metadata сайта, не сохраняя исходники и не смешивая metadata
с versioned difficulty/performance из ADR-0004. Client credentials допускает
public metadata lookup; download `.osz` в документации помечен как lazer route.

## Decision

1. Добавить явный `POST /analyses/{id}/verify-osu` для существующего анализа.
   Raw upload остаётся независимым от сети. Lookup отправляет только MD5 checksum;
   IDs/filename не используются как альтернативный ключ при несовпадении редакции.
2. Сохранять выбранную metadata в `osu_beatmap_matches`, FK/PK по input_id.
   Claims и значения результата остаются прежними. API возвращает отдельную
   `osu` metadata, статус `checksum_match` и nullable сравнение claimed IDs.
3. Принимать связь только при точном совпадении checksum с сохранённым input;
   отсутствие/другой digest — ошибка без DB-записи. SHA-256 остаётся локальным ключом.
   MD5-ассоциация не объявляется криптографическим доказательством identity.
4. Таблица — обновляемый metadata cache с временем наблюдения и versioned DTO,
   не история измерений. При refresh более старый ответ не заменяет новый.
   Старое наблюдение сохраняется при ошибке внешнего API и видимо со своим временем.
5. Optional client ID/secret через Settings; client-credentials/public token только
   в RAM. Ограничить HTTP time/body, повторить GET после 401 максимум один раз,
   кешировать ответы/ошибки, соблюдать pacing и upstream cooldown. Внешние bodies
   и exception details не раскрывать. Лимиты пока действуют на один API-процесс.
6. Не реализовывать архивный downloader через неподходящий grant или mirror.
   Текущий вход — локальный `.osu`; получение других источников исследуется отдельно.

[ADR-0003](0003-transient-inputs-compact-results.md) сохраняет lifecycle исходника;
[ADR-0004](0004-versioned-metric-families.md) остаётся требованием для будущих
количественных API attributes/локальных difficulty и pp engines.
Полный контракт: [osu-api](../architecture/osu-api.md).

## Alternatives

- Внешний запрос на каждом upload/GET: связывает offline сценарий с OAuth и сетью,
  повторно опрашивает сайт и ухудшает доступность сохранённых результатов.
- Доверять ID файла или fallback по ID: может связать изменённый файл с иной редакцией.
- Полный JSON API: сохраняет лишние данные и не определяет их типы/происхождение.
- Дедупликация по MD5: меняет ключ точных байтов и не нужна для metadata lookup.
- Немедленно вводить универсальные snapshots/jobs/difficulty tables: нет работающего
  сценария этих данных; компактный текущий cache решает другую задачу.

## Consequences

Третья компактная таблица и outer join к metadata при чтении анализа. Кеш можно
использовать без credentials до TTL; отсутствие OAuth не мешает raw анализу/health.
Metadata snapshot здесь хранится только последний: полноценный audit изменений
сайта потребует отдельного сценария. Новая версия API DTO не является pp revision.

Живая проверка требует зарегистрированного OAuth application и локальных секретов;
MockTransport/real PostgreSQL не заменяют её. Доступность/редакция сайта не гарантируются.

## Revisit conditions

Несколько API-процессов с одним client ID, необходимость истории metadata,
разрешённый on-demand file source, quantitative difficulty attributes либо M2.
Для общего бюджета запросов потребуется распределённый limiter/координатор.
