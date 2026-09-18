from __future__ import annotations

import pandas as pd


REQUIRED_PREDICTION_COLUMNS = [
    "game_id", "player_id", "market_type", "line", "prediction_time", "model_version"
]


def validate_prediction_frame(df: pd.DataFrame) -> None:
    missing = set(REQUIRED_PREDICTION_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing prediction columns: {sorted(missing)}")
    if df["line"].isna().any():
        raise ValueError("Prediction lines cannot be null")
