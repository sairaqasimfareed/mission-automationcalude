from pydantic_settings import BaseSettings, SettingsConfigDict


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
    MISSION_AUTOMATION_DRY_RUN: bool = True

    # Rendering
    DEFAULT_RENDER_ENGINE: str = "ffmpeg"

    # Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
