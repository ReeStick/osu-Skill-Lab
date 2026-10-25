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
