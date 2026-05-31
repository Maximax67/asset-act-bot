"""Telegram webhook receive + management endpoints.

POST /webhook          – receive updates from Telegram
POST /webhook/setup    – register the webhook URL with Telegram (admin only)
POST /webhook/delete   – remove the webhook from Telegram (admin only)
"""

from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.logger import logger
from app.core.settings import settings
from bot.dispatcher import dp
from bot.instance import bot

router = APIRouter(prefix="/webhook", tags=["telegram"])


@router.post("")
async def handle_webhook(
    request: Request,
    x_telegram_token: str = Header(..., alias="X-Telegram-Bot-Api-Secret-Token"),
) -> Response:
    """Receive an update from Telegram and feed it to the dispatcher."""
    if (
        settings.WEBHOOK_SECRET
        and x_telegram_token != settings.WEBHOOK_SECRET.get_secret_value()
    ):
        logger.warning("Webhook received with invalid secret token")
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        raw = await request.json()
        update = Update.model_validate(raw)
    except Exception as exc:
        logger.error(f"Failed to parse Telegram update: {exc}")
        raise HTTPException(status_code=400, detail="Invalid update payload")

    try:
        await dp.feed_update(bot, update)
    except Exception as exc:
        logger.error(f"Dispatcher error while processing update: {exc}")
        # Always return 200 so Telegram does not retry the same update
    return Response(status_code=200)


def _require_management_token(authorization: str | None) -> None:
    """Raise 401 if management token is configured but the header is wrong."""
    if not settings.WEBHOOK_MANAGE_TOKEN:
        return
    expected = f"Bearer {settings.WEBHOOK_MANAGE_TOKEN.get_secret_value()}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/setup", status_code=200)
async def setup_webhook(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Register this app's URL as the Telegram webhook."""
    _require_management_token(authorization)

    if not settings.WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="WEBHOOK_URL is not configured")

    webhook_url = f"{str(settings.WEBHOOK_URL).rstrip('/')}/webhook"
    secret = (
        settings.WEBHOOK_SECRET.get_secret_value() if settings.WEBHOOK_SECRET else None
    )

    try:
        await bot.set_webhook(
            webhook_url,
            secret_token=secret,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=False,
        )
        logger.info(f"Webhook registered: {webhook_url}")
        return {"status": "ok", "detail": f"Webhook set to {webhook_url}"}
    except Exception as exc:
        logger.error(f"Failed to register webhook: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/delete", status_code=200)
async def delete_webhook(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Remove the Telegram webhook (fall back to polling)."""
    _require_management_token(authorization)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook removed successfully")
        return {"status": "ok", "detail": "Webhook removed; pending updates dropped"}
    except Exception as exc:
        logger.error(f"Failed to remove webhook: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
