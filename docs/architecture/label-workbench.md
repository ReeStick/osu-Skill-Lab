# Локальная разметка и быстрый предпросмотр

Реализован ранний срез M4 по явному согласованию владельца. M3 difficulty/pp engine
и автоматические tag providers остаются впереди. `/lab` использует существующие
22 raw measurements, а не игровые объекты/медиа или ещё не рассчитанные SR/pp.

## Пользовательский сценарий

1. Библиотека расположена справа: карточки difficulty с выделением активной карты,
   поиском и фильтрами. На узких экранах библиотека идёт под рабочей областью.
   SR пока отсутствует: `★ —` означает отсутствие расчёта, не нулевую сложность.
   Светлая и спокойная тёмная темы переключаются в шапке; выбор хранится локально.
2. Создать тег с определением положительного примера. Scope — карта целиком без mods;
   определение immutable, новый критерий оформляется новым тегом.
3. В отдельном виде «Разметка» назначить одной карте несколько тегов кликом или
   drag-and-drop. Для выбранного тега доступны «есть», «нет», «не уверен»;
   клавиши 1/2/3 действуют только в этом виде, ↑/↓ переключают карты.
   Прогнозы скрыты, их сортировки/фильтр расхождений отключены. Снятие тега
   возвращает `unreviewed`, а не создаёт отрицательный пример. Undo дописывает событие,
   возвращающее предыдущее решение. Неразмеченные/unsure не участвуют в обучении.
4. Отметить отдельные контрольные карты для конкретного тега. Карты из того же заявленного set ID
   исключаются из train. Контроль участвует в интерактивной настройке, поэтому
   precision/recall здесь не заменяют final test на независимых сетах.
5. «Аналитика» показывает оценку выбранного скилла, распределение оценок и до шести
   наибольших по модулю вкладов метрик. Мини-гистограммы — распределение измерения
   по рабочей выборке, штрих обозначает активную карту. Вклад равен слагаемому
   линейной суммы **до sigmoid**, не проценту важности или причинному влиянию.
   Для модели он включает train-median imputation и missing indicator с явной пометкой.
   Смещение показано отдельно; скрытые меньшие вклады входят в итоговый score.
   Настройки weights/bias/threshold, версии и обучение свёрнуты по умолчанию.
   При загрузке выбирается последняя совместимая сохранённая версия правила/порога;
   если её нет — последняя модель с проверкой profile. Обучение остаётся явным.
6. При наличии двух yes и двух no вне контрольных сетов обучить logistic baseline.
   Выбрать обученную модель или прежнюю версию; сохранить новый порог отдельно.
   Обновлённые label events требуют переобучения прежде чем показывать контрольные
   метрики старой модели. Ручные метки независимы от прогнозов.

`.osu` можно добавить из UI (до 100 файлов последовательно, каждый до 4 MiB);
используется существующий `POST /analyses`. Файлы и object arrays не сохраняются.
UI не воспроизводит карту; ссылка на osu! использует непроверенный claimed ID.
Это контекст для разметки, а не новая официальная сверка metadata.

## Расчёт и кеш

Ручное правило: `score = sigmoid(bias + sum(weight[k] * (x[k] - mean[k]) / std[k]))`.
Mean/std — текущая рабочая выборка и immutable часть сохранённого правила;
нулевой std заменяется 1. Missing при ненулевом весе даёт unknown, не false.
Сохранённая нормализация повторно не fit при загрузке версии на другой набор.

Модель: train-only median imputation → train-only standardization → missing
indicators → logistic regression. Полностью missing train-признаки исключаются.
Порядок coefficients — сначала numeric keys, затем indicators тех же keys.
Provider `binary-logistic/1` фиксирует liblinear/C=1/max_iter=1000/random_state=0.
Формат и реальные sklearn/NumPy версии записаны в artifact. Score [0,1] —
выход baseline, его калибровка и качество на реальных метках пока не проверены.

Browser Web Worker получает выборку один раз. Ключ последнего scoring-кеша содержит
weights/bias/normalizer/model artifact; threshold отсутствует. Новая выборка
полностью инвалидирует кеш. UI отбрасывает устаревшие ответы по generation.
Слайдеры debounce 35 ms. Показанное «Скоринг … ms» — время worker, без HTTP,
DOM/render и загрузки выборки. Это не benchmark полного UI и не гарантия 100–200 ms.

