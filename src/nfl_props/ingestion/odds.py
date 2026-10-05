from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from .player_lookup import NFLPlayerLookup
from .nflverse import NflverseAdapter


"""
New API Odds Ingestion Process: API -> get_event_props() -> save_raw_event() -> process_event() -> Parquet
- Uses ingest_events()

Previously downloaded API Odds: JSON -> load_raw_event() -> process_event() -> Parquet
- Uses ingest_raw_events()

"""

# =============================================================================
# CONFIG
# =============================================================================

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

PROP_MARKETS = [
    "player_pass_yds",
    "player_pass_attempts",
    "player_rush_yds",
    "player_rush_attempts",
    "player_reception_yds",
    "player_receptions",
]

PROJECT_ROOT = Path(__file__).resolve().parents[3]

RAW_PROPS_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "odds"
    / "props"
)

RAW_EVENTS_DIR = (
    PROJECT_ROOT
        / "data"
        / "raw"
        / "odds"
        / "events"
)

PROCESSED_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "odds"
)

PROPS_PARQUET = PROCESSED_DIR / "props.parquet"

REQUEST_TIMEOUT = 30

logger = logging.getLogger(__name__)

player_lookup = NFLPlayerLookup()
nflverse = NflverseAdapter(
    raw_dir=PROJECT_ROOT / "data" / "raw" / "nflverse"
)

NFL_TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


# =============================================================================
# API KEY
# =============================================================================

def get_api_key() -> str:
    """
    Get The Odds API key from the ODDS_API_KEY environment variable.
    """

    api_key = os.getenv("ODDS_API_KEY")

    if not api_key:
        raise RuntimeError(
            "ODDS_API_KEY environment variable is not set."
        )

    return api_key


# =============================================================================
# ODDS API REQUESTS
# =============================================================================

def get_nfl_events(api_key: str) -> list[dict[str, Any]]:
    """
    Fetch current NFL events from The Odds API.
    """

    url = f"{BASE_URL}/sports/{SPORT}/events"

    params = {
        "apiKey": api_key,
    }

    logger.info("Fetching NFL events")

    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    events = response.json()

    logger.info(
        "Found %d NFL events",
        len(events),
    )

    return events

def filter_events_to_week(
    events: list[dict[str, Any]],
    season: int,
    week: int,
) -> list[dict[str, Any]]:
    """
    Filter Odds API NFL events to games belonging to a
    specific NFL season and regular-season week.

    Uses the nflverse schedule as the source of truth
    for season/week assignment.
    """

    schedule = nflverse.load_schedules(
        season=season
    )

    # -------------------------------------------------------------
    # Validate schedule columns
    # -------------------------------------------------------------

    required_columns = {
        "week",
        "home_team",
        "away_team",
    }

    missing_columns = (
        required_columns
        - set(schedule.columns)
    )

    if missing_columns:
        raise ValueError(
            "nflverse schedule is missing required "
            f"columns: {missing_columns}"
        )

    # -------------------------------------------------------------
    # Restrict schedule to requested week
    # -------------------------------------------------------------

    week_schedule = schedule[
        schedule["week"].eq(week)
    ].copy()

    if week_schedule.empty:
        logger.warning(
            "No nflverse schedule games found for "
            "season=%s week=%s",
            season,
            week,
        )

        return []

    # -------------------------------------------------------------
    # Create matchup lookup
    # -------------------------------------------------------------

    scheduled_matchups = {
        (
            row["home_team"],
            row["away_team"],
        )
        for _, row in week_schedule.iterrows()
    }

    # -------------------------------------------------------------
    # Filter Odds API events
    # -------------------------------------------------------------

    filtered_events = []

    for event in events:

        home_team = event.get(
            "home_team"
        )

        away_team = event.get(
            "away_team"
        )

        home_abbr = NFL_TEAM_NAME_TO_ABBR.get(
            home_team
        )

        away_abbr = NFL_TEAM_NAME_TO_ABBR.get(
            away_team
        )

        if home_abbr is None:
            logger.warning(
                "Unknown NFL team name from Odds API: %s",
                home_team,
            )
            continue

        if away_abbr is None:
            logger.warning(
                "Unknown NFL team name from Odds API: %s",
                away_team,
            )
            continue

        matchup = (
            home_abbr,
            away_abbr,
        )

        if matchup in scheduled_matchups:
            filtered_events.append(event)

    logger.info(
        "Filtered NFL events to season=%s week=%s: "
        "%d/%d events",
        season,
        week,
        len(filtered_events),
        len(events),
    )

    return filtered_events


