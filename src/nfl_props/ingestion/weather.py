from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


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
    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(
        self,
        timeout: tuple[int, int] = (5, 30),
        max_retries: int = 3,
    ):
        self.timeout = timeout

        self.session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def get_game_weather(
        self,
        team: str,
        kickoff_at: datetime,
    ) -> Dict[str, Any]:
        """
        Retrieve hourly weather data for a game.

        The API returns timestamps in UTC. The game kickoff is converted
        to UTC before determining the requested date.
        """

        stadium = STADIUMS.get(team)

        if stadium is None:
            return {
                "weather_available": False,
                "reason": f"Unknown stadium for team: {team}",
            }

        if stadium.roof_type == "dome":
            return {
                "weather_available": False,
                "reason": "Indoor dome",
            }

        if stadium.roof_type == "retractable":
            return {
                "weather_available": False,
                "reason": "Retractable roof; roof state unavailable",
            }

        # Ensure kickoff is timezone-aware.
        if kickoff_at.tzinfo is None:
            raise ValueError(
                "kickoff_at must be timezone-aware"
            )

        # Convert local kickoff time to UTC.
        kickoff_utc = kickoff_at.astimezone(timezone.utc)

        # Use the UTC date because the API response is in UTC.
        date_string = kickoff_utc.date().isoformat()

        params = {
            "latitude": stadium.latitude,
            "longitude": stadium.longitude,
            "start_date": date_string,
            "end_date": date_string,
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "rain",
                    "snowfall",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                    "wind_direction_10m",
                    "weather_code",
                ]
            ),
            "timezone": "UTC",
        }

        start_time = time.monotonic()

        try:
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout,
            )

            elapsed = time.monotonic() - start_time

            logger.debug(
                "Open-Meteo request completed: team=%s date=%s "
                "status=%s duration=%.2fs",
                team,
                date_string,
                response.status_code,
                elapsed,
            )

            response.raise_for_status()

            weather_data = response.json()

            return {
                "weather_available": True,
                "team": team,
                "stadium": stadium.name,
                "latitude": stadium.latitude,
                "longitude": stadium.longitude,
                "roof_type": stadium.roof_type,
                "requested_date": date_string,
                "hourly": weather_data.get("hourly", {}),
            }

        except requests.exceptions.Timeout as exc:
            elapsed = time.monotonic() - start_time

            logger.warning(
                "Open-Meteo timeout: team=%s date=%s "
                "duration=%.2fs error=%s",
                team,
                date_string,
                elapsed,
                exc,
            )

            return {
                "weather_available": False,
                "reason": "Request timeout",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        except requests.exceptions.HTTPError as exc:
            elapsed = time.monotonic() - start_time

            status_code = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            logger.warning(
                "Open-Meteo HTTP error: team=%s date=%s "
                "status=%s duration=%.2fs error=%s",
                team,
                date_string,
                status_code,
                elapsed,
                exc,
            )

            return {
                "weather_available": False,
                "reason": "HTTP error",
                "status_code": status_code,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        except requests.exceptions.RequestException as exc:
            elapsed = time.monotonic() - start_time

            logger.warning(
                "Open-Meteo request failed: team=%s date=%s "
                "duration=%.2fs error=%s",
                team,
                date_string,
                elapsed,
                exc,
            )

            return {
                "weather_available": False,
                "reason": "Request error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

        except ValueError as exc:
            logger.warning(
                "Invalid JSON from Open-Meteo: team=%s date=%s error=%s",
                team,
                date_string,
                exc,
            )

            return {
                "weather_available": False,
                "reason": "Invalid API response",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

def select_kickoff_weather(
    hourly_weather: Dict[str, Any],
    kickoff_at: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Select the weather observation closest to kickoff.

    Open-Meteo timestamps are returned as naive UTC timestamps.
    """

    if not hourly_weather:
        return None

    timestamps = hourly_weather.get("time", [])

    if not timestamps:
        logger.warning("Weather response contained no timestamps")
        return None

    if kickoff_at.tzinfo is None:
        raise ValueError(
            "kickoff_at must be timezone-aware"
        )

    # Convert kickoff to UTC and remove timezone information so it can
    # be compared to the API's naive UTC timestamps.
    kickoff_utc_naive = (
        kickoff_at
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    parsed_timestamps = []

    for timestamp in timestamps:
        try:
            parsed_timestamps.append(
                datetime.fromisoformat(timestamp)
            )
        except ValueError:
            parsed_timestamps.append(None)

    valid_timestamps = [
        timestamp
        for timestamp in parsed_timestamps
        if timestamp is not None
    ]

    if not valid_timestamps:
        logger.warning("Could not parse weather timestamps")
        return None

    # Select the closest hourly observation.
    selected_timestamp = min(
        valid_timestamps,
        key=lambda timestamp: abs(
            timestamp - kickoff_utc_naive
        ),
    )

    selected_index = parsed_timestamps.index(
        selected_timestamp
    )

    selected_weather = {
        "timestamp": timestamps[selected_index],
    }

    # Extract the corresponding value from every weather variable.
    for variable, values in hourly_weather.items():
        if variable == "time":
            continue

        if selected_index < len(values):
            selected_weather[variable] = values[selected_index]
        else:
            selected_weather[variable] = None

    return selected_weather

from nfl_props.ingestion.weather import (
    OpenMeteoClient,
    select_kickoff_weather,
)


def get_weather_for_game(
    home_team: str,
    gameday: str,
    gametime: str,
    client: Optional[OpenMeteoClient] = None,
) -> Dict[str, Any]:
    """
    Retrieve and select weather for a specific NFL game.
    """

    from zoneinfo import ZoneInfo

    should_close_client = client is None

    if client is None:
        client = OpenMeteoClient()

    try:
        # Adjust the format if your schedule uses a different time format.
        kickoff_naive = datetime.strptime(
            f"{gameday} {gametime}",
            "%Y-%m-%d %H:%M",
        )

        kickoff_at = kickoff_naive.replace(
            tzinfo=ZoneInfo("America/New_York")
        )

        weather_response = client.get_game_weather(
            team=home_team,
            kickoff_at=kickoff_at,
        )

        if not weather_response.get("weather_available", False):
            return {
                "weather_available": False,
                "reason": weather_response.get(
                    "reason",
                    "Weather unavailable",
                ),
                "error_type": weather_response.get("error_type"),
                "error_message": weather_response.get(
                    "error_message"
                ),
            }

        hourly_weather = weather_response.get("hourly", {})

        selected_weather = select_kickoff_weather(
            hourly_weather=hourly_weather,
            kickoff_at=kickoff_at,
        )

        if selected_weather is None:
            return {
                "weather_available": False,
                "reason": "Could not select kickoff weather",
            }

        return {
            "weather_available": True,
            "weather_timestamp": selected_weather.get("timestamp"),
            "temperature_2m": selected_weather.get("temperature_2m"),
            "relative_humidity_2m": selected_weather.get(
                "relative_humidity_2m"
            ),
            "precipitation": selected_weather.get("precipitation"),
            "rain": selected_weather.get("rain"),
            "snowfall": selected_weather.get("snowfall"),
            "wind_speed_10m": selected_weather.get("wind_speed_10m"),
            "wind_gusts_10m": selected_weather.get("wind_gusts_10m"),
            "wind_direction_10m": selected_weather.get(
                "wind_direction_10m"
            ),
            "weather_code": selected_weather.get("weather_code"),
        }

    except (ValueError, TypeError) as exc:
        logger.warning(
            "Could not parse kickoff time: team=%s "
            "gameday=%s gametime=%s error=%s",
            home_team,
            gameday,
            gametime,
            exc,
        )

        return {
            "weather_available": False,
            "reason": "Invalid kickoff datetime",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }

    finally:
        if should_close_client:
            client.close()