Вид разметки читает последние события всех тегов выбранного input одним запросом,
кеширует их в RAM вкладки и не загружает отдельную feature matrix на каждый тег.
Обновление библиотеки перечитывает метки. Записи сохраняют прежний optimistic
event ID; undo привязан к ID собственного последнего события, чтобы не затереть
более новое решение. Ответы для прежней карты/выборки отбрасываются по generation.
Отложенный preview получает снимок параметров, а смена тега отменяет его таймер.

## Хранение: migration 0006_label_lab

| Таблица | Назначение |
| --- | --- |
| `lab_tags` | UUID, name/canonical name, definition, definition SHA-256, created time |
| `lab_label_events` | Append-only tag/input/analysis, explicit value, train/validation, time; latest по input |
| `lab_rules` | Immutable UUID/tag/model reference, config hash, JSONB recipe до 8192 bytes, time |
| `lab_models` | Immutable UUID/tag, artifact/training hashes, counts, snapshot max event ID, time |
| `lab_model_examples` | Model → exact analysis + exact label event + train/validation role |

Rule JSONB — ограниченная конфигурация (weights, normalizer, threshold, profile,
dataset fingerprint или ссылка на модель); measured features остаются столбцами
`analysis_results`. В таблицах нет object arrays, feature matrices и predictions.
Latest labels — `DISTINCT ON(input_id)`; запись сериализуется lock строки тега и
проверкой `expected_event_id`, конфликт возвращает 409. API не имеет update/delete
immutable версий; административный SQL не запрещён триггером.

Artifact `<server-generated UUID>.json` хранится в
`OSU_LAB_MODEL_ARTIFACT_DIRECTORY` (default `data/model_artifacts`), до 64 KiB,
без pickle/joblib executable payload. Перед чтением проверяются hash и schema.
Новая запись создаётся без overwrite; при rollback удаляется только собственный
неизменённый artifact. Сбой диска/БД или аварийная остановка могут оставить orphan;
автоматического sweep shared directory нет. Отсутствующий/изменённый artifact — 503,
метаданные модели сами по себе не подменяют веса. PostgreSQL и каталог моделей
нужно backup/restore согласованно. Compose использует отдельный `model_artifacts`
volume, доступный non-root API; workers анализа карт его не используют.

## API и ограничения

Все пути относительно `/lab/api`:

| Запрос | Результат |
| --- | --- |
| GET/POST `/tags` | Каталог/создание immutable определения, до 200 |
| GET `/dataset?tag_id=…&limit=…` | Current profile, 22-column rows, latest labels, normalization; limit 1..1000 |
| GET `/analyses/{id}/labels` | Последние explicit события всех тегов input совместимого анализа, словарь tag UUID → label; unknown/incompatible → 404 |
| POST `/tags/{id}/labels` | Append decision с `expected_event_id` (null для первого) |
| GET/POST `/tags/{id}/rules` | До 100 версий/новая immutable версия |
| GET `/tags/{id}/models` | До 100 summaries без повторного чтения artifacts |
| GET `/models/{id}` | Metadata и проверенный portable artifact |
| POST `/tags/{id}/models` | Обучить по distinct `analysis_ids`, 4..1000; HTTP ждёт, 201 после сохранения |

Dataset выбирает первые совместимые analyses в порядке ID; `truncated` сообщает
о продолжении. Произвольные рабочие коллекции, server-side поиск/пагинация всей
библиотеки и multi-annotator agreement — будущие сценарии. Label store по input
не переносит решения автоматически между разными SHA редакциями карты.

CPU training ограничен одним отдельным process/slot на экземпляр API. Второй
запрос получает 429; при отмене слот не освобождается раньше CPU. Это локальная
admission, не общая очередь между replicas; restart может потерять in-flight train.
Для durable model training потребуется отдельный реальный job-сценарий.
Будущие признаки добавляются через typed family migration и новую profile identity;
старое правило/модель с другой profile не применяется молча. Нужные `.osu`
повторно получают только для новых извлечений, не для текущего scoring.

Решение: [ADR-0010](../adr/0010-hybrid-label-workbench.md).
Проект перехода в локальный редактор (без реализации): [client-handoff](client-handoff.md).
