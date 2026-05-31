from aiogram.types import BotCommand, BotCommandScopeChat

from app.core.settings import settings
from bot.instance import bot

_COMMANDS = [
    BotCommand(
        command="generate_asset", description="Запустити процес генерації актів"
    ),
    BotCommand(command="help", description="Показати довідку"),
]


async def set_chat_commands() -> None:
    """Register commands scoped to the admin chat so they appear in the menu."""
    await bot.set_my_commands(
        commands=_COMMANDS,
        scope=BotCommandScopeChat(chat_id=settings.ADMIN_CHAT_ID),
    )
