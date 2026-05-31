import logging
from typing import Any

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)


class DocApiError(Exception):
    """Raised when the document generator API returns a non-200 response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Doc API HTTP {status_code}: {detail}")


async def generate_document(variables: dict[str, Any]) -> tuple[bytes, str]:
    """Call the document generator API and return the file bytes + extension.

    Args:
        variables: The variables dict to render into the template.

    Returns:
        Tuple of (file_bytes, extension) e.g. (b"...", ".docx")

    Raises:
        DocApiError: on known API error status codes (400, 403, 404, 413, 422)
        httpx.RequestError: on network / timeout errors
    """
    base = settings.DOC_GENERATOR_BASE_URL.rstrip("/")
    url = f"{base}/api/drive/documents/{settings.DOCUMENT_ID}/generate"
    params = {"format": settings.DOC_FORMAT}

    headers: dict[str, str] = {"Accept": "application/octet-stream"}
    payload: dict[str, Any] = {
        "variables": variables,
        "bypass_validation": False,
    }

    logger.debug(
        f"POST {url} | format={settings.DOC_FORMAT} | "
        f"variables_keys={list(variables.keys())}"
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, params=params, headers=headers)

    logger.debug(
        f"Doc API response: status={response.status_code} "
        f"content-type={response.headers.get('content-type', '?')} "
        f"size={len(response.content)} bytes"
    )

    if response.status_code == 200:
        content_type = response.headers.get("content-type", "")
        extension = ".pdf" if "pdf" in content_type else ".docx"
        logger.info(
            f"Document generated successfully: {len(response.content)} bytes, ext={extension}"
        )
        return response.content, extension

    # Parse error body
    try:
        err_body: dict[str, Any] = response.json()
    except Exception:
        err_body = {"detail": response.text[:500]}

    status = response.status_code
    if status == 400:
        errors = err_body.get("errors", err_body)
        raise DocApiError(400, f"Validation errors: {errors}")

    detail = err_body.get("detail", response.text[:200])
    raise DocApiError(status, str(detail))
