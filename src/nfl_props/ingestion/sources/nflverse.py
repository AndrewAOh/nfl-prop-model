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

    # Store each nflverse dataset in its matching source folder. The two
    # reference tables (players and ff_playerids) remain at the nflverse root
    # because there are no dedicated folders for them in the requested layout.
    DATASET_DIRS = {
        "schedules": "schedules_parquet_data",
        "player_stats": "player_stats_parquet_data",
        "pbp": "pbp_parquet_data",
        "rosters": "rosters_parquet_data",
        "rosters_weekly": "weekly_rosters_parquet_data",
        "snap_counts": "snap_counts_parquet_data",
        "participation": "participation_parquet_data",
        "nextgen_stats_passing": "ngs_passing_parquet_data",
        "nextgen_stats_receiving": "ngs_receiving_parquet_data",
        "nextgen_stats_rushing": "ngs_rushing_parquet_data",
        "pfr_advstats_pass": "pfr_advstats_pass_parquet_data",
        "pfr_advstats_rec": "pfr_advstats_rec_parquet_data",
        "pfr_advstats_rush": "pfr_advstats_rush_parquet_data",
        "pfr_advstats_def": "pfr_advstats_def_parquet_data",
    }

    def _load_cached(
        self,
        filename: str,
        loader,
        dataset_key: str | None = None,
    ) -> tuple[pd.DataFrame, Path]:
        """Fetch fresh data and overwrite its current raw Parquet file."""
        output_root = self.settings.raw_root / "nflverse"
        dataset_dir = self.DATASET_DIRS.get(dataset_key) if dataset_key else None
        output_dir = output_root / dataset_dir if dataset_dir else output_root
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # Do not return a stale local cache: each ingestion run refreshes the file.
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
                dataset_key="schedules",
            )
        elif dataset == "players":
            frame, path = self._load_cached("players.parquet", nfl.load_players)
        elif dataset == "ff_playerids":
            frame, path = self._load_cached("ff_playerids.parquet", nfl.load_ff_playerids)
        elif dataset == "player_stats":
            frame, path = self._load_cached(
                f"player_stats_{season}.parquet",
                lambda: nfl.load_player_stats(seasons=season, summary_level="week"),
                dataset_key="player_stats",
            )
        elif dataset == "pbp":
            frame, path = self._load_cached(
                f"pbp_{season}.parquet",
                lambda: nfl.load_pbp(seasons=season),
                dataset_key="pbp",
            )
        elif dataset == "rosters":
            frame, path = self._load_cached(
                f"rosters_{season}.parquet",
                lambda: nfl.load_rosters(seasons=season),
                dataset_key="rosters",
            )
        elif dataset == "rosters_weekly":
            frame, path = self._load_cached(
                f"rosters_weekly_{season}.parquet",
                lambda: nfl.load_rosters_weekly(seasons=season),
                dataset_key="rosters_weekly",
            )
        elif dataset == "snap_counts":
            frame, path = self._load_cached(
                f"snap_counts_{season}.parquet",
                lambda: nfl.load_snap_counts(seasons=season),
                dataset_key="snap_counts",
            )
        elif dataset == "participation":
            frame, path = self._load_cached(
                f"participation_{season}.parquet",
                lambda: nfl.load_participation(seasons=season),
                dataset_key="participation",
            )
        elif dataset == "nextgen_stats":
            if stat_type not in {"passing", "receiving", "rushing"}:
                raise ValueError("nextgen_stats requires stat_type passing, receiving, or rushing")
            frame, path = self._load_cached(
                f"nextgen_stats_{stat_type}_{season}.parquet",
                lambda: nfl.load_nextgen_stats(seasons=season, stat_type=stat_type),
                dataset_key=f"nextgen_stats_{stat_type}",
            )
        elif dataset == "pfr_advstats":
            if stat_type not in {"pass", "rush", "rec", "def"}:
                raise ValueError("pfr_advstats requires stat_type pass, rush, rec, or def")
            frame, path = self._load_cached(
                f"pfr_advstats_{stat_type}_{season}.parquet",
                lambda: nfl.load_pfr_advstats(
                    seasons=season, stat_type=stat_type, summary_level="week"
                ),
                dataset_key=f"pfr_advstats_{stat_type}",
            )
        else:
            return IngestionResult(self.source_name, dataset, "skipped", message="Unknown dataset")

        return self._result(dataset, frame, path, season=season, stat_type=stat_type)


NflverseClient = NflverseAdapter