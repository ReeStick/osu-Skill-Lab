from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as PathParameter
from fastapi.responses import FileResponse

from osu_skill_lab.application.lab_contracts import (
    CollectionPage,
    DatasetView,
    LabelView,
    LabelWrite,
    ModelSummary,
    ModelView,
    RuleView,
    RuleWrite,
    TagView,
    TagWrite,
    TrainRequest,
)
from osu_skill_lab.application.lab_service import (
    LabBusy,
    LabConflict,
    LabNotFound,
    LabService,
    LabUnavailable,
)

router = APIRouter(prefix="/lab", tags=["label-workbench"])
ASSETS = Path(__file__).resolve().parents[1] / "web"


def lab_service(request: Request) -> LabService:
    return cast(LabService, request.app.state.lab_service)


@asynccontextmanager
async def _errors() -> AsyncIterator[None]:
    try:
        yield
    except LabNotFound as exc:
        raise HTTPException(404, detail=str(exc)) from None
    except LabConflict as exc:
        raise HTTPException(409, detail=str(exc)) from None
    except LabBusy as exc:
        raise HTTPException(429, detail=str(exc), headers={"Retry-After": "2"}) from None
    except LabUnavailable as exc:
        raise HTTPException(503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None


Service = Annotated[LabService, Depends(lab_service)]


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(ASSETS / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/research", include_in_schema=False)
async def research() -> FileResponse:
    return FileResponse(ASSETS / "research.html", headers={"Cache-Control": "no-cache"})


@router.get("/api/collection", response_model=CollectionPage)
async def collection(
    service: Service,
    after_id: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CollectionPage:
    async with _errors():
        return await service.collection(after_id=after_id, search=q.strip(), limit=limit)


@router.get("/api/tags", response_model=list[TagView])
async def tags(service: Service) -> list[TagView]:
    async with _errors():
        return await service.tags()


@router.post("/api/tags", status_code=201, response_model=TagView)
async def create_tag(body: TagWrite, service: Service) -> TagView:
    async with _errors():
        return await service.create_tag(body)


@router.get("/api/dataset", response_model=DatasetView)
async def dataset(
    service: Service, tag_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=1000)] = 500
) -> DatasetView:
    async with _errors():
        return await service.dataset(tag_id, limit)


@router.post("/api/tags/{tag_id}/labels", status_code=201, response_model=LabelView)
async def label(tag_id: UUID, body: LabelWrite, service: Service) -> LabelView:
    async with _errors():
        return await service.label(tag_id, body)


@router.get("/api/analyses/{analysis_id}/labels", response_model=dict[UUID, LabelView])
async def map_labels(
    analysis_id: Annotated[int, PathParameter(gt=0, le=2**63 - 1)], service: Service
) -> dict[UUID, LabelView]:
    async with _errors():
        return await service.map_labels(analysis_id)


@router.get("/api/tags/{tag_id}/rules", response_model=list[RuleView])
async def rules(tag_id: UUID, service: Service) -> list[RuleView]:
    async with _errors():
        return await service.rules(tag_id)


@router.post("/api/tags/{tag_id}/rules", status_code=201, response_model=RuleView)
async def save_rule(tag_id: UUID, body: RuleWrite, service: Service) -> RuleView:
    async with _errors():
        return await service.save_rule(tag_id, body)


@router.get("/api/tags/{tag_id}/models", response_model=list[ModelSummary])
async def models(tag_id: UUID, service: Service) -> list[ModelSummary]:
    async with _errors():
        return await service.models(tag_id)


@router.get("/api/models/{model_id}", response_model=ModelView)
async def model(model_id: UUID, service: Service) -> ModelView:
    async with _errors():
        return await service.model(model_id)


@router.post("/api/tags/{tag_id}/models", status_code=201, response_model=ModelView)
async def train(tag_id: UUID, body: TrainRequest, service: Service) -> ModelView:
    async with _errors():
        return await service.train(tag_id, body)
