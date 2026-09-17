"""nflverse downloader.

URLs are centralized so they can be updated without changing pipeline code.
The URLs are public GitHub release assets; validate schemas after download.
"""
from pathlib import Path
import requests
from nfl_props.core.contracts import IngestionResult
from nfl_props.ingestion.base import SourceAdapter

DATASETS = {
    "player_stats": "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv",
    "pbp": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet",
    "schedules": "https://github.com/nflverse/nflverse-data/releases/download/schedules/schedules.csv",
}

class NflverseAdapter(SourceAdapter):
    source_name = "nflverse"

    def ingest(self, dataset: str, season: int | None = None) -> IngestionResult:
        if dataset not in DATASETS:
            return IngestionResult(self.source_name, dataset, "skipped", message="Unknown dataset")
        url = DATASETS[dataset].format(season=season) if season else DATASETS[dataset]
        extension = ".parquet" if url.endswith(".parquet") else ".csv"
        output_dir = self.settings.raw_root / "nflverse"
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{dataset}_{season}{extension}" if "{season}" in DATASETS[dataset] else f"{dataset}{extension}"
        output_path = output_dir / filename
        response = requests.get(url, timeout=self.settings.request_timeout_seconds, headers={"User-Agent": self.settings.user_agent})
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return IngestionResult(self.source_name, dataset, "success", [output_path], metadata={"url": url, "season": season})
