import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from osu_skill_lab.analysis.label_baseline import TrainingExample, TrainingResult, train_baseline
from osu_skill_lab.application.lab_contracts import FeatureProfile, TrainRequest
from osu_skill_lab.application.lab_service import LabBusy, LabService
from osu_skill_lab.application.preparation import PreparedAnalysis, prepare_analysis
from osu_skill_lab.config import Settings
from osu_skill_lab.infrastructure.analysis_repository import save_analysis
from osu_skill_lab.infrastructure.lab_models import LabLabelEvent, LabModelExample
from osu_skill_lab.infrastructure.models import AnalysisResult
from osu_skill_lab.main import create_app

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytic-v14.osu"


async def seed(engine: AsyncEngine, count: int = 8) -> list[int]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = []
    for index in range(count):
        data = FIXTURE.read_bytes().replace(b"BeatmapID: 0", f"BeatmapID: {index + 1}".encode())
        data = data.replace(b"BeatmapSetID: -1", f"BeatmapSetID: {index + 1}".encode())
        data = (
            data.partition(b"[HitObjects]")[0]
            + b"[HitObjects]\n"
            + b"\n".join(
                f"{(i * 43) % 512},192,{1000 + i * (100 + index * 25)},1,0,0:0:0:0:".encode()
                for i in range(index + 2)
            )
        )
        candidate = prepare_analysis(data)
        assert isinstance(candidate, PreparedAnalysis)
        async with sessions() as session, session.begin():
            ids.append((await save_analysis(session, candidate)).record.id)
            if index == 0:
                await save_analysis(session, replace(candidate, algorithm_version="basic-raw/old"))
    return ids


@pytest.fixture
async def lab_app(
    migrated_engine: AsyncEngine, database_settings: Settings, tmp_path: Path
) -> AsyncIterator[FastAPI]:
    settings = database_settings.model_copy(
        update={"model_artifact_directory": tmp_path / "models"}
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.database.session_factory.configure(bind=migrated_engine)
        yield app


async def test_map_labels_read_latest_independent_tags_without_changing_decisions(
    lab_app: FastAPI, migrated_engine: AsyncEngine
) -> None:
    ids = await seed(migrated_engine, count=2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=lab_app), base_url="http://test"
    ) as client:
        path = f"/lab/api/analyses/{ids[0]}/labels"
        assert (await client.get(path)).json() == {}
        tags = [
            (await client.post("/lab/api/tags", json={"name": name, "description": name})).json()[
                "id"
            ]
            for name in ("Timing", "Geometry")
        ]
        labels = {}
        for tag in tags:
            response = await client.post(
                f"/lab/api/tags/{tag}/labels",
                json={"analysis_id": ids[0], "value": "yes"},
            )
            assert response.status_code == 201
            labels[tag] = response.json()
        assert (await client.get(path)).json() == labels
        assert (await client.get(f"/lab/api/analyses/{ids[1]}/labels")).json() == {}
        # Removing one assigned chip means unreviewed, never an implicit negative.
        response = await client.post(
            f"/lab/api/tags/{tags[0]}/labels",
            json={
                "analysis_id": ids[0],
                "value": "unreviewed",
                "expected_event_id": labels[tags[0]]["id"],
            },
        )
        assert response.status_code == 201
        labels[tags[0]] = response.json()
        assert (await client.get(path)).json() == labels
        async with async_sessionmaker(migrated_engine)() as session:
            assert await session.scalar(select(func.count()).select_from(LabLabelEvent)) == 3
        for bad in (0, -1, 2**63):
            assert (await client.get(f"/lab/api/analyses/{bad}/labels")).status_code == 422
        assert (await client.get("/lab/api/analyses/999999/labels")).status_code == 404
        async with async_sessionmaker(migrated_engine)() as session:
            old = await session.scalar(
                select(AnalysisResult.id).where(AnalysisResult.algorithm_version == "basic-raw/old")
            )
        assert (await client.get(f"/lab/api/analyses/{old}/labels")).status_code == 404


