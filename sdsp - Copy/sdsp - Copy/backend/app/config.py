"""Application settings loaded from environment variables or a .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for every subsystem of the platform."""

    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parents[2] / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ),
        extra="ignore",
    )

    database_url: str = "sqlite:///./data/app.db"
    redis_url: str | None = None
    demo_mode: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    model_dir: Path = Path("./models")
    public_base_url: str = "http://localhost:8000"

    youtube_api_key: str | None = None
    instagram_access_token: str | None = None
    instagram_app_secret: str | None = None
    instagram_verify_token: str = "change-me"
    poll_interval_minutes: int = 15

    embedding_backend: str = "hash"
    visual_backend: str = "basic"
    asr_backend: str = "none"

    llm_backend: str = "openai"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    underperformance_ratio: float = 0.5
    underperformance_min_hours: float = 2.0
    comment_surge_z: float = 3.0
    comment_surge_min_new: int = 10
    event_cooldown_hours: float = 6.0
    grounding_threshold: float = 0.8


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
