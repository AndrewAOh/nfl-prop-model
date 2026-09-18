from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class OpportunityEstimate:
    expected_routes: float
    expected_targets: float
    route_std: float = 3.0
    target_std: float = 2.0


class SimpleOpportunityModel:
    """Transparent MVP model; replace with supervised models after feature QA."""

    def estimate(self, recent_routes: list[float], recent_targets: list[float], team_pass_attempts: float) -> OpportunityEstimate:
        routes = float(np.mean(recent_routes[-4:])) if recent_routes else 0.0
        targets = float(np.mean(recent_targets[-4:])) if recent_targets else 0.0
        # Shrink target expectation toward route-based opportunity when possible.
        route_rate = (targets / routes) if routes > 0 else 0.12
        expected_targets = max(0.0, route_rate * routes)
        if team_pass_attempts > 0 and routes > 0:
            expected_targets = min(expected_targets, team_pass_attempts * 0.5)
        return OpportunityEstimate(routes, expected_targets)
