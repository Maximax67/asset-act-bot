from fastapi import APIRouter

from app.core.settings import settings
from app.routes import webhook

router = APIRouter()


@router.get("/", tags=["root"])
def info() -> dict[str, str]:
    return {"title": settings.APP_TITLE, "version": settings.APP_VERSION}


@router.get("/health", tags=["root"])
def health() -> dict[str, str]:
    return {"status": "ok"}


router.include_router(webhook.router)
