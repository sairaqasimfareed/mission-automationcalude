import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_dry_run() -> bool:
    """Development and tests default to dry run (no real provider is ever called by accident). The
    INSTALLED app is the real product: with no .env beside it, it used to start in dry run, ignore
    every provider the operator added and answer from the placeholder (found live, 2026-10-16), so a
    packaged build defaults to real. MISSION_AUTOMATION_DRY_RUN in the environment or .env wins.
    """

    return not getattr(sys, "frozen", False)


class Settings(BaseSettings):
    # API Keys
    OPENAI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""

    # Application
    APP_NAME: str = "Mission Automation"
    APP_VERSION: str = "1.0.0"

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    MISSION_AUTOMATION_DRY_RUN: bool = default_dry_run()

    # Rendering
    DEFAULT_RENDER_ENGINE: str = "ffmpeg"

    # Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
