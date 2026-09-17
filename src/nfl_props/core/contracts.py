"""Shared contracts used by every ingestion adapter."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

@dataclass
class IngestionResult:
    source: str
    dataset: str
    status: str  # success, skipped, failed
    files: list[Path] = field(default_factory=list)
    rows: int | None = None
    message: str = ""
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
