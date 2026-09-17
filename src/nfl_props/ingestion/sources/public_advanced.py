"""Optional public advanced-source adapters.

These adapters intentionally do not guess undocumented endpoints or bypass access
controls. They return `skipped` until a verified public export/API contract is added.
"""
from nfl_props.core.contracts import IngestionResult
from nfl_props.ingestion.base import SourceAdapter

class PublicAdvancedAdapter(SourceAdapter):
    def __init__(self, settings, source_name: str, homepage: str):
        self.source_name = source_name
        self.homepage = homepage
        super().__init__(settings)

    def ingest(self, dataset: str, **kwargs) -> IngestionResult:
        return IngestionResult(
            source=self.source_name,
            dataset=dataset,
            status="skipped",
            message=(
                "No verified public machine-readable endpoint configured. "
                f"Review source manually before enabling automation: {self.homepage}"
            ),
            metadata={"homepage": self.homepage},
        )
