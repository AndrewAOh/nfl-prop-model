from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import nflreadpy as nfl
except ImportError:  # Optional at import time; a clear error is raised when used.
    nfl = None


class NflverseAdapter:
    """Access nflverse datasets through the official Python port, nflreadpy.

    nflreadpy handles dataset URLs, formats, and nflverse repository changes.
    Results are cached as local Parquet files when ``raw_dir`` is provided.
    """

    def __init__(self, raw_dir: str | Path):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _require_nflreadpy() -> None:
        if nfl is None:
            raise ImportError(
                "nflreadpy is required. Install project dependencies with "
                "`pip install -r requirements.txt`."
            )

    @staticmethod
    def _to_pandas(data) -> pd.DataFrame:
        """Convert nflreadpy's Polars result to pandas without assuming one API."""
        if isinstance(data, pd.DataFrame):
            return data
        if hasattr(data, "to_pandas"):
            return data.to_pandas()
        if hasattr(data, "collect"):
            collected = data.collect()
            return collected.to_pandas() if hasattr(collected, "to_pandas") else pd.DataFrame(collected)
        return pd.DataFrame(data)

    def _cached(self, name: str, loader) -> pd.DataFrame:
        path = self.raw_dir / f"{name}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        frame = self._to_pandas(loader())
        frame.to_parquet(path, index=False)
        return frame

    def load_pbp(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached(f"play_by_play_{season}", lambda: nfl.load_pbp(seasons=[season]))
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame

    def load_player_stats(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached("player_stats", lambda: nfl.load_player_stats())
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame

    def load_snap_counts(self, seasons: Iterable[int]) -> pd.DataFrame:
        self._require_nflreadpy()
        seasons = list(seasons)
        frame = self._cached("snap_counts", lambda: nfl.load_snap_counts())
        return frame[frame["season"].isin(seasons)].copy() if "season" in frame else frame

    def load_schedules(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached("schedules", lambda: nfl.load_schedules())
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame

    def load_rosters(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached(f"rosters_{season}", lambda: nfl.load_rosters(seasons=[season]))
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame

    def load_participation(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached(f"participation_{season}", lambda: nfl.load_participation(seasons=[season]))
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame

    def load_injuries(self, season: int) -> pd.DataFrame:
        self._require_nflreadpy()
        frame = self._cached(f"injuries_{season}", lambda: nfl.load_injuries(seasons=[season]))
        return frame[frame["season"].eq(season)].copy() if "season" in frame else frame


# Backward-compatible name used by earlier scripts.
NflverseClient = NflverseAdapter
