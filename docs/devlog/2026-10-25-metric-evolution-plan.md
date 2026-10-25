# 2026-10-25 — Эволюция метрик и подготовка osu! API

## Требование

Владелец указал опираться при выборе сохраняемых метрик на официальный
difficulty/performance calculation osu!, учитывать обновления формул и новые
атрибуты. Собственные показатели нужны позднее. Также ближайшим ожидается
срез интеграции osu! API, чтобы подготовить identity/metadata до engineering метрик.

## Что проверено

Прочитаны текущие `OsuDifficultyAttributes`, `OsuPerformanceAttributes` и
`OsuPerformanceCalculator` в официальном ppy/osu. В просмотренном `master` есть
reading наряду с aim/speed/flashlight; это не доказывает версию, развёрнутую на сайте.
Performance calculator использует score statistics, mods и compatibility context,
поэтому pp нельзя хранить как независимое универсальное свойство карты.

Просмотрены README rosu-pp и Cargo.toml Python binding: wrapper и underlying engine
имеют разные версии, port указывает поддерживаемую upstream revision. Кандидат
ещё не выбран/установлен. Просмотрена актуальная документация osu! API v2:
metadata, lookup, difficulty attributes endpoint и правила использования.
Авторизованных API-запросов и скачивания карт в этом срезе не было.

GitHub commits API не открылся через web-инструмент. Поэтому не заявляется новый
проверенный commit SHA; ссылки на просмотренные ветки помечены датой и должны
быть закреплены конкретной ревизией при подключении engine.

Источники и границы выводов перечислены в
[metric-evolution](../architecture/metric-evolution.md).

## Принятое решение

[ADR-0004](../adr/0004-versioned-metric-families.md) сохраняет PostgreSQL и
временные исходники из ADR-0003, но определяет развитие независимых семейств:
`basic_raw`, `osu_difficulty`, `osu_performance`, позднее собственные показатели.
Внешний расчёт требует точного provider/build/engine provenance, известной
upstream revision, adapter/schema versions и полного контекста параметров.
Обновления создают новые snapshots; поля расширяются типизированными миграциями.
API-данным с неизвестным engine не назначается выдуманная локальная версия.

В ROADMAP/TASKS перед M2 выделен запланированный M1a: API metadata/identity,
OAuth, checksum verification, cache/rate limits и разрешённый on-demand input.
Начало M3 — выбранный difficulty engine и соответствие upstream метрик;
собственные определения идут после этой основы.

## Изменения и проверки

Обновлены AGENTS, README, ROADMAP, TASKS, architecture/database и overview;
добавлены контракт эволюции, ADR и ссылки в журналах. Изменены только Markdown
документы. Runtime, схема PostgreSQL, lock и результаты M1 не менялись.

Проверка этого среза: `git diff --check` и разрешение относительных Markdown
ссылок изменённых документов: 12 Markdown-файлов, 64 относительные ссылки разрешены
локальным helper `.tools/check_metric_docs.py` (не включается в Git).
Тесты runtime повторно не запускались: новый
исполняемый код отсутствует. Предыдущие 196 passed относятся к M1, а не к
проверке новой интеграции. CI/push не выполнялись.

## Следующий рабочий срез

Реализовать M1a с отдельными DTO/adapters и интеграционными проверками внешних
ошибок/несовпадения checksum; не смешивать metadata fetch с локальным расчётом pp.
До сохранения первого difficulty/performance snapshot контракт ADR-0004 должен
получить конкретное DDL и реализацию provenance/identity в коде.
