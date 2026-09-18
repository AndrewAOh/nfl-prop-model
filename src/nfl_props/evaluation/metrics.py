from __future__ import annotations

import numpy as np


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def brier_score(actual_binary: np.ndarray, probabilities: np.ndarray) -> float:
    return float(np.mean((probabilities - actual_binary) ** 2))


def calibration_table(actual_binary: np.ndarray, probabilities: np.ndarray, bins: int = 10):
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (probabilities >= low) & (probabilities < high if high < 1 else probabilities <= high)
        if mask.any():
            rows.append({
                "bin_low": low,
                "bin_high": high,
                "count": int(mask.sum()),
                "predicted_mean": float(probabilities[mask].mean()),
                "actual_rate": float(actual_binary[mask].mean()),
            })
    return rows
