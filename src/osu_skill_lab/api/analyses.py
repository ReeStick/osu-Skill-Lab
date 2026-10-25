"""HTTP transport for transient .osu analysis and stored scalar results."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from osu_skill_lab.api.dependencies import get_analysis_service
from osu_skill_lab.application.contracts import AnalysisPage, AnalysisRecord
from osu_skill_lab.application.service import (
    AnalysisBusyError,
    AnalysisInputError,
    AnalysisService,
    AnalysisUnavailableError,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])
AnalysisDependency = Annotated[AnalysisService, Depends(get_analysis_service)]
_BIGINT_MAX = 2**63 - 1


def _http_error(
    error: AnalysisInputError | AnalysisBusyError | AnalysisUnavailableError,
) -> HTTPException:
    if isinstance(error, AnalysisInputError):
        return HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
                if error.code == "file_too_large"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail={
                "code": error.code,
                "message": error.message,
                "section": error.section,
                "line_number": error.line_number,
            },
        )
    if isinstance(error, AnalysisBusyError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Analysis capacity is temporarily full",
            headers={"Retry-After": "1"},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Analysis service unavailable",
    )


@router.post(
    "",
    response_model=AnalysisRecord,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "model": AnalysisRecord,
            "description": "An identical versioned analysis already exists",
        },
        413: {"description": "Input exceeds the configured byte limit"},
        415: {"description": "Expected raw .osu bytes"},
        422: {"description": "Unsupported or invalid analytical .osu input"},
        429: {"description": "Analysis capacity is temporarily full"},
        503: {"description": "Analysis service unavailable"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
                "text/plain": {"schema": {"type": "string", "format": "binary"}},
            },
        },
    },
)
async def create_analysis(
    request: Request,
    response: Response,
    service: AnalysisDependency,
) -> AnalysisRecord:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"", "application/octet-stream", "text/plain"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Send raw .osu bytes as application/octet-stream or text/plain",
        )
    try:
        outcome = await service.analyze_stream(request.stream())
    except (AnalysisInputError, AnalysisBusyError, AnalysisUnavailableError) as exc:
        raise _http_error(exc) from None
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    return outcome.record


@router.get(
    "", response_model=AnalysisPage, responses={503: {"description": "Service unavailable"}}
)
async def list_analyses(
    service: AnalysisDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after_id: Annotated[int, Query(ge=0, le=_BIGINT_MAX)] = 0,
    claimed_beatmap_id: Annotated[int | None, Query(gt=0, le=_BIGINT_MAX)] = None,
) -> AnalysisPage:
    try:
        return await service.list_analyses(
            limit=limit,
            after_id=after_id,
            claimed_beatmap_id=claimed_beatmap_id,
        )
    except (AnalysisInputError, AnalysisBusyError, AnalysisUnavailableError) as exc:
        raise _http_error(exc) from None


@router.get(
    "/{analysis_id}",
    response_model=AnalysisRecord,
    responses={
        404: {"description": "Analysis not found"},
        503: {"description": "Service unavailable"},
    },
)
async def get_analysis(
    analysis_id: Annotated[int, Path(gt=0, le=_BIGINT_MAX)],
    service: AnalysisDependency,
) -> AnalysisRecord:
    try:
        record = await service.get_analysis(analysis_id)
    except (AnalysisInputError, AnalysisBusyError, AnalysisUnavailableError) as exc:
        raise _http_error(exc) from None
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return record
