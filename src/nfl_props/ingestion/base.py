"""Base adapter with consistent failure behavior."""
from abc import ABC, abstractmethod
import logging
from nfl_props.core.contracts import IngestionResult

class SourceAdapter(ABC):
    source_name: str

    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger(f"nfl_props.source.{self.source_name}")

    @abstractmethod
    def ingest(self, **kwargs) -> IngestionResult:
        raise NotImplementedError

    def safe_ingest(self, **kwargs) -> IngestionResult:
        try:
            return self.ingest(**kwargs)
        except Exception as exc:  # One source must not take down the pipeline.
            self.logger.exception("Source failed: %s", exc)
            return IngestionResult(
                source=self.source_name,
                dataset=kwargs.get("dataset", "unknown"),
                status="failed",
                message=str(exc),
            )
