"""nflverse ingestion through the maintained nflreadpy package.

Raw datasets are cached as Parquet files under data/raw/nflverse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from nfl_props.core.contracts import IngestionResult
from nfl_props.ingestion.base import SourceAdapter

try:
    import nflreadpy as nfl
except ImportError:  # pragma: no cover
    nfl = None


class NflverseAdapter(SourceAdapter):
    source_name = "nflverse"

    def _require_package(self) -> None:
        if nfl is None:
            raise ImportError("Install nflreadpy with: pip install -r requirements.txt")

    @staticmethod
    def _to_pandas(frame: Any) -> pd.DataFrame:
        if hasattr(frame, "to_pandas"):
            return frame.to_pandas()
        if isinstance(frame, pd.DataFrame):
            return frame
        return pd.DataFrame(frame)

    def _load_cached(self, filename: str, loader) -> tuple[pd.DataFrame, Path]:
        output_dir = self.settings.raw_root / "nflverse"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        if output_path.exists():
            return pd.read_parquet(output_path), output_path
        frame = self._to_pandas(loader())
        frame.to_parquet(output_path, index=False)
        return frame, output_path

    def _result(self, dataset: str, frame: pd.DataFrame, path: Path, **metadata) -> IngestionResult:
        return IngestionResult(
            self.source_name,
            dataset,
            "success",
            [path],
            rows=len(frame),
            metadata=metadata,
        )

    def ingest(self, dataset: str, season: int | None = None, stat_type: str | None = None) -> IngestionResult:
        self._require_package()
        if season is None and dataset not in {"players", "ff_playerids"}:
            raise ValueError(f"A season is required for dataset={dataset}")

        if dataset == "schedules":
            frame, path = self._load_cached(
                f"schedules_{season}.parquet",
                lambda: nfl.load_schedules(seasons=season),
            )
        elif dataset == "players":
            frame, path = self._load_cached("players.parquet", nfl.load_players)
        elif dataset == "ff_playerids":
            frame, path = self._load_cached("ff_playerids.parquet", nfl.load_ff_playerids)
        elif dataset == "player_stats":
            frame, path = self._load_cached(
                f"player_stats_{season}.parquet",
                lambda: nfl.load_player_stats(seasons=season, summary_level="week"),
            )
        elif dataset == "pbp":
            frame, path = self._load_cached(
                f"pbp_{season}.parquet",
                lambda: nfl.load_pbp(seasons=season),
            )
        elif dataset == "rosters":
            frame, path = self._load_cached(
                f"rosters_{season}.parquet",
                lambda: nfl.load_rosters(seasons=season),
            )
        elif dataset == "rosters_weekly":
            frame, path = self._load_cached(
                f"rosters_weekly_{season}.parquet",
                lambda: nfl.load_rosters_weekly(seasons=season),
            )
        elif dataset == "snap_counts":
            frame, path = self._load_cached(
                f"snap_counts_{season}.parquet",
                lambda: nfl.load_snap_counts(seasons=season),
            )
        elif dataset == "participation":
            frame, path = self._load_cached(
                f"participation_{season}.parquet",
                lambda: nfl.load_participation(seasons=season),
            )
        elif dataset == "nextgen_stats":
            if stat_type not in {"passing", "receiving", "rushing"}:
                raise ValueError("nextgen_stats requires stat_type passing, receiving, or rushing")
            frame, path = self._load_cached(
                f"nextgen_stats_{stat_type}_{season}.parquet",
                lambda: nfl.load_nextgen_stats(seasons=season, stat_type=stat_type),
            )
        elif dataset == "pfr_advstats":
            if stat_type not in {"pass", "rush", "rec", "def"}:
                raise ValueError("pfr_advstats requires stat_type pass, rush, rec, or def")
            frame, path = self._load_cached(
                f"pfr_advstats_{stat_type}_{season}.parquet",
                lambda: nfl.load_pfr_advstats(
                    seasons=season, stat_type=stat_type, summary_level="week"
                ),
            )
        else:
            return IngestionResult(self.source_name, dataset, "skipped", message="Unknown dataset")

        return self._result(dataset, frame, path, season=season, stat_type=stat_type)


NflverseClient = NflverseAdapter