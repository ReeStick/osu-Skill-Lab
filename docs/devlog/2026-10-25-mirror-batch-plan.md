# 2026-10-25 — План batch import через зеркала

## Предложение и проверка

Владелец предложил batch-загрузку для анализа и mirror как дополнительный source
при official API 429, указав Hinamizawa. Просмотрены metadata, raw file, archive
download, map-pack и rate-limit разделы документации провайдера, а также official
API terms. Никакие карты или готовые PP-значения в этом срезе не скачивались.

Документация подтверждает batch metadata lookup, но не произвольный batch raw
file response. Для анализа подходит отдельный `.osu` endpoint вместо архива с
медиа. `missing` и `unresolved` различаются. Mirror может сам обращаться к
upstream, поэтому нельзя обещать, что fallback устранит любой official 429.
Все эти выводы основаны на документации, а не на живом испытании провайдера.
Ссылки и существенные детали перечислены в [batch-import](../architecture/batch-import.md).

## Решение и изменение плана

[ADR-0006](../adr/0006-mirror-batch-import.md) принимает mirror как отдельный
download/metadata provider и частично заменяет запрет пункта 6 ADR-0005.
Действующий M1a client не меняется: official verification остаётся отдельным
наблюдением, mirror metadata не получает его статус.

Первый прикладной сценарий M2 — наш batch API с долговечными item jobs, ограниченными
загрузками, partial success и retry. На стороне источника используются batch
metadata и отдельные raw files. Заданы границы provenance, source cooldown,
staging cleanup и необходимость bytes после удаления исходника даже при ETag.

Обновлены ROADMAP/TASKS, критерии M2, архитектурные ссылки и AGENTS. Только
проектирование и Markdown; runtime, схема, lock и состояние сервиса не менялись.

## Проверки и остаток

Проверены `git diff --check` и относительные ссылки: локальный helper проверил
20 Markdown-документов, 103 относительные ссылки разрешены.
Unit/pytest harness не запускались: исполняемый код не изменялся, как и просил
пользователь. Remote CI/push не выполнялись. M2 implementation не начата;
следующий шаг — рабочий adapter и provenance contract с целевыми тестами,
затем durable batch/jobs/worker по критериям milestone.
