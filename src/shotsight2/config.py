"""Environment-backed application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load local runtime settings from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SHOTSIGHT_", extra="ignore")

    env: str = "development"
    host: str = "127.0.0.1"
    port: int = 4173
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/database/shotsight2.db"
    max_upload_bytes: int = 1_073_741_824
    max_video_minutes: int = 30
    default_language: str = "en"
    enable_sam3: bool = False
    sam3_model_path: Path | None = None


settings = Settings()

