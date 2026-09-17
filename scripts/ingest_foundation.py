import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nfl_props.config.settings import settings
from nfl_props.core.logging import configure_logging
from nfl_props.ingestion.sources.nflverse import NflverseAdapter
from nfl_props.ingestion.sources.public_advanced import PublicAdvancedAdapter
from nfl_props.storage.duckdb_store import DuckDBStore

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    configure_logging(settings.log_level)
    store = DuckDBStore(settings.db_path)
    nflverse = NflverseAdapter(settings)
    advanced = [
        PublicAdvancedAdapter(settings, "rbsdm", "https://rbsdm.com/"),
        PublicAdvancedAdapter(settings, "ftn", "https://ftnfantasy.com/nfl/stats"),
        PublicAdvancedAdapter(settings, "sumersports_offense", "https://sumersports.com/teams/offensive/"),
        PublicAdvancedAdapter(settings, "sumersports_defense", "https://sumersports.com/teams/defensive/"),
    ]
    results = []
    for dataset in ["schedules", "player_stats", "pbp"]:
        result = nflverse.safe_ingest(dataset=dataset, season=args.season)
        store.record_result(result)
        results.append(result)
    for adapter in advanced:
        result = adapter.safe_ingest(dataset="team_or_player_advanced_metrics")
        store.record_result(result)
        results.append(result)
    store.close()
    for result in results:
        print(f"{result.source:22} {result.dataset:28} {result.status:8} {result.message}")

if __name__ == "__main__":
    main()
