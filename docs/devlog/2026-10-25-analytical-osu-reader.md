# 2026-10-25 — Аналитический reader .osu

## Цель

Продолжить M1 после `.osz` extraction (`eda9e7d`): читать только параметры
карты, необходимые анализу. Владелец уточнил, что полноценный parser медиа,
фона, видео, storyboard и прочих ресурсов не нужен.

## Исходная проблема

Локально подготовлены 33 `.osu`, но независимой модели их аналитических данных
не было. На старте из пользовательских отслеживаемых файлов оставался изменённым
только корневой `.gitignore`; его не изменяли и не включаем в коммит этого среза.

Предварительный осмотр исходных ZIP members дал 26 400 объектов и 6 377 timing
points. Все 33 карты — v14; максимумы в этом корпусе: 1 624 объекта, 1 013 timing
points на карту и 207 переданных anchors в одном слайдере. Эти значения не
использовались как ожидаемые игровые skill labels или доказательство полноты формата.

## Рассмотренные решения

1. Полный игровой decoder с media/event/sample handling — шире запроса и задач анализа.
2. Взять внешнюю библиотеку целиком — нужно проверить границы API и контролировать
   нормализацию, которая могла бы незаметно заменить raw данные.
3. Независимый целевой reader, версия/лимиты, проверяемая модель и CLI summary.

## Принятое решение

Вариант 3, без новых зависимостей. Поддержка ограничена v14/UTF-8 osu!standard.
Архивный adapter остаётся отдельно; reader принимает bytes и не имеет файлового I/O.
Метаданные нужны для идентификации, difficulty/timing/objects — для будущих признаков.
Медиа, samples и остальные секции пропускаются. Значения считаются raw, не
результатом применения mods и игровых нормализаций.

Контракт: [osu-parser](../architecture/osu-parser.md). Значимых изменений принятых
границ монолита или persistence нет, отдельный ADR на reader не создавался.

## Реализация

- [models.py](../../src/osu_skill_lab/analysis/models.py): dataclasses settings,
  metadata, timing points, типизированные circles/sliders/spinners, limits/result.
- [parser.py](../../src/osu_skill_lab/analysis/parser.py): `parse_osu(bytes)`,
  версия `osu-standard-v14/1`, checksum входа, validation и ошибки с section/line.
- [summary.py](../../src/osu_skill_lab/analysis/summary.py): raw counts/settings,
  BPM extrema по red lines, первый и последний start time.
- [CLI](../../src/osu_skill_lab/cli.py): `inspect-osu` для файла/каталога,
  explicit recursion, JSON Lines, продолжение после ошибки одного файла.
- Сохраняются repeated slider anchors, spans и объявленная длина. Curves и
  длительности не вычисляются. Timing order проверяется; objects сортируются
  стабильно с warning только при фактическом изменении порядка.
- [Синтетический fixture](../../tests/fixtures/analytic-v14.osu) содержит ссылки
  на несуществующие media и намеренно невалидные ignored sample/editor поля.
- [Тесты parser](../../tests/unit/test_parser.py): 67 случаев; добавлены 3 CLI
  теста к существующим 2. Всего 70 новых тестов этого среза.

## Проблемы

- В первом поиске client ConvertHitObjectParser использован неверный путь,
  вернувший 404. Найден актуальный `osu.Game/Rulesets/Objects/Legacy/`;
  итоговые ссылки на первичные источники находятся в контракте.
- Первый mypy обнаружил повторное использование имени `value`: ранее оно
  получало str после partition, затем число в том же scope функции. Числовая
  переменная переименована; ошибки не подавлялись.
- Ruff нашёл setattr с константой в тесте immutability. Вместо добавления
  suppression убрана проверка стандартной семантики frozen dataclass;
  оставлена проверка воспроизводимости самого reader.
- На review поле TimingPoint `beat_length_ms` переименовано в `beat_length`:
  у green lines это inverse SV, единица ms была бы ошибочной. У red lines
  BPM вычисляется отдельно, у green lines — None.
- Исследование client decoder подтвердило special-case NaN SV. В текущий
  конечный числовой контракт он не входит; это ограничение явно задокументировано,
  а не объявлено несуществующим форматом клиента.

## Проверки

Среда и uv bootstrap те же, что в M0. Для temp-файлов Windows и чтения результатов
распаковки использован разрешённый запуск вне sandbox; ослабление прав не добавлялось.

| Команда / сценарий | Фактический итог |
| --- | --- |
| `uv lock --check --offline` | Актуален, 39 packages; dependency graph не менялся |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 46 files already formatted |
| `mypy` | No issues found in 26 source files |
| Первый целевой прогон parser + CLI | 66 passed; после него добавлены ещё 6 malformed cases |
| Финальный `pytest -m "not integration"` | 126 passed, 4 deselected, 1.23s |
| CLI `inspect-osu data/unpacked_osu_maps --recursive` | 33 успешных JSON-сводки, без warnings и ошибок |
| Сверка source_sha256 в сводках с extraction manifests | Все 33 совпали |

Итоги корпуса: 16 654 circles, 9 690 sliders и 56 spinners; 162 red tempo points
и 6 215 inherited points. Суммы совпали с предварительным независимым подсчётом
из ZIP members. Сводки сохранены в `data/map-summaries.jsonl` как локальный
UTF-8 JSON Lines файл. Он, карты и manifests не включаются в Git.

Тесты проверяют поля и defaults, distinction red/green, четыре curve types,
сохранение repeated anchors, BOM/CRLF/comments, сортировку с ties, пустые objects,
malformed slider/spinner/timing rows, неподдержанные modes/versions/types,
NaN/inf, отсутствующие/повторяющиеся аналитические данные и границы лимитов.
Изменение ссылок на медиа не меняет аналитические значения, но меняет source checksum.

PostgreSQL integration, migration cycle и Docker build не повторялись: persistence,
HTTP и deployment-конфигурация этим срезом не менялись. Успешный разбор корпуса
не является сравнением с client/rosu по effective gameplay и difficulty.

## Что я узнал

Один столбец timing point меняет смысл в зависимости от uninherited flag:
обобщённое имя с ms маскировало бы ошибку единиц. Сохранение raw геометрии
и повторяющихся anchors необходимо до выбора нормализации будущих features.
Полный игровой decoder допускает больше legacy случаев, чем текущий reader;
границу поддержки нужно называть явно.

## Что можно улучшить

Когда появятся duration/aim/strain features, определить effective timing/SV,
same-offset precedence, clamp/округление, stacking и mods отдельными функциями
с версиями, формулами и тестами. Поддержку других format versions добавлять
при реальной потребности и fixtures, а не расширять номер в header без проверки.

## Следующие шаги

Storage abstraction, первые Beatmap/BeatmapSet модели и версии исходников по checksum.
Затем измеряемые базовые признаки, CPU-обработка вне event loop и REST-сценарий M1.
M1 в целом не закрыт; star rating/PP, skills и tournament slots здесь не реализованы.
