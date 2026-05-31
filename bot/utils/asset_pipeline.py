import asyncio
from html import escape
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from aiogram.types import BufferedInputFile, Message

from app.core.settings import settings
from bot.instance import bot
from bot.utils.data_processing import load_departments, parse_assets
from bot.utils.doc_api_client import DocApiError, generate_document
from bot.utils.drive_uploader import upload_bytes_to_drive
from bot.utils.file_naming import generate_file_name
from bot.utils.formatters import fmt_number
from bot.utils.google_sheets import (
    build_google_services,
    ensure_file_is_spreadsheet,
)
from bot.utils.template_vars import build_variables_for_owner

logger = logging.getLogger(__name__)


@dataclass
class OwnerResult:
    """Outcome of processing one owner (department)."""

    code: str
    file_name: str
    success: bool
    items_count: int = 0
    total_sum: Decimal = field(default_factory=lambda: Decimal("0.00"))
    extension: str = ""
    drive_file_id: Optional[str] = None
    drive_skipped: bool = False
    tg_message_id: Optional[int] = None
    tg_thread_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """Aggregate outcome of the full generation run."""

    owner_results: list[OwnerResult]
    stats: dict[str, Any]

    @property
    def total(self) -> int:
        return len(self.owner_results)

    @property
    def successful(self) -> int:
        return sum(1 for r in self.owner_results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.owner_results if not r.success)

    @property
    def drive_uploaded(self) -> int:
        return sum(1 for r in self.owner_results if r.success and r.drive_file_id)


# Type alias for the progress callback
ProgressCallback = Callable[[OwnerResult], Awaitable[None]]


def _tg_msg_url(chat_id: int, message_id: int, thread_id: Optional[int] = None) -> str:
    """Build a t.me/c deep-link for a message in a private supergroup/channel.

    Supergroup chat IDs are stored as ``-100XXXXXXXXX``; the t.me/c/ format
    expects only the numeric portion without the ``-100`` prefix.
    """
    peer_id = str(abs(chat_id))
    if peer_id.startswith("100") and len(peer_id) > 3:
        peer_id = peer_id[3:]
    if thread_id:
        return f"https://t.me/c/{peer_id}/{thread_id}/{message_id}"
    return f"https://t.me/c/{peer_id}/{message_id}"


def format_owner_row(r: OwnerResult, chat_id: int = settings.ADMIN_CHAT_ID) -> str:
    """Format a single :class:`OwnerResult` as 1–2 lines of Telegram HTML.

    Successful row example::

        ✅ <СР КПІ> — Диск, Телеграм

    Failed row example::

        ❌ <СР КПІ>
        Doc API HTTP 400: …
    """

    if r.success:
        links: list[str] = []
        if r.drive_file_id:
            links.append(
                f'<a href="https://drive.google.com/file/d/{r.drive_file_id}">Диск</a>'
            )
        if r.tg_message_id:
            url = _tg_msg_url(chat_id, r.tg_message_id, r.tg_thread_id)
            links.append(f'<a href="{url}">Телеграм</a>')

        row = f"✅ <code>{escape(r.code)}</code>"
        if links:
            row += " — " + ", ".join(links)
        return row
    elif r.error:
        return f"❌ <code>{escape(r.code)}</code>:\n<code>{escape(r.error[:120])}</code>"
    else:
        return f"❌ <code>{escape(r.code)}</code>: невідома помилка"


