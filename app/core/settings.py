from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    ADMIN_CHAT_ID: int
    MESSAGE_THREAD_ID: int | None = None

    MODE: str = "webhook"
    WEBHOOK_URL: HttpUrl | None = None
    WEBHOOK_SECRET: SecretStr | None = None
    WEBHOOK_MANAGE_TOKEN: SecretStr | None = None

    GOOGLE_CLIENT_EMAIL: SecretStr
    GOOGLE_PRIVATE_KEY: SecretStr
    GOOGLE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"

    ASSETS_SHEET_ID: str
    ASSETS_SHEET_NAME: str = ""
    DEPARTMENTS_SHEET_ID: str
    DEPARTMENTS_SHEET_NAME: str = ""

    SHARED_DRIVE_ID: str = ""

    DOC_GENERATOR_BASE_URL: str
    DOCUMENT_ID: str
    DOC_FORMAT: str = "docx"

    # Supports {date} and {deptname} format placeholders
    FILE_NAME_PATTERN: str = "{date} Акт. {deptname}"

    THOUSAND_SEPARATOR: str = " "
    DECIMAL_SEPARATOR: str = ","
    CURRENCY_SUFFIX: str = ""
    ALLOW_ROUNDING_ADJUST: bool = True

    APP_TITLE: str = "Asset Act Bot"
    APP_VERSION: str = "1.0.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Allow extra env vars without raising validation errors
        extra="ignore",
    )


settings = Settings(**{})
