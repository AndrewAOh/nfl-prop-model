from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from player_lookup import NFLPlayerLookup


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

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_PROPS_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "odds"
    / "props"
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
    event: dict[str, Any],
    snapshot_time: datetime,
) -> Path:
    """
    Save the complete raw Odds API response as JSON.

    Raw files are kept so the data can be reprocessed later
    without making another API request.
    """

    snapshot_date = snapshot_time.strftime(
        "%Y-%m-%d"
    )

    # Include microseconds so two snapshots taken during
    # the same second cannot overwrite one another.
    snapshot_stamp = snapshot_time.strftime(
        "%H%M%S_%f"
    )

    output_dir = (
        RAW_PROPS_DIR
        / snapshot_date
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    event_id = event["id"]

    output_path = (
        output_dir
        / f"{event_id}_{snapshot_stamp}.json"
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            event,
            f,
            indent=2,
        )

    logger.info(
        "Saved raw odds: %s",
        output_path,
    )

    return output_path


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
                
                player_id = player_lookup.lookup(player_name)

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

    combined = combined.drop_duplicates(
        subset=dedup_columns,
        keep="last",
    )

    # ---------------------------------------------------------
    # Sort
    # ---------------------------------------------------------

    combined = combined.sort_values(
        [
            "commence_time",
            "event_id",
            "market",
            "player",
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
        "Saved %d total prop observations to %s",
        len(combined),
        output_path,
    )


# =============================================================================
# SINGLE EVENT INGESTION
# =============================================================================

def ingest_event(
    api_key: str,
    event_id: str,
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
    # Fetch
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
    )

    # ---------------------------------------------------------
    # Normalize
    # ---------------------------------------------------------

    df = normalize_event_props(
        event=event,
        snapshot_time=snapshot_time,
    )

    # ---------------------------------------------------------
    # Save processed data
    # ---------------------------------------------------------

    append_to_parquet(
        df
    )

    return df


# =============================================================================
# ALL EVENT INGESTION
# =============================================================================

def ingest_all_events(
    api_key: str,
) -> pd.DataFrame:
    """
    Fetch all current NFL events and ingest their props.
    """

    events = get_nfl_events(
        api_key
    )

    all_dataframes = []

    for event in events:

        event_id = event["id"]

        try:

            df = ingest_event(
                api_key=api_key,
                event_id=event_id,
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
            "NFL events."
        ),
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
            "%(levelname)s | "
            "%(name)s | "
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

    if args.event_id:

        df = ingest_event(
            api_key=api_key,
            event_id=args.event_id,
        )

    elif args.all:

        df = ingest_all_events(
            api_key=api_key
        )

    else:

        raise SystemExit(
            "Specify either "
            "--event-id EVENT_ID "
            "or --all"
        )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print("=" * 80)
    print("ODDS INGESTION COMPLETE")
    print("=" * 80)

    print(
        f"Rows ingested: {len(df):,}"
    )

    print(
        f"Output: {PROPS_PARQUET}"
    )

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


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()