def get_event_props(
    api_key: str,
    event_id: str,
) -> dict[str, Any]:
    """
    Fetch player prop odds for one NFL event.
    """

    url = (
        f"{BASE_URL}/sports/"
        f"{SPORT}/events/"
        f"{event_id}/odds"
    )

    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": ",".join(PROP_MARKETS),
        "oddsFormat": "american",
    }

    logger.info(
        "Fetching props for event %s",
        event_id,
    )

    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    logger.info(
        "Event %s -> HTTP %s",
        event_id,
        response.status_code,
    )

    # Log API usage headers when available.
    requests_used = response.headers.get("x-requests-used")
    requests_remaining = response.headers.get(
        "x-requests-remaining"
    )
    requests_last = response.headers.get(
        "x-requests-last"
    )

    if requests_used is not None:
        logger.info(
            "Odds API usage: used=%s remaining=%s last=%s",
            requests_used,
            requests_remaining,
            requests_last,
        )

    if not response.ok:
        logger.error(
            "Odds API error for event %s: %s",
            event_id,
            response.text,
        )

    response.raise_for_status()

    return response.json()


# =============================================================================
# PROP ID
# =============================================================================

def build_prop_id(
    event_id: str,
    bookmaker: str,
    market: str,
    player: str,
) -> str:
    """
    Build a stable identifier for a player prop.

    prop_id intentionally does NOT include:

        - side
        - line
        - odds
        - snapshot_time

    This means the same underlying prop keeps the same ID
    as the line or odds move over time.
    """

    normalized_player = str(player).strip().lower()

    raw_id = "|".join(
        [
            str(event_id),
            str(bookmaker),
            str(market),
            normalized_player,
        ]
    )

    return hashlib.sha256(
        raw_id.encode("utf-8")
    ).hexdigest()


# =============================================================================
# IMPLIED PROBABILITY
# =============================================================================

def american_odds_to_probability(
    american_odds: Any,
) -> float | None:
    """
    Convert American odds into implied probability.

    Positive odds:

        probability = 100 / (odds + 100)

    Negative odds:

        probability = -odds / (-odds + 100)

    Example:

        +100 -> 0.5000
        -110 -> 0.5238
        +150 -> 0.4000
    """

    if american_odds is None:
        return None

    if pd.isna(american_odds):
        return None

    try:
        odds = float(american_odds)
    except (TypeError, ValueError):
        return None

    if odds == 0:
        return None

    if odds > 0:
        return 100.0 / (odds + 100.0)

    return -odds / (-odds + 100.0)


# =============================================================================
# RAW DATA STORAGE
# =============================================================================

def save_raw_event(
    event_data,
    snapshot_time,
    event_id=None,
    season=None,
    week=None,
) -> Path:
    """
    Save the complete raw Odds API response as JSON.

    Raw files are kept so the data can be reprocessed later
    without making another API request.
    """

    RAW_PROPS_DIR.mkdir(parents=True, exist_ok=True)

    home_team = event_data.get("home_team", "HOME")
    away_team = event_data.get("away_team", "AWAY")

    date_str = snapshot_time.strftime("%Y%m%d")
    time_str = snapshot_time.strftime("%H%M%S")

    filename = (
        f"{season}_WK{week:02d}_"
        f"{away_team}_{home_team}_"
        f"{date_str}_{time_str}_{event_id}.json"
    )

    output_path = RAW_PROPS_DIR / snapshot_time.strftime("%Y-%m-%d") / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(event_data, f, indent=2)

    return output_path


