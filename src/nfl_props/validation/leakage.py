from __future__ import annotations

import pandas as pd


def assert_point_in_time(features: pd.DataFrame, cutoff_col: str = "feature_available_at", prediction_col: str = "prediction_time") -> None:
    if cutoff_col not in features.columns or prediction_col not in features.columns:
        raise ValueError(f"Expected columns: {cutoff_col}, {prediction_col}")
    available = pd.to_datetime(features[cutoff_col], utc=True, errors="coerce")
    prediction = pd.to_datetime(features[prediction_col], utc=True, errors="coerce")
    if available.isna().any() or prediction.isna().any():
        raise ValueError("Invalid or missing timestamps detected")
    violations = available > prediction
    if violations.any():
        raise ValueError(f"Point-in-time leakage detected in {violations.sum()} rows")


def require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = set(columns) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
