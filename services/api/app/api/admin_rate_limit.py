from fastapi import APIRouter, Depends

from app.auth import require_admin_token
from app.core.rate_limit import rate_limit_status
from app.schemas import RateLimitStatusOut

router = APIRouter(
    prefix="/admin/rate-limit", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/status", response_model=RateLimitStatusOut)
def rate_limit_status_endpoint():
    return rate_limit_status()
