from __future__ import annotations

from datetime import date
import requests


class OpenMeteoClient:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def get_forecast(self, latitude: float, longitude: float, target_date: date) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_speed_10m_max"],
            "timezone": "UTC",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        }
        response = requests.get(self.BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
