from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from nfl_props.models.efficiency import EfficiencyEstimate
from nfl_props.models.opportunity import OpportunityEstimate


@dataclass
class SimulationResult:
    outcomes: np.ndarray

    @property
    def mean(self) -> float:
        return float(np.mean(self.outcomes))

    @property
    def median(self) -> float:
        return float(np.median(self.outcomes))

    def probability_over(self, line: float) -> float:
        return float(np.mean(self.outcomes > line))

    def percentile(self, q: float) -> float:
        return float(np.percentile(self.outcomes, q))


class ReceivingYardsSimulator:
    def __init__(self, n_sims: int = 10_000, seed: int = 42):
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

    def simulate(self, opportunity: OpportunityEstimate, efficiency: EfficiencyEstimate) -> SimulationResult:
        routes = np.maximum(0, self.rng.normal(opportunity.expected_routes, opportunity.route_std, self.n_sims)).round()
        target_rate = np.clip(opportunity.expected_targets / max(opportunity.expected_routes, 1e-6), 0.01, 0.8)
        targets = self.rng.binomial(routes.astype(int), target_rate)
        catch_rates = np.clip(self.rng.normal(efficiency.catch_rate, efficiency.catch_rate_std, self.n_sims), 0.05, 0.98)
        receptions = self.rng.binomial(targets.astype(int), catch_rates)
        ypr = np.maximum(0.1, self.rng.normal(efficiency.yards_per_reception, efficiency.ypr_std, self.n_sims))
        yards = receptions * ypr
        return SimulationResult(yards)
