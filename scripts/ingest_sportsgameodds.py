
import argparse
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from nfl_props.ingestion.sportsgameodds import (
    fetch_events, 
    normalize_events,
    append_to_parquet,
    filter_events_to_week,
    get_api_key,
    save_raw_event,
    player_lookup_log_mult_matched_names,
    player_lookup_log_unresolved_names,
    log_account_usage,
)
from nfl_props.ingestion.player_lookup import NFLPlayerLookup

# =============================================================================
# CONFIG
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_EVENTS_DIR = PROJECT_ROOT / "data" / "raw" / "odds" / "events" / "sportsgameodds"
RAW_PROPS_DIR = PROJECT_ROOT / "data" / "raw" / "odds" / "props" / "sportsgameodds"

INTERIM_DIR = PROJECT_ROOT / "data" / "interim" / "odds"
PROPS_PARQUET = INTERIM_DIR / "props.parquet"

logger = logging.getLogger(__name__)
player_lookup = NFLPlayerLookup()


# =============================================================================
# LOGGING / REPORTING
# =============================================================================

def log_ingestion_report(
    props: pd.DataFrame,
    events_fetched: int,
    snapshot_time: str,
    output_path: Path,
    season: int | None = None,
    weeks: list[int] | None = None,
    sample_size: int = 10,
) -> None:
    """Log a summary of the current SportsGameOdds ingestion run."""

    separator = "=" * 80

    logger.info(separator)
    logger.info("SPORTSGAMEODDS INGESTION COMPLETE")
    logger.info(separator)
    logger.info("Snapshot:       %s", snapshot_time)
    logger.info("Events fetched: %s", events_fetched)
    logger.info("Rows processed: %s", f"{len(props):,}")
    logger.info("Output:         %s", output_path.resolve())

    if season is not None:
        logger.info("Season:         %s", season)

    if weeks:
        logger.info("Weeks:          %s", ", ".join(map(str, sorted(set(weeks)))))

    if props.empty:
        logger.warning("No player props were normalized.")
        return

    # Games
    game_columns = [
        "event_id",
        "game_day",
        "game_time",
        "away_team",
        "home_team",
    ]
    available_game_columns = [
        column for column in game_columns if column in props.columns
    ]

    if "event_id" in available_game_columns:
        games = (
            props[available_game_columns]
            .drop_duplicates(subset=["event_id"])
            .sort_values(
                [
                    column
                    for column in ("game_day", "game_time")
                    if column in available_game_columns
                ]
            )
        )

        logger.info(separator)
        logger.info("GAMES INGESTED")
        logger.info("Unique games with props: %s", len(games))
        logger.info("\n%s", games.to_string(index=False))

    # Market / bookmaker / side distributions
    for column, heading in (
        ("market", "ODDS BY MARKET"),
        ("bookmaker", "ODDS BY BOOKMAKER"),
        ("side", "ODDS BY SIDE"),
    ):
        if column in props.columns:
            logger.info(separator)
            logger.info(heading)
            logger.info(
                "\n%s",
                props[column].value_counts(dropna=False).to_string(),
            )
            logger.info(separator)

    # Unique players with their market counts and market lists
    player_columns = [
        column
        for column in ("player_name", "player_id", "market")
        if column in props.columns
    ]

    if {"player_name", "player_id", "market"}.issubset(props.columns):
        player_markets = (
            props[["player_name", "player_id", "market"]]
            .dropna(subset=["player_name", "market"])
            .drop_duplicates()
            .groupby(["player_name", "player_id"], dropna=False)
            .agg(
                number_of_markets=("market", "nunique"),
                markets=("market", lambda values: sorted(values.unique().tolist())),
            )
            .reset_index()
            .sort_values("player_name")
        )

        logger.info(separator)
        logger.info("Unique players: %s", len(player_markets))
        logger.info(
            "\n%s",
            player_markets.to_string(index=False),
        )
    logger.info(separator)
    logger.info("DATAFRAME SAMPLE: FIRST %s ROWS", sample_size)
    logger.info("\n%s", props.head(sample_size).to_string(index=False))
    logger.info(separator)

    player_lookup_log_mult_matched_names()
    player_lookup_log_unresolved_names()
    # Audit missing player IDs in the final props DataFrame.
    if "player_id" in props.columns:
        missing_id_mask = (
            props["player_id"].isna()
            | props["player_id"].astype(str).str.strip().eq("")
        )

        missing_ids = props.loc[
            missing_id_mask,
            ["player_name", "player_id"],
        ].drop_duplicates()

        if missing_ids.empty:
            logger.info("Validated - All prop rows have player IDs.")
        else:
            logger.warning(
                "Found %d unique player-name/ID combinations without a player ID:",
                len(missing_ids),
            )
            logger.warning(
                "\n%s",
                missing_ids.sort_values("player_name", na_position="last")
                .to_string(index=False),
            )


