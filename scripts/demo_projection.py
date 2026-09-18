from nfl_props.models.efficiency import SimpleEfficiencyModel
from nfl_props.models.opportunity import SimpleOpportunityModel
from nfl_props.pricing.odds import expected_value
from nfl_props.simulation.engine import ReceivingYardsSimulator


def main() -> None:
    opportunity = SimpleOpportunityModel().estimate(
        recent_routes=[34, 38, 36, 40],
        recent_targets=[7, 9, 8, 10],
        team_pass_attempts=36,
    )
    efficiency = SimpleEfficiencyModel().estimate(
        recent_receptions=[5, 6, 5, 7],
        recent_targets=[7, 9, 8, 10],
        recent_yards=[61, 78, 55, 92],
    )
    result = ReceivingYardsSimulator(n_sims=10_000, seed=42).simulate(opportunity, efficiency)
    p_over = result.probability_over(59.5)
    print({
        "expected_routes": opportunity.expected_routes,
        "expected_targets": opportunity.expected_targets,
        "mean_yards": round(result.mean, 2),
        "median_yards": round(result.median, 2),
        "p_over_59_5": round(p_over, 4),
        "ev_at_minus_110": round(expected_value(p_over, -110), 4),
        "p10": round(result.percentile(10), 2),
        "p90": round(result.percentile(90), 2),
    })


if __name__ == "__main__":
    main()
