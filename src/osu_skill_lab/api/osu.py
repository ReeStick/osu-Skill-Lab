from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from osu_skill_lab.application.contracts import AnalysisRecord
from osu_skill_lab.application.osu_metadata import OsuApiError
from osu_skill_lab.application.osu_verification import OsuVerificationService
from osu_skill_lab.application.service import AnalysisUnavailableError

router = APIRouter(tags=["osu"])


def verification_service(request: Request) -> OsuVerificationService:
    return cast(OsuVerificationService, request.app.state.osu_verification)


@router.post(
    "/analyses/{analysis_id}/verify-osu",
    response_model=AnalysisRecord,
    responses={
        404: {"description": "Analysis or matching upstream beatmap not found"},
        409: {"description": "Checksum missing or different"},
        422: {"description": "Invalid ID or unsupported ruleset"},
        429: {"description": "Verification capacity or upstream rate limit reached"},
        502: {"description": "Invalid or unavailable upstream response"},
        503: {"description": "Credentials or persistence unavailable"},
        504: {"description": "Upstream timeout"},
    },
)
async def verify_osu(
    analysis_id: Annotated[int, Path(gt=0, le=2**63 - 1)],
    service: Annotated[OsuVerificationService, Depends(verification_service)],
) -> AnalysisRecord:
    try:
        return await service.verify(analysis_id)
    except AnalysisUnavailableError:
        raise HTTPException(status_code=503, detail="Analysis storage unavailable") from None
    except OsuApiError as exc:
        status_code = {
            "analysis_not_found": 404,
            "osu_not_found": 404,
            "osu_checksum_mismatch": 409,
            "osu_checksum_unavailable": 409,
            "osu_unsupported_ruleset": 422,
            "osu_busy": 429,
            "osu_rate_limited": 429,
            "osu_not_configured": 503,
            "osu_auth_failed": 503,
            "osu_storage_unavailable": 503,
            "osu_timeout": 504,
        }.get(exc.code, 502)
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None,
        ) from None
