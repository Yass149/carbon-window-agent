"""Environment configuration; paid providers require an explicit opt-in."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    """Runtime defaults keep the application usable without a model API key."""

    model_config = ConfigDict(extra="forbid")
    provider: Literal["demo", "anthropic"] = "demo"
    model: str = "claude-haiku-4-5-20251001"
    db_path: str = "data/cwa.sqlite3"
    allow_paid_api: bool = False
    anthropic_api_key: SecretStr = SecretStr("")
    max_output_tokens: int = Field(default=1024, ge=128, le=4096)

    @classmethod
    def from_env(cls) -> "Settings":
        """Read environment variables without loading or logging secret files."""
        return cls.model_validate(
            {
                "provider": os.getenv("PROVIDER", "demo"),
                "model": os.getenv("MODEL", "claude-haiku-4-5-20251001"),
                "db_path": os.getenv("DB_PATH", "data/cwa.sqlite3"),
                "allow_paid_api": os.getenv("ALLOW_PAID_API", "false"),
                "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
                "max_output_tokens": os.getenv("MAX_OUTPUT_TOKENS", "1024"),
            }
        )