async def run_asset_generation(
    on_progress: Optional[ProgressCallback] = None,
) -> PipelineResult:
    """Execute the full asset act generation pipeline.

    Pipeline steps:
    1. Validate environment config
    2. Authenticate with Google APIs (thread)
    3. Verify both spreadsheets are accessible (thread)
    4. Load departments (thread)
    5. Parse assets from the Assets sheet (thread)
    6. For each owner:
       a. Build template variables
       b. Call document generator API (async HTTP)
       c. Send document via Telegram
       d. Upload to Google Drive (thread)
       e. Invoke on_progress callback

    Args:
        on_progress: Optional async callable invoked after every owner is
                     processed.  Receives an OwnerResult; exceptions are caught
                     and logged so they never abort the pipeline.

    Returns:
        PipelineResult containing per-owner results and aggregate statistics.

    Raises:
        RuntimeError: if Google API setup or spreadsheet verification fails
    """
    logger.info("Asset generation pipeline starting")

    sheets_svc, drive_svc = await asyncio.to_thread(build_google_services)

    await asyncio.to_thread(
        ensure_file_is_spreadsheet,
        drive_svc,
        settings.ASSETS_SHEET_ID,
        "Assets spreadsheet",
    )
    await asyncio.to_thread(
        ensure_file_is_spreadsheet,
        drive_svc,
        settings.DEPARTMENTS_SHEET_ID,
        "Departments spreadsheet",
    )

    departments = await asyncio.to_thread(load_departments, sheets_svc)
    if not departments:
        raise RuntimeError(
            "No departments could be loaded from the Departments sheet. "
            "Check the sheet ID, sheet name and service account access."
        )

    per_owner, stats = await asyncio.to_thread(parse_assets, sheets_svc, departments)

    if not per_owner:
        logger.info(
            "No valid owners after parsing — pipeline complete with zero documents"
        )
        return PipelineResult(owner_results=[], stats=stats)

    logger.info(f"Generating documents for {len(per_owner)} owner(s)")

    results: list[OwnerResult] = []

    for code, data in per_owner.items():
        result = await _process_single_owner(code, data, drive_svc)
        results.append(result)

        if on_progress:
            try:
                await on_progress(result)
            except Exception as cb_exc:
                logger.warning(f"Progress callback raised an exception: {cb_exc}")

    pipeline_result = PipelineResult(owner_results=results, stats=stats)
    logger.info(
        f"Pipeline complete — owners: {pipeline_result.successful} ok / "
        f"{pipeline_result.failed} failed / {pipeline_result.total} total | "
        f"rows_processed={stats.get('rows_processed', 0)} | "
        f"total_items={stats.get('total_items_in_acts', 0)} | "
        f"total_value={fmt_number(stats.get('total_value_generated', Decimal('0')))}"
    )

    return pipeline_result


async def _process_single_owner(
    code: str,
    data: dict[str, Any],
    drive_svc: Any,
) -> OwnerResult:
    """Handle one owner: generate document → send via Telegram → upload to Drive.

    Errors at any step are caught and surfaced in the OwnerResult rather than
    propagating, so a single failure does not abort the whole pipeline.
    """
    dept = data["dept"]
    file_name = generate_file_name(dept.get("code", code))
    items_count = len(data.get("items", []))
    total_sum: Decimal = data.get("tot_sum", Decimal("0.00"))

    logger.info(
        f"Owner '{code}': {items_count} item(s), "
        f"sum={fmt_number(total_sum)}, file='{file_name}'"
    )

    # --- Build template variables (pure, sync, cheap) ---
    try:
        variables = build_variables_for_owner(data, dept)
    except Exception as exc:
        logger.error(f"Owner '{code}': failed to build template variables: {exc}")
        return OwnerResult(
            code=code,
            file_name=file_name,
            success=False,
            items_count=items_count,
            total_sum=total_sum,
            error=f"Variable build error: {exc}",
        )

    # --- Call document generator API (async HTTP) ---
    try:
        doc_bytes, extension = await generate_document(variables)
        logger.info(
            f"Owner '{code}': document generated — "
            f"{len(doc_bytes):,} bytes, extension='{extension}'"
        )
    except DocApiError as exc:
        logger.error(f"Owner '{code}': document API error — {exc}")
        return OwnerResult(
            code=code,
            file_name=file_name,
            success=False,
            items_count=items_count,
            total_sum=total_sum,
            error=str(exc),
        )
    except Exception as exc:
        logger.error(f"Owner '{code}': unexpected error calling document API — {exc}")
        return OwnerResult(
            code=code,
            file_name=file_name,
            success=False,
            items_count=items_count,
            total_sum=total_sum,
            error=f"Network/API error: {exc}",
        )

    # --- Send document via Telegram ---
    tg_message_id: Optional[int] = None
    tg_thread_id: Optional[int] = None
    try:
        sent: Message = await bot.send_document(
            settings.ADMIN_CHAT_ID,
            BufferedInputFile(doc_bytes, filename=f"{file_name}{extension}"),
            message_thread_id=settings.MESSAGE_THREAD_ID,
        )
        tg_message_id = sent.message_id
        tg_thread_id = sent.message_thread_id
    except Exception as exc:
        logger.error(f"'{code}': telegram file upload failed — {exc}")
        return OwnerResult(
            code=code,
            file_name=file_name,
            extension=extension,
            success=False,
            items_count=items_count,
            total_sum=total_sum,
            error=f"Telegram upload error: {exc}",
        )

    # --- Upload to Google Drive (sync → thread) ---
    drive_file_id: Optional[str] = None
    drive_skipped = False

    if not settings.SHARED_DRIVE_ID:
        drive_skipped = True
        logger.info(f"Owner '{code}': Drive upload skipped (SHARED_DRIVE_ID not set)")
    else:
        try:
            drive_file_id = await asyncio.to_thread(
                upload_bytes_to_drive, drive_svc, doc_bytes, file_name, extension
            )
        except RuntimeError as exc:
            logger.error(f"Owner '{code}': Drive upload failed — {exc}")
            return OwnerResult(
                code=code,
                file_name=file_name,
                extension=extension,
                success=False,
                items_count=items_count,
                total_sum=total_sum,
                tg_message_id=tg_message_id,
                tg_thread_id=tg_thread_id,
                error=str(exc),
            )

    return OwnerResult(
        code=code,
        file_name=file_name,
        extension=extension,
        success=True,
        items_count=items_count,
        total_sum=total_sum,
        drive_file_id=drive_file_id,
        drive_skipped=drive_skipped,
        tg_message_id=tg_message_id,
        tg_thread_id=tg_thread_id,
    )


