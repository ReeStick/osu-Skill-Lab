from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from osu_skill_lab.application.batches import (
    BatchCapacityError,
    BatchConflict,
    BatchRequest,
    BatchService,
    BatchView,
)
from osu_skill_lab.application.service import AnalysisUnavailableError

router = APIRouter(prefix="/analysis-batches", tags=["batches"])


def batch_service(request: Request) -> BatchService:
    return cast(BatchService, request.app.state.batch_service)


@router.post("", status_code=202, response_model=BatchView)
async def submit_batch(
    body: BatchRequest,
    response: Response,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    service: Annotated[BatchService, Depends(batch_service)],
) -> BatchView:
    try:
        result = await service.submit(body, key)
    except BatchConflict as exc:
        raise HTTPException(409, detail=str(exc)) from None
    except BatchCapacityError:
        raise HTTPException(
            429, detail="Batch capacity is full", headers={"Retry-After": "5"}
        ) from None
    except AnalysisUnavailableError:
        raise HTTPException(503, detail="Batch storage unavailable") from None
    response.headers["Location"] = f"/analysis-batches/{result.id}"
    return result


@router.get("/{batch_id}", response_model=BatchView)
async def get_batch(
    batch_id: UUID,
    service: Annotated[BatchService, Depends(batch_service)],
) -> BatchView:
    return await _read(service, batch_id)


@router.post("/{batch_id}/cancel", response_model=BatchView)
async def cancel_batch(
    batch_id: UUID,
    service: Annotated[BatchService, Depends(batch_service)],
) -> BatchView:
    return await _read(service, batch_id, cancel=True)


async def _read(service: BatchService, batch_id: UUID, *, cancel: bool = False) -> BatchView:
    try:
        result = await service.get(batch_id, cancel=cancel)
    except AnalysisUnavailableError:
        raise HTTPException(503, detail="Batch storage unavailable") from None
    if result is None:
        raise HTTPException(404, detail="Batch not found")
    return result
