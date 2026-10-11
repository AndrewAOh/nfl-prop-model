import os
import json
from zoneinfo import ZoneInfo
import requests
import logging
import pandas as pd

from pathlib import Path
from datetime import datetime, timezone

from .player_lookup import NFLPlayerLookup
from .nflverse import NflverseAdapter



BASE_URL = "https://api.sportsgameodds.com/v2"
SOURCE = "sportsgameodds"

PLAYER_PROP_STATS = {
    "passing_yards",
    "passing_attempts",
    "passing_completions",
    "passing_touchdowns",
    "passing_interceptions",
    "passing_longestCompletion"
    "rushing_yards",
    "rushing_attempts",
    "rushing_longestRush",
    "rushing_touchdowns",
    "receiving_yards",
    "receiving_receptions",
    "receiving_targets",
    "receiving_touchdowns",
    "receiving_longestReception",
    "touchdowns",
    "firstTouchdown",
    "fantasyScore",
    
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]

RAW_PROPS_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "odds"
    / "props"
    / "sportsgameodds"
)

RAW_EVENTS_DIR = (
    PROJECT_ROOT
        / "data"
        / "raw"
        / "odds"
        / "events"
        / "sportsgameodds"
)

# Store in Interim first. Processed will have odds in a clean format
INTERIM_DIR = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "odds"
)

