# Аналитический reader .osu v14

Парсер читает только данные, нужные анализу. Вход — `bytes`, выход —
immutable dataclasses из `analysis/models.py`. Нет FastAPI, ORM, файлового I/O
или обращения к ресурсам карты. Версия контракта: `osu-standard-v14/1`.

## Поддерживаемые данные

| Секция | Используемые поля |
| --- | --- |
| General | Mode, StackLeniency |
| Metadata | Title/Artist и Unicode-варианты, Creator, Version, Source, Tags, BeatmapID/BeatmapSetID |
| Difficulty | HPDrainRate, CircleSize, OverallDifficulty, ApproachRate, SliderMultiplier, SliderTickRate |
| TimingPoints | time, beatLength, meter, uninherited, effects |
| HitObjects | позиция, время начала, type flags; path/spans/length слайдера; конец spinner |

Editor, Events, Colours, storyboard, hitsounds, sample banks и другие поля
игнорируются. В частности, break events пока тоже не читаются. Упоминание
аудио/видео/изображения не приводит к открытию файла или проверке его наличия.
Невалидное значение игнорируемого поля само по себе не означает ошибку reader.
Поэтому успешный разбор не является полной валидацией игрового `.osu`.

## Контракт входа

- Только UTF-8 с необязательным BOM и заголовком `osu file format v14`.
  Более ранние версии и lazer v128 отклоняются явно, без заявления совместимости.
- Поддержан osu!standard. Mode отсутствует → 0; другие modes отклоняются.
- Обязательны секции Difficulty, TimingPoints и HitObjects. Пустые HitObjects
  допустимы как данные, но не подтверждают пригодность карты для анализа.
- AR отсутствует → OD. StackLeniency отсутствует → 0.7. Остальные используемые
  difficulty-поля обязательны. Metadata допускает пустые значения; ID отсутствует,
  равен 0 или -1 → `None`. Положительный ID сохраняется, существование на сайте
  не проверяется.
- HP/CS/OD/AR принимаются в диапазоне 0–10. SliderMultiplier/SliderTickRate >0.
  Числа должны быть конечными, с абсолютным значением ≤10¹². Это политика
  reader, а не перечисление всех файлов, которые способен открыть клиент.
- Полные строки комментариев `//` игнорируются; inline comments в числах
  не поддержаны. Повтор аналитической секции или используемого ключа — ошибка.

## Timing и объекты

Timing point содержит восемь полей; три поля samples/volume пропускаются.
Для red line `uninherited=1`, `beat_length>0`, BPM = `60_000 / beat_length`.
Для green line `uninherited=0`, `beat_length<0`; это raw обратное SV-значение,
а не отрицательный BPM и не длительность в миллисекундах. Поэтому поле модели
называется `beat_length` без суффикса единицы. BPM у green line — `None`.
Нужна хотя бы одна red line. Порядок timing points проверяется, равные offsets
и их исходный порядок сохраняются. Разрешены отрицательные offsets.

Circles, sliders и spinners различаются по type bits. Несколько object types
одновременно, mania hold или неизвестный тип отклоняются. New-combo и colour-skip
flags сохраняются как raw flags. Координаты и timestamps хранятся без игрового
clamp/округления. Объекты стабильно сортируются по start time; при изменении
порядка возвращается `hit_objects_stably_sorted`. Source line numbers сохраняются.

У слайдеров принимаются B/C/L/P и числовые anchors. `control_points` включает
head первой точкой; повторы anchors не удаляются. `spans` — исходное `slides`,
то есть repeat count + 1. `pixel_length` — объявленная длина одного прохода.
Кривая не аппроксимируется, её геометрическая корректность и duration не вычисляются.
У spinner проверяется `end_time_ms >= start_time_ms`.

## Сводка и CLI

```powershell
uv run --locked osu-skill-lab inspect-osu tests/fixtures/analytic-v14.osu
uv run --locked osu-skill-lab inspect-osu data/unpacked_osu_maps --recursive
```

Для каталога рекурсия только с `--recursive`. CLI ограничивает чтение файла
до `max_file_bytes + 1`, вызывает чистый reader и выдаёт JSON Lines в stdout.
В stderr — ошибки с code, section, line_number, message. Ошибки одного файла
не отменяют остальные; exit 1 при любой ошибке или пустом каталоге, 0 при успехе,
2 при ошибке аргументов. Для локального snapshot можно сохранить stdout в файл;
например, в PowerShell использовать `Set-Content -Encoding UTF8`.

`summarize_beatmap` возвращает исходные settings/metadata, checksum входа,
версию parser, counts, BPM extrema по всем red lines и первый/последний **start**.
Это не duration, dominant/средний BPM или диапазон BPM только играбельного участка.
SHA-256 считается по всем исходным байтам `.osu`, включая игнорируемый текст:
изменение строки с видео меняет checksum, но не аналитические значения.

Summary — диагностический вывод, не вход feature extraction. `POST /analyses`
передаёт bytes reader и работает с `ParsedBeatmap` внутри CPU-процесса;
после расчёта сохраняются компактные metadata/settings и скалярные результаты.
Объекты и timing points в постоянное хранилище не попадают. См.
[basic-features](basic-features.md) и [database](database.md).

## Ограничения и дальнейшие шаги

Сейчас нет effective settings с mods, star rating/PP, stacking, resolved SV
timeline, оценки длительности слайдеров, ticks, curve traversal и skill scores.
Reader не копирует все client fallbacks. Например, special-case NaN SV,
поддерживаемый клиентом для отключения slider ticks, здесь отклоняется явно.
Игровое clamp/округление координат и настроек также не воспроизводится.
Будущие признаки должны явно определить нормализацию и расчёт effective данных.

Лимиты по умолчанию: файл 4 MiB; строка 65 536 символов; 100 000 объектов;
100 000 timing points; 2 048 control points на слайдер с учётом head;
100 000 control points на карту; 9 000 spans. Limits сохраняются в ParsedBeatmap.
Проверка размера происходит до UTF-8 decode, остальных лимитов — при обходе.
Это ограничивает вход; жёсткий memory/CPU budget процесса здесь не заявляется.

Источники, проверенные 2026-10-25: [формат osu!](https://osu.ppy.sh/wiki/en/Client/File_formats/osu_(file_format)),
[client decoder](https://github.com/ppy/osu/blob/master/osu.Game/Beatmaps/Formats/LegacyBeatmapDecoder.cs),
[hit object reader](https://github.com/ppy/osu/blob/master/osu.Game/Rulesets/Objects/Legacy/ConvertHitObjectParser.cs).
Реализация собственная; список поддерживаемых случаев зафиксирован выше и тестами.