# =============================================================================
# LOAD RAW EVENT (only used for offline - when api already donwloaded)
# =============================================================================

def load_raw_event(
    raw_path: Path,
) -> tuple[dict[str, Any], datetime]:
    """
    Load a previously saved raw Odds API response.

    Reconstructs the original snapshot timestamp from
    the file path and filename created by save_raw_event().
    """

    with raw_path.open(
        "r",
        encoding="utf-8",
    ) as f:
        event = json.load(f)

    # Filename format:
    #
    # {event_id}_{HHMMSS}_{microseconds}.json
    #
    # Example:
    #
    # abc123_143025_123456.json

    timestamp_parts = raw_path.stem.rsplit(
        "_",
        2,
    )

    if len(timestamp_parts) != 3:
        raise ValueError(
            f"Unexpected raw odds filename format: "
            f"{raw_path.name}"
        )

    _, time_part, microseconds = timestamp_parts

    snapshot_date = raw_path.parent.name

    snapshot_time = datetime.strptime(
        f"{snapshot_date} {time_part}_{microseconds}",
        "%Y-%m-%d %H%M%S_%f",
    ).replace(
        tzinfo=timezone.utc
    )

    return event, snapshot_time


# =============================================================================
# PROCESS EVENT (after save_raw_event() in live api | after load_raw_event() in offline ingestion)
# =============================================================================

def process_event(
    event: dict[str, Any],
    snapshot_time: datetime,
) -> pd.DataFrame:

    df = normalize_event_props(
        event=event,
        snapshot_time=snapshot_time,
    )

    append_to_parquet(df)

    return df

# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_event_props(
    event: dict[str, Any],
    snapshot_time: datetime,
) -> pd.DataFrame:
    """
    Convert the nested Odds API response into a flat DataFrame.

    One row represents one:

        event
        bookmaker
        market
        player
        side
        line
        odds
        snapshot
    """

    rows = []

    snapshot_timestamp = (
        snapshot_time.isoformat()
    )

    home_team = event.get(
        "home_team"
    )

    away_team = event.get(
        "away_team"
    )
    home_abbr = NFL_TEAM_NAME_TO_ABBR.get(
        home_team
    )

    away_abbr = NFL_TEAM_NAME_TO_ABBR.get(
        away_team
    )

    for bookmaker in event.get(
        "bookmakers",
        [],
    ):

        bookmaker_key = bookmaker.get(
            "key"
        )

        bookmaker_title = bookmaker.get(
            "title"
        )

        for market in bookmaker.get(
            "markets",
            [],
        ):

            market_key = market.get(
                "key"
            )

            last_update = market.get(
                "last_update"
            )

            for outcome in market.get(
                "outcomes",
                [],
            ):

                player_name = outcome.get(
                    "description"
                )

                side = outcome.get(
                    "name"
                )

                line = outcome.get(
                    "point"
                )

                odds = outcome.get(
                    "price"
                )


                # -------------------------------------------------------------
                # Stable prop ID
                # -------------------------------------------------------------

                prop_id = build_prop_id(
                    event_id=event.get("id"),
                    bookmaker=bookmaker_key,
                    market=market_key,
                    player=player_name,
                )

                # -------------------------------------------------------------
                # Implied probability
                # -------------------------------------------------------------

                implied_probability = (
                    american_odds_to_probability(
                        odds
                    )
                )

                # -------------------------------------------------------------
                # Player ID
                # -------------------------------------------------------------
                
                player_id = player_lookup.lookup(player_name, home_abbr, away_abbr)

                # -------------------------------------------------------------
                # Store normalized row
                # -------------------------------------------------------------
                rows.append(
                    {
                        "prop_id": prop_id,

                        "event_id": event.get(
                            "id"
                        ),

                        "sport": event.get(
                            "sport_key"
                        ),

                        "commence_time": event.get(
                            "commence_time"
                        ),
                        
                        "game_day": (
                            datetime.fromisoformat(
                                event.get("commence_time").replace("Z", "+00:00")
                            )
                            .astimezone(ZoneInfo("America/Los_Angeles"))
                            .strftime("%Y-%m-%d")
                        ),

                        "game_time": (
                            datetime.fromisoformat(
                                event.get("commence_time").replace("Z", "+00:00")
                            )
                            .astimezone(ZoneInfo("America/Los_Angeles"))
                            .strftime("%I:%M %p")
                        ),

                        "home_team": event.get(
                            "home_team"
                        ),

                        "away_team": event.get(
                            "away_team"
                        ),

                        "bookmaker": bookmaker_key,

                        "bookmaker_title": bookmaker_title,

                        "market": market_key,

                        "player_name": player_name,

                        "player_id": player_id,

                        "side": side,

                        "line": line,

                        "odds": odds,

                        "implied_probability": (
                            implied_probability
                        ),

                        "last_update": last_update,

                        "snapshot_time": (
                            snapshot_timestamp
                        ),
                    }
                )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