# =============================================================================
# CACHED JSON REPLAY
# =============================================================================

def extract_cached_events(
    payload: Any,
) -> tuple[list[dict[str, Any]], str | None]:
    """Extract event objects from supported cached JSON formats."""

    snapshot_time = None

    if isinstance(payload, list):
        events = [item for item in payload if isinstance(item, dict)]
        return events, snapshot_time

    if not isinstance(payload, dict):
        return [], snapshot_time

    snapshot_time = payload.get("snapshot_time")

    # Wrapper format used when saving a single event.
    if isinstance(payload.get("event"), dict):
        return [payload["event"]], snapshot_time

    # Wrapper format used for a paginated API response.
    response = payload.get("response")
    if isinstance(response, dict):
        data = response.get("data", [])
        if isinstance(data, list):
            return [
                item for item in data if isinstance(item, dict)
            ], snapshot_time

    # Plain API response format.
    data = payload.get("data")
    if isinstance(data, list):
        return [
            item for item in data if isinstance(item, dict)
        ], snapshot_time

    # A single event saved directly.
    if payload.get("eventID") or payload.get("id"):
        return [payload], snapshot_time

    return [], snapshot_time


def parse_snapshot_time(
    value: str | None,
    fallback: datetime,
) -> datetime:
    """Parse a cached snapshot timestamp, falling back to the file mtime."""

    if not value:
        return fallback

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def ingest_cached_directory(
    raw_dir: Path,
    output_path: Path,
) -> tuple[pd.DataFrame, int, str]:
    """Normalize cached JSON files without making API requests."""

    raw_files = sorted(Path(raw_dir).rglob("*.json"))

    if not raw_files:
        logger.warning("No JSON files found in %s", raw_dir)
        return pd.DataFrame(), 0, datetime.now(timezone.utc).isoformat()

    logger.info("Found %d cached JSON files in %s", len(raw_files), raw_dir)

    frames: list[pd.DataFrame] = []
    total_events = 0
    latest_snapshot = None

    for raw_file in raw_files:
        try:
            with raw_file.open("r", encoding="utf-8") as file:
                payload = json.load(file)

            events, cached_snapshot = extract_cached_events(payload)

            if not events:
                logger.warning("No events found in %s", raw_file)
                continue

            file_mtime = datetime.fromtimestamp(
                raw_file.stat().st_mtime,
                tz=timezone.utc,
            )
            snapshot = parse_snapshot_time(cached_snapshot, file_mtime)

            total_events += len(events)
            latest_snapshot = max(
                latest_snapshot or snapshot,
                snapshot,
            )

            props = normalize_events(events, snapshot.isoformat())

            if not props.empty:
                frames.append(props)

            logger.info(
                "Processed cached file %s | events=%d | props=%d",
                raw_file,
                len(events),
                len(props),
            )

        except (OSError, json.JSONDecodeError, ValueError):
            logger.exception("Failed to process cached file %s", raw_file)

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        append_to_parquet(combined, output_path)
    else:
        combined = pd.DataFrame()
        logger.warning("No props were produced from cached files.")

    snapshot_text = (
        latest_snapshot.isoformat()
        if latest_snapshot
        else datetime.now(timezone.utc).isoformat()
    )

    return combined, total_events, snapshot_text


