# Тестовые данные

Unit-тесты создают маленькие синтетические `.osz` в `tmp_path`. Для них не нужны
загрузки, реальные карты или доступ к osu! API. Интеграционные тесты БД описаны
в корневом README и не используют локальный корпус.

`unlabeled_osu_maps/` — необязательный, игнорируемый Git каталог реальных `.osz`,
предоставленных владельцем для ручных проверок. Это не размеченный датасет:
из него нельзя делать выводы о качестве skill/slot classification. Карты, аудио,
изображения и manifests не включаются в коммиты.

```powershell
uv run --locked osu-skill-lab extract-osz tests/unlabeled_osu_maps
```

Извлечённые `.osu` и manifests находятся в игнорируемом `data/unpacked_osu_maps/`.
Контракт и ограничения: [local-import](../docs/architecture/local-import.md).

`fixtures/analytic-v14.osu` — созданный в проекте синтетический пример с circles,
slider и spinner, tempo/SV points и ссылками на несуществующие медиа. Реальные
assets не нужны; ignored поля намеренно могут содержать неигровые значения.
Тестируется аналитический reader, не полная валидация client-формата.

```powershell
uv run --locked osu-skill-lab inspect-osu tests/fixtures/analytic-v14.osu
uv run --locked osu-skill-lab inspect-osu data/unpacked_osu_maps --recursive
```

Сводки реальных карт остаются в `data/`; CI запускает только синтетические случаи.