def format_pipeline_summary(
    result: PipelineResult,
    chat_id: int = settings.ADMIN_CHAT_ID,
) -> str:
    """Return a Telegram HTML message summarising the pipeline outcome.

    Shows aggregate stats followed by one row per owner (success and failure),
    using the same :func:`format_owner_row` format as the live progress view.
    """
    stats = result.stats
    total_value: Decimal = stats.get("total_value_generated", Decimal("0.00"))

    if not result.owner_results:
        return (
            "✅ <b>Генерацію завершено</b>\n\n"
            "ℹ️ Не знайдено підрозділів до генерації.\n\n"
            f"📊 Оброблено рядків: {stats.get('rows_processed', 0)}\n"
            f"⏭️ Пропущено рядків: {stats.get('rows_skipped', 0)}"
        )

    # --- Header ---
    status_line = f"✅ Успішно: <b>{result.successful} / {result.total}</b>"
    if result.failed:
        status_line += f"   ❌ Помилок: <b>{result.failed} / {result.total}</b>"

    lines: list[str] = [
        "📋 <b>Генерацію завершено</b>",
        "",
        status_line,
    ]

    if result.drive_uploaded:
        lines.append(f"☁️ Завантажено на Диск: <b>{result.drive_uploaded}</b>")

    # --- Aggregate stats ---
    lines += [
        "",
        f"📦 Всього позицій: <b>{stats.get('total_items_in_acts', 0)}</b>",
        f"💰 Загальна сума: <b>{fmt_number(total_value)}</b>",
        "",
        f"📊 Оброблено рядків: {stats.get('rows_processed', 0)}",
        f"⏭️ Пропущено рядків: {stats.get('rows_skipped', 0)}",
        f"👤 Пропущено підрозділів: {stats.get('owners_skipped', 0)}",
        "",
    ]

    # --- Per-owner rows (all results, success and failure) ---
    for r in result.owner_results:
        lines.append(format_owner_row(r, chat_id))

    text = "\n".join(lines)
    # Telegram message cap is 4096 chars; trim gracefully
    if len(text) > 4000:
        text = text[:3990] + "\n\n…<i>(обрізано)</i>"
    return text
