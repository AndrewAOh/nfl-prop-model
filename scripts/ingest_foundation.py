import argparse
from pathlib import Path
import sys
import pandas as pd
import logging
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nfl_props.config.settings import settings
from nfl_props.core.logging import configure_logging
from nfl_props.ingestion.sources.nflverse import NflverseAdapter
from nfl_props.ingestion.sources.public_advanced import PublicAdvancedAdapter
from nfl_props.storage.duckdb_store import DuckDBStore
from nfl_props.ingestion.weather import OpenMeteoClient, get_weather_for_game

logger = logging.getLogger(__name__)


def ingest_game_weather(
    schedules: pd.DataFrame,
    output_dir: Path,
) -> pd.DataFrame:
    """
    Retrieve weather for every scheduled game and save as Parquet.
    """

    required_columns = {
        "game_id",
        "season",
        "week",
        "gameday",
        "home_team",
        "away_team",
        "gametime",
    }

    missing_columns = required_columns - set(schedules.columns)

    if missing_columns:
        raise ValueError(
            f"Schedules missing required columns: {missing_columns}"
        )

    if schedules.empty:
        logger.warning("No scheduled games found.")
        return pd.DataFrame()

    weather_records = []
    client = OpenMeteoClient()

    for game_row in schedules.itertuples(index=False):
        game = game_row._asdict()

        game_id = game["game_id"]
        matchup = (
            f"{game['away_team']} at {game['home_team']}"
        )

        try:
            weather = get_weather_for_game(
                game=game,
                client=client,
            )

            weather_records.append(weather)

            logger.info(
                "Weather retrieved: %s",
                matchup,
            )

        except Exception as exc:
            logger.exception(
                "Weather failed for game %s: %s",
                game_id,
                exc,
            )

            # Preserve failed games for quality checks.
            weather_records.append({
                "game_id": game_id,
                "season": game["season"],
                "week": game["week"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "weather_available": False,
                "weather_error": str(exc),
            })

    weather_df = pd.DataFrame(weather_records)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = output_dir / "game_weather.parquet"

    weather_df.to_parquet(
        output_path,
        index=False,
    )

    successful = weather_df["weather_available"].eq(True).sum()
    indoor_dome = (
            weather_df["weather_available"].eq(False)
            & weather_df["reason"].eq("Indoor dome")
        ).sum()
    failed = (
            weather_df["weather_available"].eq(False)
            & weather_df["reason"].ne("Indoor dome")
        ).sum()

    logger.info(
        "Saved %d weather records to %s",
        len(weather_df),
        output_path,
    )

    logger.info(
        "Weather summary: %d successful, %d indoor, %d failed",
        successful,
        indoor_dome,
        failed,
    )

    return weather_df

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

    # Ingest schedules first
    result = nflverse.safe_ingest(
        dataset="schedules",
        season=args.season,
        stat_type=None,
    )

    store.record_result(result)
    results.append(result)

    # Load schedules from the generated Parquet file
    schedule_path = (
        Path("data/raw/nflverse") / f"schedules_{args.season}.parquet"
    )

    if not schedule_path.exists():
        raise FileNotFoundError(
            f"Schedule file not found: {schedule_path}"
        )

    schedules = pd.read_parquet(schedule_path)

    # Retrieve weather for every scheduled game
    weather_result = ingest_game_weather(
        schedules=schedules,
        output_dir=Path("data/raw/weather"),
    )
    datasets = [
        ("players", None),
        ("ff_playerids", None),
        ("player_stats", None),
        ("pbp", None),
        ("rosters", None),
        ("rosters_weekly", None),
        ("snap_counts", None),
        ("participation", None),
    ]
    
    for dataset, stat_type in datasets:
        result = nflverse.safe_ingest(
            dataset=dataset, season=args.season, stat_type=stat_type
        )
        store.record_result(result)
        results.append(result)

    for stat_type in ["passing", "receiving", "rushing"]:
        result = nflverse.safe_ingest(
            dataset="nextgen_stats", season=args.season, stat_type=stat_type
        )
        store.record_result(result)
        results.append(result)

    for stat_type in ["pass", "rush", "rec", "def"]:
        result = nflverse.safe_ingest(
            dataset="pfr_advstats", season=args.season, stat_type=stat_type
        )
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