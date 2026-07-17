from fastapi import APIRouter

from app.core.version import get_version_info
from app.schemas import VersionOut

router = APIRouter()


@router.get("/version", response_model=VersionOut)
def version() -> VersionOut:
    return VersionOut(**get_version_info())
