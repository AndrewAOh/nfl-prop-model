"""Environment-backed settings with safe defaults and no required secrets."""
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

class Settings(BaseModel):
    project_root: Path = PROJECT_ROOT
    environment: str = Field(default_factory=lambda: os.getenv("NFL_PROPS_ENV", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("NFL_PROPS_LOG_LEVEL", "INFO"))
    db_path: Path = Field(default_factory=lambda: PROJECT_ROOT / os.getenv("NFL_PROPS_DB_PATH", "db/nfl_props.duckdb"))
    request_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("NFL_PROPS_REQUEST_TIMEOUT_SECONDS", "60")))
    user_agent: str = Field(default_factory=lambda: os.getenv("NFL_PROPS_USER_AGENT", "nfl-prop-model/0.1"))

    @property
    def data_root(self) -> Path:
        return self.project_root / "data"

    @property
    def raw_root(self) -> Path:
        return self.data_root / "raw"

    @property
    def interim_root(self) -> Path:
        return self.data_root / "interim"

    @property
    def processed_root(self) -> Path:
        return self.data_root / "processed"

settings = Settings()
