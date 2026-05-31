"""Generate output file names from the configured pattern."""

from datetime import datetime

from app.core.settings import settings


def generate_file_name(dept_code: str) -> str:
    """Return a file name (without extension) using FILE_NAME_PATTERN.

    Supported placeholders:
      {date}     — today formatted as "YYYY MM DD HH:MM"
      {deptname} — department code from the Departments sheet
    """
    date_str = datetime.now().strftime("%Y %m %d %H:%M")
    return settings.FILE_NAME_PATTERN.format(date=date_str, deptname=dept_code)
