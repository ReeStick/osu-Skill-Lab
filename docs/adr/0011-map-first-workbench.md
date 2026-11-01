# ADR-0011: Карта и разметка — основной сценарий workbench

Status: Accepted
Date: 2026-11-01
Refines: ADR-0010 (UI, catalog, default partition selection)

## Context

Владелец приоритизировал прикладную полезность, согласовал простой интерфейс
в духе выбора карты osu! и браузерный preview, затем полную переработку UI.
Основной сценарий: выбрать → посмотреть → отметить → следующая. ML-настройки
не должны быть условием ручной разметки.

## Decision

- `/lab` — коллекция и проверка одного тега. `/lab/research` сохраняет прежние
  правила, модели, обучение и аналитический UI; данные и старые API не удаляются.
- Коллекция переключает `yes` ↔ `unreviewed`. Explicit `no`/`unsure` видны текстом,
  не выводятся из отсутствия отметки. Проверка тега предлагает yes/no/unsure и
  переходит дальше только после успешного POST. Skip не пишет ничего.
- События остаются append-only с optimistic event ID. Undo отправляет ID своего
  события, а не последнего перечитанного чужого. После ошибки записи UI перечитывает
  сервер: потерянный ответ может означать уже выполненный commit.
- Для новой пары tag/input основной UI автоматически назначает partition:
  FNV-1a 32-bit от UTF-16 кода ASCII group key `set:<claimed set ID>` или
  `input:<sha256>`; hash % 5 == 0 → validation, иначе train. Одинаковая группа
  получает одну роль независимо от страницы. Существующая partition сохраняется.
  Это детерминированный приблизительный 20% interactive holdout, не stratified
  split и не независимый final test. Старый исследовательский UI допускает ручную
  partition; backend всё ещё исключает train-группы с validation-примерами.
- Новый GET `/lab/api/collection?q=&after_id=&limit=` возвращает current-profile
  rows и next_cursor. До 100 rows/page, поиск по title/artist/difficulty в БД.
  SQL wildcards экранируются. Нет normalizer/обучения на каждой странице.
  Прежний `/dataset` для экспериментов остаётся ограничен 1000 строками.
- Browser preview принимает локальный `.osu`, сверяет SHA-256 с выбранным анализом
  и строит геометрию в отдельном cancellable Web Worker. Новый upload анализируется
  существующим API; File reference остаётся только в RAM вкладки (до 20 / 32 MiB).
  Просмотр ранее импортированной карты требует снова выбрать её исходник.
- Preview — приблизительный NM: circles, sliders L/B/P/C, spans, timing/SV, AR/CS,
  spinner, seek/speed и необязательное локальное audio. Без stacking, ticks,
  hitsounds, mods, storyboard или заявления о точности stable/lazer. Пределы:
  .osu 4 MiB, 20 000 объектов, 1 млн точек пути, timeout подготовки 15 s;
  audio 100 MiB. Входы не попадают в localStorage, IndexedDB, БД или диск сервиса.
- Audio clock задаёт позицию при воспроизведении. Переключение карты останавливает
  playback, отзывает object URL, завершает worker и сбрасывает canvas. Устаревшие
  ответы каталога, labels, preview и playback не подменяют текущую карту.
- Нет новых runtime-зависимостей, migrations, очередей или storage-сервисов.
  Frontend остаётся ES modules, включёнными в Python wheel.

## Consequences

Просмотр требует доступного исходного файла. Получение raw через mirror, `.osz`,
изображения фона и точное игровое декодирование не входят в этот срез.
Новая коллекция не ограничена первой тысячей; модели, тег-каталог (200) и
исследовательские выборки сохраняют прежние ограничения. Изменение feature-profile
и поддержка старых профилей остаются отдельной задачей, не закрытой этим UI.

## Validation

Unit tests проверяют parser timing/curves и explicit label/undo semantics;
Chromium smoke — пользовательские сценарии с synthetic API; PostgreSQL integration
проверяет новый поиск/пагинацию отдельно. Фактические результаты — в devlog.