# =============================================================================
# PARQUET STORAGE
# =============================================================================

def append_to_parquet(
    df: pd.DataFrame,
    output_path: Path = PROPS_PARQUET,
) -> None:
    """
    Append normalized prop observations to the Parquet dataset.

    Existing observations are preserved so we can track
    line and odds movement over time.
    """

    if df.empty:
        logger.warning(
            "No normalized odds to save"
        )
        return

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # Load existing data
    # ---------------------------------------------------------

    if output_path.exists():

        existing = pd.read_parquet(
            output_path
        )

        combined = pd.concat(
            [
                existing,
                df,
            ],
            ignore_index=True,
        )

        # logger.info("Existing parquet columns: %s", list(existing.columns) if not existing.empty else [])
        # logger.info("New dataframe columns: %s", list(df.columns))
        # logger.info("Combined columns: %s", list(combined.columns))
        # logger.info("Combined shape: %s", combined.shape)

    else:

        combined = df.copy()


    # ---------------------------------------------------------
    # Remove exact duplicate observations
    # ---------------------------------------------------------
    #
    # prop_id identifies the underlying prop.
    #
    # side / line / odds / last_update / snapshot_time
    # identify the particular market observation.
    #
    # We intentionally DO NOT deduplicate only on prop_id
    # because we want to preserve line movement.
    #

    dedup_columns = [
        "prop_id",
        "side",
        "line",
        "odds",
        "last_update",
        "snapshot_time",
    ]

    rows_before_dedup = len(combined)

    combined = combined.drop_duplicates(
        subset=dedup_columns,
        keep="last",
    )

    rows_after_dedup = len(combined)
    duplicates_removed = (
        rows_before_dedup - rows_after_dedup
    )

    # ---------------------------------------------------------
    # Sort
    # ---------------------------------------------------------

    combined = combined.sort_values(
        [
            "commence_time",
            "event_id",
            "market",
            "player_name",
            "bookmaker",
            "snapshot_time",
        ]
    ).reset_index(
        drop=True
    )

    # ---------------------------------------------------------
    # Save
    # ---------------------------------------------------------

    combined.to_parquet(
        output_path,
        index=False,
    )

    logger.info(
        "Parquet update: %d rows before dedup | "
        "%d duplicates removed | "
        "%d rows saved",
        rows_before_dedup,
        duplicates_removed,
        rows_after_dedup,
    )


# =============================================================================
# SINGLE EVENT INGESTION
# =============================================================================

