import asyncio
import logging
from collections.abc import AsyncIterator
from concurrent.futures import Executor
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager
from statistics import fmean, pstdev
from uuid import UUID, uuid4

from asyncpg import PostgresError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from osu_skill_lab.analysis.label_baseline import TrainingExample, TrainingResult, train_baseline
from osu_skill_lab.application.lab_contracts import (
    FEATURE_KEYS,
    FEATURE_TITLES,
    DatasetView,
    LabelView,
    LabelWrite,
    LabRow,
    ModelSummary,
    ModelView,
    Normalizer,
    RuleView,
    RuleWrite,
    TagView,
    TagWrite,
    TrainRequest,
    current_profile,
    digest,
)
from osu_skill_lab.infrastructure import lab_repository as repository
from osu_skill_lab.infrastructure.database import Database
from osu_skill_lab.infrastructure.lab_models import (
    LabLabelEvent,
    LabModel,
    LabModelExample,
    LabRule,
    LabTag,
)
from osu_skill_lab.infrastructure.model_artifacts import ArtifactUnavailable, ModelArtifactStore

logger = logging.getLogger(__name__)


class LabNotFound(ValueError):
    pass


class LabConflict(ValueError):
    pass


class LabBusy(RuntimeError):
    pass


class LabUnavailable(RuntimeError):
    pass


def make_dataset(rows: list[LabRow], truncated: bool) -> DatasetView:
    means, scales = {}, {}
    values = [repository.feature_values(row) for row in rows]
    for key in FEATURE_KEYS:
        present = [value for row in values if (value := row[key]) is not None]
        means[key], scales[key] = (
            (fmean(present), pstdev(present) or 1.0) if present else (0.0, 1.0)
        )
    profile = current_profile()
    fingerprint = digest(
        {"profile": profile.model_dump(), "rows": [(row.analysis_id, row.sha256) for row in rows]}
    )
    return DatasetView(
        profile=profile,
        profile_sha256=profile.fingerprint,
        dataset_sha256=fingerprint,
        feature_catalog=[
            {"key": key, "title": title, "unit": unit}
            for key, (title, unit) in FEATURE_TITLES.items()
        ],
        normalizer=Normalizer(means=means, scales=scales),
        rows=rows,
        truncated=truncated,
    )


