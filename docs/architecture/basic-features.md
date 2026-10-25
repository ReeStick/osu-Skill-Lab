# Базовые измеряемые признаки

Контракт `BasicFeatures` реализован в
[`analysis/features.py`](../../src/osu_skill_lab/analysis/features.py).
Версия алгоритма — `basic-raw/1`, текущий reader — `osu-standard-v14/1`.
Вычисление принимает `ParsedBeatmap` и возвращает frozen dataclass из 22 скалярных
полей. Массивы объектов и timing points нужны во время анализа, в результат
признаков они не входят. `dataclasses.asdict()` даёт JSON-совместимый словарь.

## Последовательности и формулы

Пусть `O` — все объекты, стабильно отсортированные reader по времени начала.
`H` получается из `O` фильтрацией: остаются circles и slider heads. Spinner
не создаёт head и не разрывает последовательность: пара до и после него
по-прежнему участвует в измерениях. Равные времена сохраняют порядок файла.

Для каждой соседней пары `H[i], H[i+1]`:

```text
interval[i] = H[i+1].start_time_ms - H[i].start_time_ms
distance[i] = sqrt((H[i+1].x - H[i].x)^2 + (H[i+1].y - H[i].y)^2)
```

Интервалы измеряются в миллисекундах, расстояния — в исходных координатных
единицах `.osu`, обозначенных суффиксом `_px`. Это евклидово расстояние между
heads без нормализации по CS, clamp, округления, stacking или mods.
Для slider используется только head; anchors, endpoint, repeats, объявленная
длина и прохождение кривой не участвуют в этих расстояниях.

Среднее — арифметическое по наблюдениям, без взвешивания по времени.
Медиана — центральное значение отсортированных интервалов; при чётном
числе наблюдений — среднее двух центральных. Нулевые интервалы сохраняются
и входят во все агрегаты; деления на интервал и расчёта скорости здесь нет.

## Поля

| Поле | Определение |
| --- | --- |
| `hit_object_count` | `len(O)`, все circles, sliders и spinners |
| `circle_count` | Число circles |
| `slider_count` | Число sliders; repeats не увеличивают count |
| `spinner_count` | Число spinners |
| `timing_point_count` | Число всех timing points |
| `red_timing_point_count` | Число uninherited/red points |
| `inherited_timing_point_count` | Число inherited/green points |
| `red_bpm_min` | Минимум `60_000 / beat_length` по всем red points |
| `red_bpm_max` | Максимум той же последовательности BPM |
| `first_object_start_ms` | Начало первого объекта в `O`, включая spinners |
| `last_object_start_ms` | Начало последнего объекта в `O`, включая spinners |
| `object_start_span_ms` | `last_object_start_ms - first_object_start_ms` |
| `head_object_count` | `len(H) = circle_count + slider_count` |
| `head_pair_count` | `max(len(H) - 1, 0)` |
| `head_interval_min_ms` | Минимум `interval` |
| `head_interval_max_ms` | Максимум `interval` |
| `head_interval_mean_ms` | Арифметическое среднее `interval` |
| `head_interval_median_ms` | Медиана `interval` |
| `zero_head_interval_count` | Число элементов `interval`, равных нулю |
| `raw_head_distance_min_px` | Минимум `distance` |
| `raw_head_distance_max_px` | Максимум `distance` |
| `raw_head_distance_mean_px` | Арифметическое среднее `distance` |

BPM extrema охватывают все red lines, в том числе до первого или после
последнего объекта. Green lines задают raw SV, поэтому в BPM не участвуют.
Это не dominant BPM, не средний BPM и не диапазон исключительно игрового участка.

Start span не является длительностью карты, аудио или активной игры.
Он не учитывает spinner ends, slider duration, breaks, lead-in и outro.
Настройки AR/OD/CS/HP и slider settings сохраняются отдельными полями результата,
а не вычисляются из этих признаков.

## Пустые и единичные последовательности

Counts всегда целые и неотрицательные. При пустой `O` оба start timestamps
и start span равны `None`; для одного объекта start timestamps совпадают,
а span равен `0`. Отрицательные start timestamps допустимы согласно reader.

Если heads меньше двух, пар нет: `head_pair_count` и
`zero_head_interval_count` равны `0`; все агрегаты интервалов и расстояний
равны `None`. Карта только со spinners имеет start span, но не head pairs.
У нескольких одновременных heads span и интервалы могут быть равны `0`;
это измеренное значение, которое отличается от отсутствующего наблюдения.

BPM extrema равны `None`, если red points отсутствуют. Текущий reader требует
хотя бы одну red line, поэтому после успешного штатного разбора эти два поля
числовые даже при пустой `O`.

## Версии и ограничения

Результат детерминирован для одинаковых разобранных данных. Конечные числовые
значения и лимиты количества объектов обеспечиваются контрактом reader;
результат можно сериализовать через `json.dumps(..., allow_nan=False)`.
Вход extractor должен пройти reader: произвольные вручную созданные dataclasses
не получают отдельной повторной валидации.

Изменение формул, состава последовательностей или смысла полей требует новой
версии алгоритма. Для сопоставления результатов также учитываются checksum
исходных байтов, parser version и конфигурация, включая parser limits.

Эти скаляры — измерения raw данных. Они не оценивают skill profile,
турнирный слот, star rating, PP, strain или игровую сложность. До признаков,
зависящих от фактического gameplay, нужны отдельные определения effective
timing/SV, slider traversal, нормализации координат, stacking и mods.

Поведение закреплено синтетическими примерами в
[`test_features.py`](../../tests/unit/test_features.py): известная геометрия
и интервалы, head вместо slider endpoint, исключение spinners, одновременные
объекты, пустые и единичные последовательности, raw координаты и конечный JSON.
