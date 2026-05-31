import logging
from io import BytesIO
from typing import Any, Optional

from googleapiclient.errors import HttpError  # type: ignore[import-untyped]
from googleapiclient.http import MediaIoBaseUpload  # type: ignore[import-untyped]

from app.core.settings import settings

logger = logging.getLogger(__name__)

_MIME_TYPES: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}


def upload_bytes_to_drive(
    drive_svc: Any,
    file_bytes: bytes,
    file_name: str,
    extension: str = ".docx",
) -> Optional[str]:
    """Upload *file_bytes* to the configured Google Drive folder.

    Args:
        drive_svc: Google Drive API v3 service object
        file_bytes: Raw file content
        file_name: Desired file name **without** extension
        extension: File extension including the leading dot (e.g. '.docx')

    Returns:
        The Drive file ID on success, or None if SHARED_DRIVE_ID is not set.

    Raises:
        RuntimeError: if the Drive API call fails
    """
    if not settings.SHARED_DRIVE_ID:
        logger.warning("SHARED_DRIVE_ID is not configured; Drive upload skipped")
        return None

    mime_type = _MIME_TYPES.get(extension, _MIME_TYPES[".docx"])
    full_name = f"{file_name}{extension}"

    logger.info(
        f"Uploading '{full_name}' ({len(file_bytes):,} bytes) "
        f"to Drive folder/drive '{settings.SHARED_DRIVE_ID}'"
    )

    try:
        media = MediaIoBaseUpload(
            BytesIO(file_bytes),
            mimetype=mime_type,
            resumable=False,
        )
        file_metadata = {
            "name": full_name,
            "parents": [settings.SHARED_DRIVE_ID],
        }
        result = (
            drive_svc.files()
            .create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id,name,webViewLink",
            )
            .execute()
        )
        file_id: str = result.get("id", "")
        link: str = result.get("webViewLink", "")
        logger.info(
            f"Uploaded '{full_name}' → Drive id={file_id}"
            + (f" link={link}" if link else "")
        )
        return file_id

    except HttpError as exc:
        raise RuntimeError(
            f"Google Drive upload failed for '{full_name}': {exc}"
        ) from exc
