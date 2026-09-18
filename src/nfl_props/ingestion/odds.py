from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import pandas as pd
import requests


class OddsApiClient:
    """Optional Odds API client. Keep this module replaceable and rate-limit aware."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_API_BASE_URL", "https://api.the-odds-api.com/v4")

    def get_events(self, sport: str = "americanfootball_nfl", regions: str = "us") -> list[dict]:
        if not self.api_key:
            raise RuntimeError("ODDS_API_KEY is not configured")
        url = f"{self.base_url}/sports/{sport}/events"
        response = requests.get(url, params={"apiKey": self.api_key, "regions": regions}, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_player_props(self, event_id: str, markets: str = "player_reception_yds,player_receptions") -> list[dict]:
        if not self.api_key:
            raise RuntimeError("ODDS_API_KEY is not configured")
        url = f"{self.base_url}/sports/americanfootball_nfl/events/{event_id}/odds"
        params = {"apiKey": self.api_key, "regions": "us", "markets": markets, "oddsFormat": "american"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def flatten_snapshot(payload: list[dict], observed_at: datetime | None = None) -> pd.DataFrame:
        observed_at = observed_at or datetime.now(timezone.utc)
        rows: list[dict] = []
        for event in payload:
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        rows.append({
                            "event_id": event.get("id"),
                            "commence_time": event.get("commence_time"),
                            "bookmaker": bookmaker.get("key"),
                            "market_key": market.get("key"),
                            "player_name": outcome.get("description") or outcome.get("name"),
                            "outcome_name": outcome.get("name"),
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                            "observed_at": observed_at.isoformat(),
                        })
        return pd.DataFrame(rows)


def load_manual_odds_csv(path: str | Path) -> pd.DataFrame:
    """Load manually collected odds using a stable minimum schema."""
    df = pd.read_csv(path)
    required = {"game_id", "player_id", "market_type", "line", "price", "sportsbook", "observed_at"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Manual odds file is missing columns: {sorted(missing)}")
    return df
