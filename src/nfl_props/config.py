from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    raw_dir: Path
    processed_dir: Path
    odds_api_key: str | None = None
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    @classmethod
    def from_root(cls, root_dir: str | Path) -> "Settings":
        root = Path(root_dir).resolve()
        return cls(
            root_dir=root,
            raw_dir=root / "data" / "raw",
            processed_dir=root / "data" / "processed",
            odds_api_key=os.getenv("ODDS_API_KEY") or None,
            odds_api_base_url=os.getenv(
                "ODDS_API_BASE_URL", "https://api.the-odds-api.com/v4"
            ),
        )

    def ensure_directories(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
