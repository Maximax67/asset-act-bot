import asyncio

from app.core.logger import logger
from app.core.settings import settings
from bot.dispatcher import dp
from bot.instance import bot
from bot.utils.commands import set_chat_commands


async def main() -> None:
    logger.info(f"Starting {settings.APP_TITLE} v{settings.APP_VERSION} in polling mode")

    if settings.WEBHOOK_URL:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Removed existing webhook; switching to polling")

    await set_chat_commands()
    logger.info("Bot commands registered; starting long-polling…")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


if __name__ == "__main__":
    asyncio.run(main())
