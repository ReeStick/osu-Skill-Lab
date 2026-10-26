# ADR-0010: Ручная разметка, правило и обучаемый baseline

Status: Accepted
Date: 2026-10-26

## Context

Владелец согласовал гибридный интерфейс: решения по картам, настройка влияния
признаков и быстрый просмотр результатов на выборке. Это явное разрешение раннего
среза M4 до завершения difficulty engine M3. Интерфейс нужен для сбора разметки;
качество skill classification ещё нельзя подтвердить.

## Decision

1. Локальный `/lab`, HTML/CSS/ES modules из Python wheel, без отдельного frontend
   сервиса и Node runtime. Выборка — до 1000 совместимых `basic-raw/1` результатов.
   Исходные карты/objects для такого предпросмотра повторно не нужны.
2. Immutable определение тега относится к whole map NM. Решения `yes`, `no`,
   `unsure`, `unreviewed` хранятся append-only по tag/input; отсутствие решения не
   отрицательный пример. Изменение определения требует нового тега. Последний event
   задаёт текущее решение; optimistic event ID предотвращает потерю обновления.
3. Ручное правило — sigmoid от bias и взвешенных стандартизованных признаков.
   Нормализация фиксируется в версии; UI рассчитывает её по рабочей выборке только
   для исследовательской гипотезы. Ненулевой вес missing-признака даёт unknown.
   Движение ползунков не пишет БД; сохранение создаёт новую immutable конфигурацию.
4. Первый обучаемый provider — `binary-logistic/1`: sklearn LogisticRegression,
   liblinear, C=1, max_iter=1000, random_state=0. Только явные yes/no; минимум два
   train примера каждого класса. Median imputation и mean/std fit только на train;
   добавлены missing indicators. Полностью отсутствующие в train признаки исключаются.
   Это независимые бинарные модели тегов, не взаимоисключающие классы.
5. Пользователь отмечает контрольные карты; тренировочные примеры с тем же claimed
   set ID исключаются целиком. Без set ID группа — точный input SHA. Claims здесь
   лишь консервативная группировка, не официальный identity match; утечки между
   редакциями/песнями с неизвестной связью всё ещё возможны. Контроль помогает
   настройке, но после подбора порога не является независимым final test.
6. Обучение — один отдельный CPU process и один admission slot на API process.
   HTTP ждёт результат; это не durable training job/202. При отмене слот сохраняется
   до завершения CPU. RabbitMQ M2 обслуживает анализ карт независимо.
7. PostgreSQL хранит определения, sparse label events, bounded rule config и
   метаданные моделей/связи с конкретными analyses и label events. Веса/preprocessing
   модели — отдельный неисполняемый JSON artifact до 64 KiB с SHA-256, реальными
   версиями sklearn/NumPy и profile/training fingerprints. Это отдельный сценарий
   хранения моделей, не разрешение сохранять `.osu` или feature matrices в JSONB.
8. Preview Web Worker держит feature matrix в RAM и кеширует последний вектор оценок.
   Изменение порога переиспользует его; смена выборки/правила/модели сбрасывает кеш.
   Python и JS исполняют один portable контракт. Прогнозы не становятся human labels,
   score не объявляется калиброванной вероятностью. Постоянного prediction cache нет.

## Alternatives

- Только разметка: нет быстрого способа увидеть, что объясняют имеющиеся признаки.
- Только веса: экспертная гипотеза подменяет независимую разметку.
- Сразу сложный ML/GPU provider: пока нет размеченных данных для его оценки.
- Повторный анализ `.osu` при движении: ненужные CPU и network задержки.

## Consequences

Интерфейс позволяет собирать данные и проверять гипотезы. Он ещё не выдаёт
достоверный skill profile, tournament slots, SR/pp, segment tags или ML providers
в массовом pipeline. Нет автоматического присваивания тегов всей библиотеке.
Для нескольких API machines нужны shared artifact storage и общий training budget;
каталог UI пока до 200 тегов/100 версий, выборка — первые 1000 analyses.

100–200 ms — цель полного UI update, не подтверждённая характеристика.
Перед production нужны размеченный корпус, grouped evaluation и профилирование.

Контракт: [label-workbench](../architecture/label-workbench.md).
Основание baseline: [документация LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).
