from __future__ import annotations

import numpy as np
import pandas as pd


class RollingBaseline:
    def __init__(self, value_col: str, window: int = 4, min_periods: int = 1):
        self.value_col = value_col
        self.window = window
        self.min_periods = min_periods

    def predict(self, history: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        df = history.copy().sort_values(group_cols + ["game_date"])
        grouped = df.groupby(group_cols, group_keys=False)[self.value_col]
        df["prediction"] = grouped.transform(
            lambda s: s.shift(1).rolling(self.window, min_periods=self.min_periods).mean()
        )
        return df


class ExponentialWeightedBaseline:
    def __init__(self, value_col: str, alpha: float = 0.35):
        self.value_col = value_col
        self.alpha = alpha

    def predict(self, history: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        df = history.copy().sort_values(group_cols + ["game_date"])
        grouped = df.groupby(group_cols, group_keys=False)[self.value_col]
        df["prediction"] = grouped.transform(
            lambda s: s.shift(1).ewm(alpha=self.alpha, adjust=False, min_periods=1).mean()
        )
        return df
