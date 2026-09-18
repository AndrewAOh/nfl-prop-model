from __future__ import annotations

import pandas as pd


def add_lagged_rolling_features(
    df: pd.DataFrame,
    group_cols: list[str],
    value_col: str,
    windows: tuple[int, ...] = (2, 4, 6),
) -> pd.DataFrame:
    """Create strictly lagged rolling means to avoid using the current game outcome."""
    result = df.copy()
    result = result.sort_values(group_cols + ["game_date"])
    grouped = result.groupby(group_cols, group_keys=False)[value_col]
    result[f"{value_col}_lag1"] = grouped.shift(1)
    for window in windows:
        result[f"{value_col}_roll{window}"] = grouped.transform(
            lambda s: s.shift(1).rolling(window, min_periods=1).mean()
        )
    return result


def build_receiver_opportunity_features(player_stats: pd.DataFrame) -> pd.DataFrame:
    """Build initial receiving opportunity features from weekly/player-game data.

    This function is deliberately defensive because nflverse column availability can
    differ by table and season. Missing advanced fields are left for later modules.
    """
    df = player_stats.copy()
    numeric_cols = ["targets", "receptions", "receiving_yards", "routes", "snap_count", "target_share"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "targets" in df.columns and "routes" in df.columns:
        df["targets_per_route"] = df["targets"] / df["routes"].replace(0, pd.NA)
    if "receptions" in df.columns and "targets" in df.columns:
        df["catch_rate"] = df["receptions"] / df["targets"].replace(0, pd.NA)
    if "snap_count" in df.columns:
        # Snap share requires team offensive snaps; do not fabricate the denominator.
        df["snap_count"] = df["snap_count"].fillna(0)
    return df