def ingest_event(
    api_key: str,
    event_id: str,
    season=None,
    week=None
) -> pd.DataFrame:
    """
    Fetch, save, normalize, and store one NFL event's props.
    """

    snapshot_time = datetime.now(
        timezone.utc
    )

    logger.info(
        "Ingesting event %s",
        event_id,
    )

    # ---------------------------------------------------------
    # Fetch events
    # ---------------------------------------------------------

    event = get_event_props(
        api_key=api_key,
        event_id=event_id,
    )

    # ---------------------------------------------------------
    # Save raw response
    # ---------------------------------------------------------

    save_raw_event(
        event=event,
        snapshot_time=snapshot_time,
        event_id=event_id,
        season=season,
        week=week
    )

    # New pipeline 
    return process_event(
        event=event,
        snapshot_time=snapshot_time,
    )
    # Old previous code for pipeline
    # ---------------------------------------------------------
    # Normalize
    # ---------------------------------------------------------

    # df = normalize_event_props(
    #     event=event,
    #     snapshot_time=snapshot_time,
    # )

    # ---------------------------------------------------------
    # Save processed data
    # ---------------------------------------------------------

    # append_to_parquet(
    #     df
    # )

    # return df


# =============================================================================
# ALL EVENT INGESTION
# =============================================================================

