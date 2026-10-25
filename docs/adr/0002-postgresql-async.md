# ADR-0002: PostgreSQL, SQLAlchemy async и отдельные миграции

Status: Accepted
Date: 2026-10-25

## Context

Будущая модель имеет связи, ограничения уникальности и версии анализа.
FastAPI должен работать с БД без блокирующего драйвера. Схема пока не определена
достаточно, чтобы вводить все бизнес-таблицы.

## Decision

PostgreSQL — единственная БД; SQLAlchemy 2.0 async и asyncpg. Явные транзакции
в use cases, отдельная сессия на операцию. Alembic запускается отдельно через
async engine + `run_sync`, с `NullPool`; DSN читается из Settings без помещения
секретов в ini. M0 содержит baseline без доменного DDL.
Интеграционные тесты работают с реальным PostgreSQL и временными схемами.

## Alternatives

- MongoDB: не даёт преимущества для связей и ограничений этой модели.
- SQLite для тестов: не проверяет asyncpg и семантику PostgreSQL.
- Sync SQLAlchemy: допустим с отдельным thread pool, но добавляет иной путь I/O.
- `create_all()` на старте: не даёт версионирования изменений схемы.

## Consequences

Разработчику нужен PostgreSQL для полного набора проверок. Транзакции требуют
явного владельца; общую сессию нельзя использовать конкурентно. Миграции
составляют отдельную deployment-операцию. JSONB остаётся возможностью для
признаков; конкретная схема и индексы будут выбраны на M1.

## Revisit conditions

Измеренная необходимость другого хранилища, несовместимость драйвера или
неприемлемая стоимость async-подхода. Изменения оформляются новым ADR.

Основа API: [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
[Alembic asyncio cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic).
