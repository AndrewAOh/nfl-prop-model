import argparse
from pathlib import Path
import sys
import pandas as pd
import logging
import time
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nfl_props.config.settings import settings
from nfl_props.core.logging import configure_logging
from nfl_props.ingestion.sources.nflverse import NflverseAdapter
from nfl_props.ingestion.sources.public_advanced import PublicAdvancedAdapter
from nfl_props.storage.duckdb_store import DuckDBStore
from nfl_props.ingestion.weather import OpenMeteoClient, get_weather_for_game

logger = logging.getLogger(__name__)
# logging.basicConfig(
#     level=logging.DEBUG,
#     format=(
#         "%(asctime)s | %(levelname)s | "
#         "%(name)s | %(message)s"
#     ),
# )


def ingest_game_weather(
    schedules: pd.DataFrame,
    output_dir: Path,
) -> pd.DataFrame:
    """
    Ingest historical weather for scheduled games.

    Failures are recorded as rows instead of stopping the entire run.
    """

    required_columns = [
        "game_id",
        "gameday",
        "gametime",
        "home_team",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in schedules.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Schedules missing required columns: {missing_columns}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    weather_records: list[dict[str, Any]] = []

    # Reuse one Session and connection pool for the entire ingestion.
    weather_client = OpenMeteoClient(
        timeout=(5, 30),
        max_retries=3,
    )

    total_games = len(schedules)

    try:
        for game_number, game in enumerate(
            schedules.itertuples(index=False),
            start=1,
        ):
            game_id = getattr(game, "game_id")
            gameday = getattr(game, "gameday")
            gametime = getattr(game, "gametime")
            home_team = getattr(game, "home_team")

            logger.info(
                "Weather ingestion: %s/%s game_id=%s",
                game_number,
                total_games,
                game_id,
            )

            game_start_time = time.monotonic()

            base_record = {
                "game_id": game_id,
                "gameday": gameday,
                "gametime": gametime,
                "home_team": home_team,
            }

            try:
                weather = get_weather_for_game(
                    home_team=home_team,
                    gameday=gameday,
                    gametime=gametime,
                    client=weather_client,
                )

                record = {
                    **base_record,
                    **weather,
                }

                weather_records.append(record)

                elapsed = time.monotonic() - game_start_time

                logger.info(
                    "Weather completed: game_id=%s "
                    "available=%s duration=%.2fs",
                    game_id,
                    record.get("weather_available"),
                    elapsed,
                )

            except Exception as exc:
                # Catch unexpected errors for this individual game.
                # The rest of the season should continue processing.
                elapsed = time.monotonic() - game_start_time

                logger.exception(
                    "Unexpected weather failure: game_id=%s "
                    "duration=%.2fs",
                    game_id,
                    elapsed,
                )

                weather_records.append(
                    {
                        **base_record,
                        "weather_available": False,
                        "reason": "Unexpected ingestion error",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )

    finally:
        weather_client.close()

    weather_df = pd.DataFrame(weather_records)

    output_path = output_dir / "game_weather.parquet"

    weather_df.to_parquet(
        output_path,
        index=False,
    )

    logger.info(
        "Weather data written: path=%s rows=%s",
        output_path,
        len(weather_df),
    )

    # Summary statistics.
    if weather_df.empty:
        logger.warning("No weather records were generated")
        return weather_df

    successful = int(
        weather_df["weather_available"]
        .fillna(False)
        .astype(bool)
        .sum()
    )
    indoor_dome = ( 
        weather_df["weather_available"].eq(False) & 
        weather_df["reason"].eq("Indoor dome") 
    ).sum()
    retractable_roof = (
        weather_df["weather_available"].eq(False) & 
        weather_df["reason"].eq("Retractable roof; roof state unavailable") 
    ).sum()
    failed = ( 
        weather_df["weather_available"].eq(False) & 
        weather_df["reason"].ne("Indoor dome") &
        weather_df["reason"].ne("Retractable roof; roof state unavailable") 
    ).sum() 

    reason_counts = (
        weather_df.loc[
            ~weather_df["weather_available"].fillna(False).astype(bool),
            "reason",
        ]
        .fillna("Unknown")
        .value_counts()
        .to_dict()
    )

    logger.info(
        "Weather summary: total=%s successful=%s dome/roof=%s failed=%s",
        len(weather_df),
        successful,
        indoor_dome + retractable_roof,
        failed,
    )

    logger.info(
        "Weather unavailable reasons: %s",
        reason_counts,
    )
    return weather_df


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ingest NFL foundation data"
    )

    parser.add_argument(
        "--season",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--weeks",
        type=int,
        nargs="+",
        default=None,
        help="Specific weeks to ingest. Defaults to all available weeks.",
    )

    parser.add_argument(
        "--refresh-weather",
        action="store_true",
        help="Retry weather for games that previously failed.",
    )

    parser.add_argument(
        "--skip-participation",
        action="store_true",
        help="Skip unavailable official participation data.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    configure_logging(settings.log_level)

    store = DuckDBStore(settings.db_path)
    nflverse = NflverseAdapter(settings)

    advanced = [
        PublicAdvancedAdapter(
            settings,
            "rbsdm",
            "https://rbsdm.com/",
        ),
        PublicAdvancedAdapter(
            settings,
            "ftn",
            "https://ftnfantasy.com/nfl/stats",
        ),
        PublicAdvancedAdapter(
            settings,
            "sumersports_offense",
            "https://sumersports.com/teams/offensive/",
        ),
        PublicAdvancedAdapter(
            settings,
            "sumersports_defense",
            "https://sumersports.com/teams/defensive/",
        ),
    ]

    results = []

    try:
        # Ingest schedule
        result = nflverse.safe_ingest(
            dataset="schedules",
            season=args.season,
            stat_type=None,
        )

        store.record_result(result)
        results.append(result)

        schedule_path = (
            Path("data/raw/nflverse")
            / f"schedules_{args.season}.parquet"
        )

        if not schedule_path.exists():
            raise FileNotFoundError(
                f"Schedule file not found: {schedule_path}"
            )

        schedules = pd.read_parquet(schedule_path)

        # Filter requested weeks
        if args.weeks is not None:
            if "week" not in schedules.columns:
                raise ValueError(
                    "Schedules missing required column: week"
                )

            schedules = schedules[
                schedules["week"].isin(args.weeks)
            ].copy()

        logger.info(
            "Processing season=%s weeks=%s games=%s",
            args.season,
            args.weeks if args.weeks else "all",
            len(schedules),
        )

        # Weather ingestion
        # Note: this currently writes one Parquet file and does
        # not yet merge with previously stored weather data.
        ingest_game_weather(
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
        ]

        if not args.skip_participation:
            datasets.append(("participation", None))

        for dataset, stat_type in datasets:
            result = nflverse.safe_ingest(
                dataset=dataset,
                season=args.season,
                stat_type=stat_type,
            )

            store.record_result(result)
            results.append(result)

        # Next Gen Stats
        for stat_type in ["passing", "receiving", "rushing"]:
            result = nflverse.safe_ingest(
                dataset="nextgen_stats",
                season=args.season,
                stat_type=stat_type,
            )

            store.record_result(result)
            results.append(result)

        # PFR Advanced Stats
        for stat_type in ["pass", "rush", "rec", "def"]:
            result = nflverse.safe_ingest(
                dataset="pfr_advstats",
                season=args.season,
                stat_type=stat_type,
            )

            store.record_result(result)
            results.append(result)

        # Public advanced metrics
        for adapter in advanced:
            result = adapter.safe_ingest(
                dataset="team_or_player_advanced_metrics"
            )

            store.record_result(result)
            results.append(result)

    finally:
        store.close()

    for result in results:
        print(
            f"{result.source:22} "
            f"{result.dataset:28} "
            f"{result.status:8} "
            f"{result.message}"
        )


if __name__ == "__main__":
    main()