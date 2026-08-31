"""Application settings.

Everything that differs between machines lives here and is read from the
environment (or ``.env``).  Nothing in this module may import from ``app.db``
or ``app.models`` — it is the lowest layer.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(API_ROOT / ".env", REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Trellis"
    environment: Literal["local", "test", "production"] = "local"
    debug: bool = True

    database_url: str = "postgresql+psycopg://localhost:5432/opportunity_agent"
    test_database_url: str = "postgresql+psycopg://localhost:5432/opportunity_agent_test"

    # --- CORS -------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Chrome extensions call the import endpoint with a chrome-extension:// origin.
    allow_extension_origins: bool = True

    # --- Storage ----------------------------------------------------------
    # Resumes are deliberately stored OUTSIDE any web-served static directory
    # and are only reachable through an authorised API route (see docs/privacy.md).
    storage_dir: Path = API_ROOT / "storage"
    max_resume_bytes: int = 10 * 1024 * 1024

    # --- Secrets ----------------------------------------------------------
    # Fernet key used to encrypt at-rest secrets (never third-party passwords —
    # we do not store those at all).  Generated on first run if unset.
    secret_key_file: Path = API_ROOT / ".secret_key"

    # --- LLM --------------------------------------------------------------
    llm_provider: Literal["auto", "anthropic", "deterministic"] = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    llm_max_output_tokens: int = 4096
    llm_timeout_seconds: float = 90.0

    # --- Fetching ---------------------------------------------------------
    user_agent: str = (
        "TrellisOpportunityAgent/0.1 (+personal student research assistant; "
        "contact: set FETCH_CONTACT_EMAIL)"
    )
    fetch_contact_email: str | None = None
    fetch_timeout_seconds: float = 30.0
    fetch_max_bytes: int = 4 * 1024 * 1024
    respect_robots_txt: bool = True
    polite_delay_seconds: float = 1.0

    # --- Agent behaviour --------------------------------------------------
    default_university: str = "Stanford University"
    recency_window_months: int = 24
    strong_recency_window_months: int = 12

    # --- Reminders --------------------------------------------------------
    default_reminder_offsets_days: list[int] = Field(default_factory=lambda: [7, 3, 1])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def resume_dir(self) -> Path:
        return self.storage_dir / "resumes"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.resume_dir.mkdir(parents=True, exist_ok=True)
    return settings
