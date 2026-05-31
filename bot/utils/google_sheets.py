import logging
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from app.core.settings import settings

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def build_google_services() -> tuple[Any, Any]:
    """Authenticate with the service account and return (sheets_svc, drive_svc).

    Raises:
        FileNotFoundError: if credentials file is missing
        google.auth.exceptions.* : on auth failure
    """
    creds = service_account.Credentials.from_service_account_info(
        {
            "client_email": settings.GOOGLE_CLIENT_EMAIL.get_secret_value(),
            "private_key": settings.GOOGLE_PRIVATE_KEY.get_secret_value().replace(
                "\\n", "\n"
            ),
            "token_uri": settings.GOOGLE_TOKEN_URI,
        },
        scopes=_SCOPES,
    )  # type: ignore[no-untyped-call]
    sheets_svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive_svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    logger.info("Google API services authenticated successfully")
    return sheets_svc, drive_svc


def ensure_file_is_spreadsheet(drive_svc: Any, file_id: str, label: str) -> None:
    """Assert that file_id is an accessible Google Spreadsheet.

    Raises:
        RuntimeError: if the file cannot be fetched or is not a spreadsheet
    """
    try:
        meta = (
            drive_svc.files()
            .get(
                fileId=file_id,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(f"Cannot access {label} (id={file_id}): {exc}") from exc

    mime = meta.get("mimeType", "")
    if mime != "application/vnd.google-apps.spreadsheet":
        raise RuntimeError(
            f"{label} (id={file_id}) has unexpected MIME type '{mime}'. "
            "Check that the ID points to a Google Spreadsheet."
        )
    logger.info(f"{label} verified: '{meta.get('name', '<untitled>')}' (id={file_id})")


def read_sheet_values(
    sheets_svc: Any, spreadsheet_id: str, sheet_name: str
) -> list[list[Any]]:
    """Read all cell values from a sheet.

    Args:
        sheets_svc: Google Sheets API service
        spreadsheet_id: ID of the Google Spreadsheet
        sheet_name: Sheet tab name (empty string → first/default sheet)

    Returns:
        List of rows; each row is a list of cell values (strings from the API)

    Raises:
        RuntimeError: on API errors
    """
    range_str = sheet_name if sheet_name else ""
    try:
        response = (
            sheets_svc.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_str)
            .execute()
        )
        rows: list[list[Any]] = response.get("values", [])
        logger.debug(
            f"Read {len(rows)} rows from spreadsheet={spreadsheet_id} range='{range_str}'"
        )
        return rows
    except HttpError as exc:
        msg = str(exc)
        if "not supported for this document" in msg:
            raise RuntimeError(
                f"File {spreadsheet_id} cannot be read as a Spreadsheet. "
                "Ensure the service account has Viewer access and the ID is correct."
            ) from exc
        raise RuntimeError(
            f"Sheets API error — spreadsheet={spreadsheet_id} range='{range_str}': {exc}"
        ) from exc
