from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests


@dataclass(frozen=True)
class Stadium:
    name: str
    latitude: float
    longitude: float
    roof_type: str  # "outdoor", "retractable", or "dome"


# Coordinates are approximate stadium locations.
# Keep this mapping version-controlled and update it when stadiums change.
STADIUMS: dict[str, Stadium] = {
    "ARI": Stadium("State Farm Stadium", 33.5276, -112.2626, "retractable"),
    "ATL": Stadium("Mercedes-Benz Stadium", 33.7554, -84.4009, "retractable"),
    "BAL": Stadium("M&T Bank Stadium", 39.2780, -76.6227, "outdoor"),
    "BUF": Stadium("Highmark Stadium", 42.7738, -78.7868, "outdoor"),
    "CAR": Stadium("Bank of America Stadium", 35.2258, -80.8528, "outdoor"),
    "CHI": Stadium("Soldier Field", 41.8623, -87.6167, "outdoor"),
    "CIN": Stadium("Paycor Stadium", 39.0954, -84.5160, "outdoor"),
    "CLE": Stadium("Huntington Bank Field", 41.5061, -81.6995, "outdoor"),
    "DAL": Stadium("AT&T Stadium", 32.7473, -97.0945, "retractable"),
    "DEN": Stadium("Empower Field at Mile High", 39.7439, -105.0201, "outdoor"),
    "DET": Stadium("Ford Field", 42.3400, -83.0456, "dome"),
    "GB": Stadium("Lambeau Field", 44.5013, -88.0622, "outdoor"),
    "HOU": Stadium("NRG Stadium", 29.6847, -95.4107, "retractable"),
    "IND": Stadium("Lucas Oil Stadium", 39.7601, -86.1639, "retractable"),
    "JAX": Stadium("EverBank Stadium", 30.3239, -81.6373, "outdoor"),
    "KC": Stadium("GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "outdoor"),
    "LV": Stadium("Allegiant Stadium", 36.0909, -115.1833, "dome"),
    "LAC": Stadium("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "LA": Stadium("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "LAR": Stadium("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "MIA": Stadium("Hard Rock Stadium", 25.9580, -80.2389, "outdoor"),
    "MIN": Stadium("U.S. Bank Stadium", 44.9738, -93.2575, "dome"),
    "NE": Stadium("Gillette Stadium", 42.0909, -71.2643, "outdoor"),
    "NO": Stadium("Caesars Superdome", 29.9511, -90.0812, "dome"),
    "NYG": Stadium("MetLife Stadium", 40.8135, -74.0745, "outdoor"),
    "NYJ": Stadium("MetLife Stadium", 40.8135, -74.0745, "outdoor"),
    "PHI": Stadium("Lincoln Financial Field", 39.9008, -75.1675, "outdoor"),
    "PIT": Stadium("Acrisure Stadium", 40.4468, -80.0158, "outdoor"),
    "SEA": Stadium("Lumen Field", 47.5952, -122.3316, "outdoor"),
    "SF": Stadium("Levi's Stadium", 37.4033, -121.9694, "outdoor"),
    "TB": Stadium("Raymond James Stadium", 27.9759, -82.5033, "outdoor"),
    "TEN": Stadium("Nissan Stadium", 36.1665, -86.7713, "outdoor"),
    "WAS": Stadium("Northwest Stadium", 38.9076, -76.8645, "outdoor"),
}


class OpenMeteoClient:
    """
    Retrieves hourly historical weather from Open-Meteo.

    Historical games should use the archive endpoint.
    """

    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def get_game_weather(
        self,
        team: str,
        kickoff_at: datetime,
    ) -> Optional[dict]:
        stadium = STADIUMS.get(team)

        if stadium is None:
            raise ValueError(f"No stadium metadata found for team: {team}")

        # Indoor stadiums do not expose meaningful outdoor game conditions.
        if stadium.roof_type == "dome":
            return {
                "stadium": stadium.name,
                "roof_type": stadium.roof_type,
                "weather_available": False,
                "reason": "Indoor dome",
            }
        elif stadium.roof_type == "retractable":
            return {
                "stadium": stadium.name,
                "roof_type": stadium.roof_type,
                "weather_available": False,
                "reason": "Indoor dome",
            }

        date_string = kickoff_at.date().isoformat()

        params = {
            "latitude": stadium.latitude,
            "longitude": stadium.longitude,
            "start_date": date_string,
            "end_date": date_string,
            "hourly": [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "rain",
                "snowfall",
                "wind_speed_10m",
                "wind_gusts_10m",
                "wind_direction_10m",
                "weather_code",
            ],
            "timezone": "UTC",
        }

        response = requests.get(
            self.BASE_URL,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        weather = response.json()

        return {
            "stadium": stadium.name,
            "latitude": stadium.latitude,
            "longitude": stadium.longitude,
            "roof_type": stadium.roof_type,
            "weather_available": True,
            "kickoff_at": kickoff_at.isoformat(),
            "hourly_weather": weather.get("hourly", {}),
        }

def select_kickoff_weather(
    hourly_weather: dict,
    kickoff_at: datetime,
) -> dict:
    timestamps = hourly_weather.get("time", [])

    if not timestamps:
        return {}

    kickoff_timestamp = kickoff_at.replace(
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()

    # Open-Meteo may format timestamps without timezone information.
    kickoff_timestamp = kickoff_timestamp.replace("+00:00", "")

    try:
        index = timestamps.index(kickoff_timestamp)
    except ValueError:
        # Fallback to the closest available hour.
        parsed_times = [
            datetime.fromisoformat(timestamp)
            for timestamp in timestamps
        ]

        index = min(
            range(len(parsed_times)),
            key=lambda i: abs(parsed_times[i] - kickoff_at.replace(tzinfo=None)),
        )

    result = {}

    for field, values in hourly_weather.items():
        if field == "time":
            continue

        if index < len(values):
            result[field] = values[index]

    return result

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nfl_props.ingestion.weather import (
    OpenMeteoClient,
    select_kickoff_weather,
)


def get_weather_for_game(
    game: dict,
    client: OpenMeteoClient | None = None,
) -> dict:
    if client is None:
        client = OpenMeteoClient()

    gameday = game["gameday"]
    gametime = game["gametime"]

    if isinstance(gameday, datetime):
        game_date = gameday.date()
    else:
        game_date = datetime.fromisoformat(
            str(gameday)
        ).date()

    kickoff_at = datetime.strptime(
        f"{game_date} {gametime}",
        "%Y-%m-%d %H:%M",
    ).replace(
        tzinfo=ZoneInfo("America/New_York")
    )

    weather_result = client.get_game_weather(
        team=game["home_team"],
        kickoff_at=kickoff_at,
    )

    if not weather_result:
        return {
            "game_id": game["game_id"],
            "weather_available": False,
        }

    if not weather_result["weather_available"]:
        return {
            "game_id": game["game_id"],
            **weather_result,
        }

    kickoff_weather = select_kickoff_weather(
        weather_result["hourly_weather"],
        kickoff_at,
    )

    return {
        "game_id": game["game_id"],
        "season": game.get("season"),
        "week": game.get("week"),
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "kickoff_at": kickoff_at,
        "weather_available": True,
        **kickoff_weather,
    }