# =============================================================================
# LIVE INGESTION
# =============================================================================

def ingest_live_week(
    season: int,
    week: int,
    limit: int,
    output_path: Path,
) -> tuple[pd.DataFrame, int, str]:
    """Fetch, filter, save, and normalize events for one NFL week."""

    run_time = datetime.now(timezone.utc)
    snapshot_text = run_time.isoformat()

    events_dir = (
        RAW_EVENTS_DIR
        / f"{season}_WK{week:02d}"
        / run_time.strftime("%Y-%m-%d")
    )
    
    # Define a rolling 7-day window starting at ingestion time.
    run_time = datetime.now(timezone.utc)
    snapshot_text = run_time.isoformat()

    starts_after = run_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    starts_before = (
        run_time + timedelta(days=7)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        "SportsGameOdds API date filter | "
        "startsAfter=%s | startsBefore=%s",
        starts_after,
        starts_before,
    )

    api_key = get_api_key()

    events, api_snapshot = fetch_events(
        raw_dir=events_dir,
        api_key=api_key,
        limit=limit,
        starts_after=starts_after,
        starts_before=starts_before,
    )

    log_account_usage(api_key)

    # Use the timestamp returned by the fetch function if it supplies one.
    if isinstance(api_snapshot, datetime):
        run_time = api_snapshot
        snapshot_text = run_time.isoformat()
    elif isinstance(api_snapshot, str):
        snapshot_text = api_snapshot

    logger.info("Events fetched from API: %d", len(events))

    events = filter_events_to_week(
        events,
        season=season,
        week=week,
    )

    logger.info(
        "Events matching season=%d week=%d: %d",
        season,
        week,
        len(events),
    )

    frames: list[pd.DataFrame] = []

    for event in events:
        event_id = event.get("eventID") or event.get("id")

        try:
            save_raw_event(
                event,
                run_time,
                season,
                week,
                raw_dir=RAW_PROPS_DIR,
            )

            props = normalize_events([event], snapshot_text)

            if not props.empty:
                frames.append(props)
            else:
                logger.warning(
                    "Event %s produced no normalized props. "
                    "Verify that the event payload contains an odds tree.",
                    event_id,
                )

        except (KeyError, TypeError, ValueError, OSError):
            logger.exception("Failed to process event %s", event_id)

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        append_to_parquet(combined, output_path)
    else:
        combined = pd.DataFrame()
        logger.warning("No player props were produced for this week.")

    return combined, len(events), snapshot_text


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest NFL player props from SportsGameOdds."
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all",
        action="store_true",
        help="Fetch and ingest events for a specified NFL week.",
    )
    mode.add_argument(
        "--raw-dir",
        type=Path,
        help="Replay cached JSON files without API calls.",
    )

    parser.add_argument("--season", type=int, help="NFL season, e.g. 2026.")
    parser.add_argument("--week", type=int, help="NFL week, e.g. 5.")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum events per API page.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROPS_PARQUET,
        help="Output Parquet path.",
    )

    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = parse_args()

    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")

    if args.all:
        if args.season is None or args.week is None:
            raise SystemExit("--all requires both --season and --week.")

        if not 1 <= args.week <= 22:
            raise SystemExit("--week must be between 1 and 22.")

        props, event_count, snapshot = ingest_live_week(
            season=args.season,
            week=args.week,
            limit=args.limit,
            output_path=args.output,
        )
        weeks = [args.week]
    else:
        props, event_count, snapshot = ingest_cached_directory(
            raw_dir=args.raw_dir,
            output_path=args.output,
        )
        weeks = [args.week] if args.week is not None else []

    log_ingestion_report(
        props=props,
        events_fetched=event_count,
        snapshot_time=snapshot,
        output_path=args.output,
        season=args.season,
        weeks=weeks,
    )


if __name__ == "__main__":
    main()