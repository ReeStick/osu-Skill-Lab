from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from osu_skill_lab.api.analyses import _http_error
from osu_skill_lab.application.contracts import AnalysisRecord
from osu_skill_lab.application.mirror_import import MirrorImportService
from osu_skill_lab.application.service import (
    AnalysisBusyError,
    AnalysisInputError,
    AnalysisUnavailableError,
)
from osu_skill_lab.application.sources import MirrorError

router = APIRouter(prefix="/imports", tags=["imports"])


def mirror_import_service(request: Request) -> MirrorImportService:
    return cast(MirrorImportService, request.app.state.mirror_import)


@router.post(
    "/hinamizawa/{beatmap_id}",
    response_model=AnalysisRecord,
    status_code=201,
    responses={
        200: {"model": AnalysisRecord, "description": "Existing versioned result"},
        404: {"description": "Beatmap not found"},
        409: {"description": "Checksum unavailable or different"},
        422: {"description": "Unsupported or invalid input"},
        429: {"description": "Local capacity or source cooldown"},
        502: {"description": "Invalid source response"},
        503: {"description": "Source or persistence unavailable"},
        504: {"description": "Source timeout"},
    },
)
async def import_hinamizawa(
    beatmap_id: Annotated[int, Path(gt=0, le=10**12)],
    response: Response,
    service: Annotated[MirrorImportService, Depends(mirror_import_service)],
    expected_sha256: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$")] = None,
) -> AnalysisRecord:
    try:
        outcome = await service.import_id(beatmap_id, expected_sha256=expected_sha256)
    except (AnalysisInputError, AnalysisBusyError, AnalysisUnavailableError) as exc:
        raise _http_error(exc) from None
    except MirrorError as exc:
        status = {
            "mirror_not_found": 404,
            "mirror_checksum_unavailable": 409,
            "mirror_checksum_mismatch": 409,
            "mirror_unsupported_ruleset": 422,
            "mirror_unsupported_encoding": 422,
            "mirror_busy": 429,
            "mirror_rate_limited": 429,
            "mirror_unresolved": 503,
            "mirror_unavailable": 503,
            "mirror_timeout": 504,
        }.get(exc.code, 502)
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None,
        ) from None
    if not outcome.created:
        response.status_code = 200
    return outcome.record