def ingest_all_events(
    api_key: str,
    season: int,
    week: int,
) -> pd.DataFrame:
    """
    Fetch current NFL events and ingest props only
    for games belonging to the requested NFL week.
    """

    # Ingests events by searching through Odds API to get event ids of NFL games
    events = get_nfl_events(
        api_key
    )
    # Store these events in data/raw/odds/events/
    # Store the complete events response as a raw snapshot
    snapshot_time = datetime.now(timezone.utc)

    RAW_EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    events_path = (
        RAW_EVENTS_DIR
        / f"{season}_WK{week:02d}_"
        / snapshot_time.strftime("%Y-%m-%d")
        / f"events_{snapshot_time.strftime('%H%M%S_%f')}.json"
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)

    with events_path.open("w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)

    print(f"Saved {len(events)} NFL events to {events_path}")

    # ---------------------------------------------------------
    # Filter events to requested NFL week
    # ---------------------------------------------------------

    # Filter events to the requested NFL week
    week_events = filter_events_to_week(
        events,
        season,
        week,
    )
    print(
        f"Found {len(week_events)} NFL events "
        f"for {season} Week {week}"
    )

    all_dataframes = []

    for event in week_events:

        event_id = event["id"]

        try:

            df = ingest_event(
                api_key=api_key,
                event_id=event_id,
                season=season,
                week=week
            )

            if not df.empty:
                all_dataframes.append(
                    df
                )

        except requests.HTTPError:

            logger.exception(
                "Failed to ingest event %s",
                event_id,
            )

        except Exception:

            logger.exception(
                "Unexpected error ingesting event %s",
                event_id,
            )

    if all_dataframes:

        return pd.concat(
            all_dataframes,
            ignore_index=True,
        )

    return pd.DataFrame()

# =============================================================================
# EVENT INGESTION FOR PREVIOUSLY SAVED DATA
# =============================================================================
def ingest_raw_file(
    raw_path: Path,
) -> pd.DataFrame:
    """
    Process a previously saved raw Odds API JSON file.

    No API requests are made.
    """

    event, snapshot_time = load_raw_event(
        raw_path
    )

    home_team = event.get("home_team", "Unknown")
    away_team = event.get("away_team", "Unknown")
    event_id = event.get("id", "Unknown")
    commence_time = event.get("commence_time", "Unknown")
    game_datetime = (
        datetime.fromisoformat(
            commence_time.replace("Z", "+00:00")
        )
        .astimezone(ZoneInfo("America/Los_Angeles"))
    )
    game_day = game_datetime.strftime("%Y-%m-%d")
    game_time = game_datetime.strftime("%I:%M %p")

    logger.info(
        "Processing %s | %s | %s | %s @ %s | event=%s | snapshot=%s",
        raw_path.name,
        game_day,
        game_time,
        away_team,
        home_team,
        event_id,
        snapshot_time.strftime("%H:%M:%S"),
    )

    df = process_event(
        event=event,
        snapshot_time=snapshot_time,
    )

    logger.info(
        "Processed: %d prop rows",
        len(df),
    )

    return df

# =============================================================================
# CLI
# =============================================================================

def parse_args():
    """
    Parse command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Ingest NFL player props "
            "from The Odds API."
        )
    )

    parser.add_argument(
        "--event-id",
        type=str,
        help=(
            "Ingest one specific NFL event."
        ),
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Ingest props for all current "
            "NFL events in the requested week."
        ),
    )

    parser.add_argument(
        "--season",
        type=int,
        # required=True,
        help=(
            "NFL season, e.g. 2026."
        ),
    )

    parser.add_argument(
        "--week",
        type=int,
        # required=True,
        help=(
            "NFL regular-season week, e.g. 4."
        ),
    )

    parser.add_argument(
        "--raw-file",
        type=Path,
        help=(
            "Process an existing raw Odds API JSON file "
            "without making an API request."
        ),
    )

    parser.add_argument(
        "--raw-dir",
        type=str,
        help="Process all raw prop JSON files in a directory without making API calls.",
    )

    return parser.parse_args()


# =============================================================================
# MAIN
# =============================================================================

def main():
    """
    Main CLI entry point.
    """

    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            # "%(levelname)s | "
            # "%(name)s | "
            "%(message)s"
        ),
    )

    # ---------------------------------------------------------
    # API key
    # ---------------------------------------------------------

    api_key = get_api_key()

    # ---------------------------------------------------------
    # Ingest
    # ---------------------------------------------------------

    if args.raw_file:

        df = ingest_raw_file(
            raw_path=args.raw_file
        )

    elif args.event_id:

        df = ingest_event(
            api_key=api_key,
            event_id=args.event_id,
        )

    elif args.all:

        if args.season is None or args.week is None:
            raise SystemExit(
                "--season and --week are required when using --all"
            )

        df = ingest_all_events(
            api_key=api_key,
            season=args.season,
            week=args.week,
        )
    elif args.raw_dir:
        raw_dir = Path(args.raw_dir)

        if not raw_dir.exists():
            raise FileNotFoundError(
                f"Raw directory does not exist: {raw_dir}"
            )

        raw_files = sorted(raw_dir.glob("*.json"))

        if not raw_files:
            print(f"No JSON files found in {raw_dir}")
            return

        print(f"Found {len(raw_files)} raw prop files.")

        frames = []

        for raw_file in raw_files:
            print(f"Processing {raw_file}")

            df = ingest_raw_file(raw_file)

            if not df.empty:
                frames.append(df)

        if frames:
            combined = pd.concat(frames, ignore_index=True)
            print(
                f"Processed {len(combined):,} prop rows "
                f"from {len(raw_files)} files."
            )
        else:
            print("No prop rows were produced.")

    else:

        raise SystemExit(
            "Specify --event-id, --all, or --raw-file"
        )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print()
    print("=" * 80)
    print("ODDS INGESTION COMPLETE")
    print("=" * 80)

    print(f"Rows processed: {len(df):,}")
    print(f"Output:         {PROPS_PARQUET}")

    if args.season is not None:
        print(f"Season:         {args.season}")

    if args.week is not None:
        print(f"Week:           {args.week}")

    if not df.empty:

        print("\nMarkets:")

        print(
            df["market"]
            .value_counts()
            .to_string()
        )

        print("\nBookmakers:")

        print(
            df["bookmaker"]
            .value_counts()
            .to_string()
        )

        print("\nSides:")

        print(
            df["side"]
            .value_counts()
            .to_string()
        )

        print("\nSample:")

        print(
            df.head(10).to_string(
                index=False
            )
        )
    
    player_lookup.log_mult_matched_names()
    player_lookup.log_unresolved_names()
    


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()