async def test_workbench_end_to_end_preserves_decisions_versions_and_model_lineage(
    lab_app: FastAPI, migrated_engine: AsyncEngine
) -> None:
    ids = await seed(migrated_engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=lab_app), base_url="http://test"
    ) as client:
        assert (await client.get("/lab")).status_code == 200
        assert (await client.get("/lab/assets/preview-worker.js")).status_code == 200
        assert (await client.get("/lab/api/dataset?limit=1001")).status_code == 422
        tag_body = {"name": "Tempo changes", "description": "Explicit synthetic test criteria"}
        response = await client.post("/lab/api/tags", json=tag_body)
        assert response.status_code == 201, response.text
        tag = response.json()["id"]
        assert (
            await client.post("/lab/api/tags", json={**tag_body, "name": "TEMPO CHANGES"})
        ).status_code == 409
        assert len((await client.get("/lab/api/tags")).json()) == 1
        path = f"/lab/api/tags/{tag}"
        data = (await client.get(f"/lab/api/dataset?tag_id={tag}")).json()
        assert [row["analysis_id"] for row in data["rows"]] == ids
        assert all(row["label"] is None for row in data["rows"])
        limited = (await client.get("/lab/api/dataset?limit=2")).json()
        assert limited["truncated"] and len(limited["rows"]) == 2
        labels = []
        for index, analysis_id in enumerate(ids):
            response = await client.post(
                path + "/labels",
                json={
                    "analysis_id": analysis_id,
                    "value": "no" if index < 3 else "yes" if index < 6 else "unsure",
                    "partition": "validation" if index in (2, 5) else "train",
                    "expected_event_id": None,
                },
            )
            assert response.status_code == 201, response.text
            labels.append(response.json())
        stale = await client.post(path + "/labels", json={"analysis_id": ids[0], "value": "yes"})
        assert stale.status_code == 409
        first_rule = {
            "name": "Initial hypothesis",
            "profile_sha256": data["profile_sha256"],
            "dataset_sha256": data["dataset_sha256"],
            "normalizer": data["normalizer"],
            "weights": {"hit_object_count": 1},
            "threshold": 0.5,
        }
        saved = await client.post(path + "/rules", json=first_rule)
        assert saved.status_code == 201, saved.text
        second = await client.post(path + "/rules", json={**first_rule, "threshold": 0.7})
        assert second.status_code == 201
        assert saved.json()["configuration_sha256"] != second.json()["configuration_sha256"]
        assert len((await client.get(path + "/rules")).json()) == 2
        assert (
            await client.post(path + "/rules", json={**first_rule, "profile_sha256": "0" * 64})
        ).status_code == 409
        response = await client.post(path + "/models", json={"analysis_ids": ids})
        assert response.status_code == 201, response.text
        model = response.json()
        assert model["train_count"] == 4 and model["validation_count"] == 2
        assert model["latest_event_id"] == labels[-1]["id"], (
            "Uncertain decisions also belong to the frozen snapshot"
        )
        assert (await client.get(f"/lab/api/models/{model['id']}")).json() == model
        assert "artifact" not in (await client.get(path + "/models")).json()[0]
        model_rule = {
            "name": "Baseline threshold",
            "kind": "model",
            "profile_sha256": data["profile_sha256"],
            "dataset_sha256": data["dataset_sha256"],
            "model_id": model["id"],
            "threshold": 0.6,
        }
        assert (await client.post(path + "/rules", json=model_rule)).status_code == 201
        after = (await client.get(f"/lab/api/dataset?tag_id={tag}")).json()
        assert [row["label"] for row in after["rows"]] == labels, (
            "Predictions must not overwrite human labels"
        )
        sessions = async_sessionmaker(migrated_engine)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(LabLabelEvent)) == 8
            lineage = list(
                await session.scalars(
                    select(LabModelExample).where(LabModelExample.model_id == UUID(model["id"]))
                )
            )
            assert {row.label_event_id for row in lineage} == {label["id"] for label in labels[:6]}
        artifact_path = lab_app.state.lab_service.artifacts.directory / f"{model['id']}.json"
        artifact_path.write_text("{}")
        assert (await client.get(f"/lab/api/models/{model['id']}")).status_code == 503
        assert (await client.post(path + "/rules", json=model_rule)).status_code == 503


async def test_concurrent_label_optimistic_guard_and_compensating_undo(
    lab_app: FastAPI, migrated_engine: AsyncEngine
) -> None:
    ids = await seed(migrated_engine, 1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=lab_app), base_url="http://test"
    ) as client:
        tag = (
            await client.post("/lab/api/tags", json={"name": "race", "description": "criteria"})
        ).json()["id"]
        path = f"/lab/api/tags/{tag}/labels"
        replies = await asyncio.gather(
            *[
                client.post(path, json={"analysis_id": ids[0], "value": value})
                for value in ("yes", "no")
            ]
        )
        assert sorted(reply.status_code for reply in replies) == [201, 409]
        latest = next(reply.json() for reply in replies if reply.status_code == 201)
        undo = await client.post(
            path,
            json={"analysis_id": ids[0], "value": "unreviewed", "expected_event_id": latest["id"]},
        )
        assert undo.status_code == 201 and undo.json()["id"] > latest["id"]
        assert (
            await client.post(path, json={"analysis_id": 9999999, "value": "no"})
        ).status_code == 404


async def test_cancelled_training_retains_admission_until_cpu_releases(
    lab_app: FastAPI, migrated_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await seed(migrated_engine, 4)
    original: LabService = lab_app.state.lab_service
    started, finish = threading.Event(), threading.Event()

    def blocked(
        tag_id: UUID, profile: FeatureProfile, rows: tuple[TrainingExample, ...]
    ) -> TrainingResult:
        started.set()
        assert finish.wait(10)
        return train_baseline(tag_id, profile, rows)

    monkeypatch.setattr("osu_skill_lab.application.lab_service.train_baseline", blocked)
    with ThreadPoolExecutor(max_workers=1) as executor:
        service = LabService(original.database, executor, original.artifacts)
        lab_app.state.lab_service = service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=lab_app), base_url="http://test"
        ) as client:
            tag = (
                await client.post(
                    "/lab/api/tags", json={"name": "cancel", "description": "criteria"}
                )
            ).json()["id"]
            for i, analysis_id in enumerate(ids):
                assert (
                    await client.post(
                        f"/lab/api/tags/{tag}/labels",
                        json={"analysis_id": analysis_id, "value": "no" if i < 2 else "yes"},
                    )
                ).status_code == 201
            request = TrainRequest(analysis_ids=ids)
            task = asyncio.create_task(service.train(UUID(tag), request))
            try:
                assert await asyncio.to_thread(started.wait, 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                with pytest.raises(LabBusy):
                    await service.train(UUID(tag), request)
            finally:
                finish.set()
            for _ in range(100):
                if not service._training_slots.empty():
                    break
                await asyncio.sleep(0.02)
            assert not service._training_slots.empty()
            assert await service.models(UUID(tag)) == []
