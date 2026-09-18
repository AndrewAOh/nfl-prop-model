from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class EfficiencyEstimate:
    catch_rate: float = 0.65
    yards_per_reception: float = 11.0
    catch_rate_std: float = 0.08
    ypr_std: float = 4.0


class SimpleEfficiencyModel:
    def estimate(self, recent_receptions: list[float], recent_targets: list[float], recent_yards: list[float]) -> EfficiencyEstimate:
        targets = sum(recent_targets)
        receptions = sum(recent_receptions)
        yards = sum(recent_yards)
        catch_rate = receptions / targets if targets > 0 else 0.65
        ypr = yards / receptions if receptions > 0 else 11.0
        return EfficiencyEstimate(float(np.clip(catch_rate, 0.05, 0.98)), max(0.1, float(ypr)))
