import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core.settings import settings
from bot.utils.asset_pipeline import (
    OwnerResult,
    PipelineResult,
    format_owner_row,
    format_pipeline_summary,
    run_asset_generation,
)
from bot.utils.commands import set_chat_commands

logger = logging.getLogger(__name__)
router = Router()

# Only allow commands from the configured admin chat
ADMIN_FILTER = F.chat.id == settings.ADMIN_CHAT_ID

# Prevent concurrent generation runs
_generation_lock = asyncio.Lock()


@router.message(Command("start"), ADMIN_FILTER)
async def start_handler(message: Message) -> None:
    await set_chat_commands()
    await message.answer(
        "🏢 <b>Бот генерації актів</b>\n\n"
        "<b>Команди:</b>\n"
        "/generate_asset — Запустити процес генерації актів\n"
        "/help — Показати довідку"
    )


@router.message(Command("help"), ADMIN_FILTER)
async def help_handler(message: Message) -> None:
    await message.answer(
        "🏢 <b>Бот генерації актів</b>\n\n"
        "<b>Як це працює:</b>\n"
        '1. Зчитує у гугл таблиці рядки, де стоїть птичка у стовпці "На генерацію"\n'
        "2. Зчитує аркуш з підрозділи для отримання метаданих власників\n"
        "3. Групує активи за кодом власника\n"
        "4. Для кожного власника викликає API генератора документів"
        "5. Завантажує згенерований файл на Google Диск та дублює в телеграм\n\n"
        "<b>Команди:</b>\n"
        "/generate_asset — Запустити процес генерації\n"
        "/help — Показати це повідомлення"
    )


@router.message(Command("generate_asset"), ADMIN_FILTER)
async def generate_asset_handler(message: Message) -> None:
    """Trigger the full asset generation pipeline."""

    # Prevent two simultaneous runs
    if _generation_lock.locked():
        logger.warning(f"Generation is already in progress, chat_id={message.chat.id}")
        await message.answer(
            "⚠️ <b>Процес генерації вже триває.</b>\n"
            "Будь ласка, зачекайте на його завершення, перш ніж запускати новий."
        )
        return

    logger.info(f"Generation triggered by chat_id={message.chat.id}")
    processed: list[OwnerResult] = []
    status_msg = await message.answer("⏳ <b>Зчитування Google Таблиць…</b>")

    async def on_progress(result: OwnerResult) -> None:
        """Called after each owner is processed; rebuilds the full stacked list."""
        processed.append(result)
        done = sum(1 for r in processed if r.success)
        failed = sum(1 for r in processed if not r.success)

        lines = [
            f"⏳ <b>Обробка підрозділів…</b>",
            f"✅ Успішно: {done}   ❌ Помилок: {failed}",
            "",
        ]
        for r in processed:
            lines.append(format_owner_row(r, settings.ADMIN_CHAT_ID))

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3990] + "\n…<i>(обрізано)</i>"

        try:
            await status_msg.edit_text(text)
        except Exception:
            # "Message is not modified" or flood-wait — silently ignore
            pass

    async with _generation_lock:
        try:
            pipeline_result: PipelineResult = await run_asset_generation(
                on_progress=on_progress
            )

            summary = format_pipeline_summary(
                pipeline_result, chat_id=settings.ADMIN_CHAT_ID
            )
            await status_msg.edit_text(summary)

            logger.info(
                f"Generation complete: {pipeline_result.successful}/{pipeline_result.total} owners succeeded"
            )
        except RuntimeError as exc:
            text = f"❌ <b>Помилка конфігурації або API</b>\n\n<code>{exc}</code>"
            logger.error(f"Runtime error: {exc}")
            await status_msg.edit_text(text)
        except Exception as exc:
            text = f"❌ <b>Непередбачувана помилка</b>\n\n<code>{exc}</code>"
            logger.exception(f"Unhandled exception in generation pipeline: {exc}")
            await status_msg.edit_text(text)


@router.message(Command("start", "help", "generate_asset"))
async def unauthorized_handler(message: Message) -> None:
    logger.warning(
        f"Unauthorized command '{message.text}' from chat_id={message.chat.id} "
        f"user_id={message.from_user.id if message.from_user else 'unknown'}"
    )
    await message.answer(
        "⛔ [EN]: You are not authorised to use this bot. [UK]: У вас немає прав для використання цього бота."
    )