PROPS_PARQUET = INTERIM_DIR / "props.parquet"

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
    "Los Angeles Rams": "LAR",
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
    Get SportsGameOdds API key from the SPORTSGAMEODDS_API_KEY environment variable.
    """

    api_key = os.getenv("SPORTSGAMEODDS_API_KEY")

    if not api_key:
        raise ValueError(
            "Set the SPORTSGAMEODDS_API_KEY environment variable."
        )
    return api_key


def get_team_abbr(team: dict) -> str | None:
    """Map a SportsGameOdds team object to an nflverse abbreviation."""

    name = get_team_name(team)

    if not name:
        return None

    # Accept either a full team name or an existing abbreviation.
    if name in NFL_TEAM_NAME_TO_ABBR:
        return NFL_TEAM_NAME_TO_ABBR[name]

    known_abbreviations = set(NFL_TEAM_NAME_TO_ABBR.values())
    if name in known_abbreviations:
        return name

    # Handle provider-specific team IDs if they are abbreviations.
    team_id = team.get("teamID") if isinstance(team, dict) else None

    if team_id in known_abbreviations:
        return team_id

    logger.warning("Unknown SportsGameOdds team: %s", name)
    return None


def filter_events_to_week(
    events: list[dict],
    season: int,
    week: int,
) -> list[dict]:
    """Filter SportsGameOdds events using the nflverse schedule."""

    schedule = nflverse.load_schedules(season=season)

    required = {"week", "home_team", "away_team"}
    missing = required - set(schedule.columns)

    if missing:
        raise ValueError(
            f"nflverse schedule is missing columns: {missing}"
        )

    week_schedule = schedule.loc[
        schedule["week"].eq(week)
        & schedule["season"].eq(season)
    ]

    scheduled_matchups = set(
        zip(
            week_schedule["home_team"],
            week_schedule["away_team"],
        )
    )

    filtered = []

    for event in events:
        teams = event.get("teams") or {}

        home_abbr = get_team_abbr(teams.get("home") or {})
        away_abbr = get_team_abbr(teams.get("away") or {})

        if (home_abbr, away_abbr) in scheduled_matchups:
            event["_nfl_season"] = season
            event["_nfl_week"] = week
            filtered.append(event)

    logger.info(
        "Filtered NFL events to season=%s week=%s: %d/%d events",
        season,
        week,
        len(filtered),
        len(events),
    )

    return filtered


def american_to_implied_probability(odds):
    """Convert American odds to raw implied probability."""
    if odds is None:
        return None

    try:
        odds = float(odds)
    except (TypeError, ValueError):
        return None

    if odds == 0:
        return None

    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (abs(odds) + 100)


def get_team_name(team):
    """Extract a readable team name when available."""
    if not isinstance(team, dict):
        return None

    names = team.get("names") or {}

    return (
        names.get("long")
        or names.get("short")
        or team.get("teamID")
    )


def save_raw_event(
    event_data: dict,
    snapshot_time: datetime,
    season: int,
    week: int,
    raw_dir,
) -> Path:
    """Save one raw SportsGameOdds event response."""
    RAW_PROPS_DIR = raw_dir

    RAW_PROPS_DIR.mkdir(parents=True, exist_ok=True)

    status = event_data.get("status") or {}
    teams = event_data.get("teams") or {}

    home = get_team_name(teams.get("home") or {}) or "HOME"
    away = get_team_name(teams.get("away") or {}) or "AWAY"
    event_id = event_data.get("eventID", "unknown")

    safe_away = away.replace(" ", "-")
    safe_home = home.replace(" ", "-")

    filename = (
        f"{season}_WK{week:02d}_"
        f"{safe_away}_{safe_home}_"
        f"{snapshot_time.strftime('%Y%m%d_%H%M%S_%f')}_"
        f"{event_id}.json"
    )

    output_path = (
        RAW_PROPS_DIR
        / snapshot_time.strftime("%Y-%m-%d")
        / filename
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(event_data, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw event response: %s", output_path)

    return output_path

def process_event(
    event: dict,
    snapshot_time: datetime,
) -> pd.DataFrame:
    """Normalize one previously fetched SportsGameOdds event."""

    return normalize_events(
        events=[event],
        snapshot_time=snapshot_time.isoformat(),
    )


def append_to_parquet(
    df: pd.DataFrame,
    output_path: Path = PROPS_PARQUET,
) -> None:
    """Append observations while preserving historical line movement."""

    if df.empty:
        logger.warning("No normalized odds to save")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        existing = pd.read_parquet(output_path)
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df.copy()

    dedup_columns = [
        "prop_id",
        "side",
        "line",
        "odds",
        "last_update",
        "snapshot_time",
    ]

    before = len(combined)

    combined = combined.drop_duplicates(
        subset=dedup_columns,
        keep="last",
    )

    removed = before - len(combined)

    sort_columns = [
        "commence_time",
        "source",
        "event_id",
        "market",
        "player_name",
        "bookmaker",
        "snapshot_time",
    ]

    combined = combined.sort_values(
        sort_columns,
        na_position="last",
    ).reset_index(drop=True)

    # Ensure the line column has a consistent numeric dtype.
    for column in ["line", "odds", "implied_probability"]:
        if column in combined.columns:
            combined[column] = pd.to_numeric(
                combined[column],
                errors="coerce",
            )

    combined.to_parquet(output_path, index=False)

    logger.info(
        "Parquet update: %d rows before dedup | "
        "%d duplicates removed | %d rows saved",
        before,
        removed,
        len(combined),
    )

def fetch_events(
    raw_dir: Path,
    api_key: str,
    limit: int = 100,
) -> tuple[list[dict], str]:
    """Fetch paginated NFL events and preserve raw JSON responses."""

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    headers = {"x-api-key": api_key}
    params = {
        "leagueID": "NFL",
        "oddsAvailable": "true",
        "limit": limit,
    }

    events = []
    page_num = 1
    snapshot_time = datetime.now(timezone.utc).isoformat()

    logger.info("Fetching NFL events from SportsGameOdds")

    while True:
        try:
            response = requests.get(
                f"{BASE_URL}/events",
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            logger.info(
                "SportsGameOdds events page %d -> HTTP %s",
                page_num,
                response.status_code,
            )

            # Log API usage headers if SportsGameOdds provides them.
            credit_headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if any(term in key.lower() for term in ("credit", "request", "quota", "rate"))
            }

            if credit_headers:
                logger.info(
                    "SportsGameOdds API usage headers | page=%d | %s",
                    page_num,
                    credit_headers,
                )
            else:
                logger.debug(
                    "No recognizable credit-usage headers returned for page %d",
                    page_num,
                )

            if not response.ok:
                logger.error(
                    "SportsGameOdds API error: %s",
                    response.text,
                )

            response.raise_for_status()

            payload = response.json()

        except requests.RequestException:
            logger.exception(
                "Failed to fetch SportsGameOdds page %d",
                page_num,
            )
            raise

        raw_file = raw_dir / f"page_{page_num}.json"
        raw_file.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        page_events = payload.get("data", [])
        events.extend(page_events)

        logger.info(
            "Page %d: %d events | saved %s",
            page_num,
            len(page_events),
            raw_file,
        )

        cursor = payload.get("nextCursor")

        if not cursor or not page_events:
            break

        params["cursor"] = cursor
        page_num += 1

    logger.info(
        "Found %d NFL events across %d pages",
        len(events),
        page_num,
    )

    return events, snapshot_time


def create_player_resolution_tracker():
    return {
        "matched": {},
        "unresolved": set(),
    }


def normalize_events(events, snapshot_time):
    """
    Convert SportsGameOdds events into the shared prop schema.
    One row represents one market outcome at one bookmaker.
    """
    rows = []

    for event in events:
        event_id = event.get("eventID")
        status = event.get("status") or {}
        teams = event.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}

        home_name = get_team_name(home)
        away_name = get_team_name(away)

        players = event.get("players") or {}
        odds_tree = event.get("odds") or {}

        
        # Define team abbreviations before iterating through odds.
        home_abbr = NFL_TEAM_NAME_TO_ABBR.get(home_name)
        away_abbr = NFL_TEAM_NAME_TO_ABBR.get(away_name)

        players = event.get("players") or {}
        odds_tree = event.get("odds") or {}

        for odd_id, market in odds_tree.items():
            if not isinstance(market, dict):
                continue

            parts = odd_id.split("-")
            if len(parts) < 5:
                continue

            stat = parts[0]
            sgo_player_id = "-".join(parts[1:-3])
            period_id = parts[-3]
            bet_type = parts[-2]
            side = parts[-1]

            if stat not in PLAYER_PROP_STATS:
                continue

            # SportsGameOdds ID, not the canonical nflverse ID.
            player = players.get(sgo_player_id) or {}

            player_name = (
                player.get("name")
                or player.get("displayName")
                or sgo_player_id
            )

            # Ignore non-player labels returned by SportsGameOdds.
            if str(player_name).strip().lower() in {"all", "home", "away"}:
                continue

            # Canonical nflverse GSIS ID.
            player_id = player_lookup.lookup(
                player_name,
                home_abbr,
                away_abbr,
            )

            # The docs specify odds.<oddID>.byBookmaker.<bookmakerID>.
            books = market.get("byBookmaker") or {}

            for bookmaker, price in books.items():
                if not isinstance(price, dict):
                    continue

                if price.get("available") is False:
                    continue

                american_odds = price.get("odds")

                line = (
                    price.get("overUnder")
                    or price.get("spread")
                )

                # Prefer a stable market ID; keep snapshots distinct
                # using the snapshot_time column.
                prop_id = (
                    f"{event_id}|{odd_id}|{bookmaker}"
                )

                rows.append({
                    "prop_id": prop_id,
                    "source": SOURCE,
                    "event_id": event_id,
                    "sport": "NFL",
                    "commence_time": status.get("startsAt"),
                    "game_day": (
                        datetime.fromisoformat(
                           status.get("startsAt").replace("Z", "+00:00")
                        )
                        .astimezone(ZoneInfo("America/Los_Angeles"))
                        .strftime("%Y-%m-%d")
                    ),
                    "game_time": (
                        datetime.fromisoformat(
                            status.get("startsAt").replace("Z", "+00:00")
                        )
                        .astimezone(ZoneInfo("America/Los_Angeles"))
                        .strftime("%I:%M %p")
                    ), 
                    "home_team": home_name,
                    "away_team": away_name,
                    "bookmaker": bookmaker,
                    "bookmaker_title": bookmaker,
                    "market": stat,
                    "player_name": player_name,
                    "player_id": player_id,
                    "side": side,
                    "line": line,
                    "odds": american_odds,
                    "implied_probability":
                        american_to_implied_probability(
                            american_odds
                        ),
                    "last_update": price.get("lastUpdatedAt"),
                    "snapshot_time": snapshot_time,
                    "period_id": period_id,
                    "bet_type": bet_type,
                    "available": price.get("available"),
                })

    return pd.DataFrame(rows)

def player_lookup_log_mult_matched_names():
    player_lookup.log_mult_matched_names()
        

def player_lookup_log_unresolved_names():
    player_lookup.log_unresolved_names()