class LabService:
    def __init__(
        self, database: Database, executor: Executor, artifacts: ModelArtifactStore
    ) -> None:
        self.database, self.executor, self.artifacts = database, executor, artifacts
        self._training_slots: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._training_slots.put_nowait(None)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self.database.session() as session, session.begin():
                yield session
        except IntegrityError:
            raise LabConflict("Запись конфликтует с существующими данными") from None
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            logger.warning("Lab storage unavailable (%s)", type(exc).__name__)
            raise LabUnavailable("Хранилище разметки временно недоступно") from None

    async def _tag(self, session: AsyncSession, tag_id: UUID, *, lock: bool = False) -> LabTag:
        query = select(LabTag).where(LabTag.id == tag_id)
        row = await session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise LabNotFound("Тег не найден")
        return row

    async def tags(self) -> list[TagView]:
        async with self._session() as session:
            rows = await session.scalars(select(LabTag).order_by(LabTag.created_at).limit(200))
            return [repository.tag_view(row) for row in rows]

    async def create_tag(self, body: TagWrite) -> TagView:
        async with self._session() as session:
            return await repository.create_tag(session, body)

    async def dataset(self, tag_id: UUID | None, limit: int = 500) -> DatasetView:
        async with self._session() as session:
            if tag_id is not None:
                await self._tag(session, tag_id)
            rows, truncated = await repository.dataset_rows(session, tag_id, limit=limit)
        return await asyncio.to_thread(make_dataset, rows, truncated)

    async def label(self, tag_id: UUID, body: LabelWrite) -> LabelView:
        async with self._session() as session:
            await self._tag(session, tag_id, lock=True)
            rows, _ = await repository.dataset_rows(
                session, tag_id, limit=1, analysis_ids=[body.analysis_id]
            )
            if not rows:
                raise LabNotFound("Совместимый анализ не найден")
            row = rows[0]
            if (row.label.id if row.label else None) != body.expected_event_id:
                raise LabConflict("Разметка уже изменилась. Обновите набор и повторите решение")
            event = LabLabelEvent(
                tag_id=tag_id,
                input_id=row.input_id,
                analysis_id=row.analysis_id,
                value=body.value,
                partition=body.partition,
            )
            session.add(event)
            await session.flush()
            return repository.label_view(event)

    async def map_labels(self, analysis_id: int) -> dict[UUID, LabelView]:
        async with self._session() as session:
            rows, _ = await repository.dataset_rows(
                session, None, limit=1, analysis_ids=[analysis_id]
            )
            if not rows:
                raise LabNotFound("Совместимый анализ не найден")
            return await repository.input_labels(session, rows[0].input_id)

    async def rules(self, tag_id: UUID) -> list[RuleView]:
        async with self._session() as session:
            await self._tag(session, tag_id)
            rows = await session.scalars(
                select(LabRule)
                .where(LabRule.tag_id == tag_id)
                .order_by(LabRule.created_at.desc())
                .limit(100)
            )
            return [repository.rule_view(row) for row in rows]

    async def save_rule(self, tag_id: UUID, body: RuleWrite) -> RuleView:
        if body.profile_sha256 != current_profile().fingerprint:
            raise LabConflict("Версия признаков отличается от текущего профиля")
        if body.model_id:
            saved_model = await self.model(body.model_id)
            if (
                saved_model.tag_id != tag_id
                or saved_model.artifact.profile.fingerprint != body.profile_sha256
            ):
                raise LabConflict("Модель не соответствует тегу или версии признаков")
        async with self._session() as session:
            await self._tag(session, tag_id)
            if body.model_id:
                model = await session.get(LabModel, body.model_id)
                if model is None or model.tag_id != tag_id:
                    raise LabConflict("Модель не принадлежит этому тегу")
            specification = body.model_dump(mode="json")
            row = LabRule(
                id=uuid4(),
                tag_id=tag_id,
                model_id=body.model_id,
                configuration_sha256=bytes.fromhex(digest(specification)),
                specification=specification,
            )
            session.add(row)
            await session.flush()
            return repository.rule_view(row)

    async def models(self, tag_id: UUID) -> list[ModelSummary]:
        async with self._session() as session:
            await self._tag(session, tag_id)
            rows = await session.scalars(
                select(LabModel)
                .where(LabModel.tag_id == tag_id)
                .order_by(LabModel.created_at.desc())
                .limit(100)
            )
            return [repository.model_summary(row) for row in rows]

    async def model(self, model_id: UUID) -> ModelView:
        async with self._session() as session:
            row = await session.get(LabModel, model_id)
            if row is None:
                raise LabNotFound("Модель не найдена")
            summary = repository.model_summary(row)
        try:
            artifact = await asyncio.to_thread(self.artifacts.load, row.id, row.artifact_sha256)
        except ArtifactUnavailable:
            raise LabUnavailable("Артефакт модели недоступен или повреждён") from None
        return ModelView(**summary.model_dump(), artifact=artifact)

    async def train(self, tag_id: UUID, body: TrainRequest) -> ModelView:
        try:
            self._training_slots.get_nowait()
        except asyncio.QueueEmpty:
            raise LabBusy("Одна модель уже обучается. Дождитесь результата") from None
        release_on_exit = True
        model_id, artifact_hash = uuid4(), None
        try:
            async with self._session() as session:
                await self._tag(session, tag_id)
                rows, _ = await repository.dataset_rows(
                    session, tag_id, limit=1000, analysis_ids=body.analysis_ids
                )
                if len(rows) != len(body.analysis_ids):
                    raise LabConflict("В наборе есть недоступные или несовместимые анализы")
            examples = tuple(
                TrainingExample(
                    row.analysis_id,
                    row.label.id,
                    row.sha256,
                    f"set:{row.beatmap_set_id}" if row.beatmap_set_id else f"input:{row.sha256}",
                    row.label.value,
                    row.label.partition,
                    repository.feature_values(row),
                )
                for row in rows
                if row.label is not None and row.label.value in {"yes", "no"}
            )
            loop = asyncio.get_running_loop()
            try:
                future = loop.run_in_executor(
                    self.executor, train_baseline, tag_id, current_profile(), examples
                )
                try:
                    result = await asyncio.shield(future)
                except asyncio.CancelledError:
                    release_on_exit = False

                    def finished(task: asyncio.Future[TrainingResult]) -> None:
                        if not task.cancelled():
                            task.exception()
                        self._training_slots.put_nowait(None)

                    future.add_done_callback(finished)
                    raise
            except (BrokenProcessPool, RuntimeError):
                raise LabUnavailable("Процесс обучения временно недоступен") from None
            try:
                artifact_hash = await asyncio.to_thread(
                    self.artifacts.save, model_id, result.artifact
                )
            except ArtifactUnavailable:
                raise LabUnavailable("Не удалось сохранить артефакт модели") from None
            async with self._session() as session:
                model = LabModel(
                    id=model_id,
                    tag_id=tag_id,
                    artifact_sha256=artifact_hash,
                    training_sha256=bytes.fromhex(result.artifact.training_sha256),
                    train_count=result.train_count,
                    validation_count=result.validation_count,
                    excluded_same_set=result.excluded_same_set,
                    latest_event_id=max(row.label.id for row in rows if row.label is not None),
                )
                session.add(model)
                await session.flush()
                session.add_all(
                    [
                        LabModelExample(
                            model_id=model_id,
                            analysis_id=row.analysis_id,
                            label_event_id=row.event_id,
                            partition=row.partition,
                        )
                        for row in result.examples
                    ]
                )
            return await self.model(model_id)
        except BaseException:
            if artifact_hash is not None:
                # Only our newly created artifact; never sweep a shared directory.
                try:
                    async with self._session() as session:
                        committed = await session.get(LabModel, model_id)
                    if committed is None:
                        await asyncio.to_thread(
                            self.artifacts.remove_owned, model_id, artifact_hash
                        )
                except (LabUnavailable, OSError):
                    logger.warning("Could not reconcile new model artifact %s", model_id)
            raise
        finally:
            if release_on_exit:
                self._training_slots.put_nowait(None)
