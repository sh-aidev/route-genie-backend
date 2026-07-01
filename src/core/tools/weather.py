import time
from collections import defaultdict
from datetime import datetime, timedelta

import httpx

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import ToolCallMeta, WeatherEntry, WeatherSummary

OPENWEATHER_BASE = "https://api.openweathermap.org/data/2.5"


def _aggregate_daily(forecast_list: list[dict], from_dt: datetime, to_dt: datetime) -> dict:
    """Aggregate 3-hour forecast slots into daily summaries within [from_dt, to_dt]."""
    daily: dict[str, dict[str, list]] = defaultdict(
        lambda: {"temps": [], "descriptions": [], "humidities": []}
    )
    for entry in forecast_list:
        dt = datetime.utcfromtimestamp(entry["dt"])
        if from_dt.date() <= dt.date() <= to_dt.date():
            date_key = dt.strftime("%Y-%m-%d")
            daily[date_key]["temps"].append(entry["main"]["temp"])
            daily[date_key]["descriptions"].append(entry["weather"][0]["description"])
            daily[date_key]["humidities"].append(entry["main"]["humidity"])
    return daily


def _daily_to_entries(daily: dict) -> list[WeatherEntry]:
    return [
        WeatherEntry(
            date=date,
            description=max(set(v["descriptions"]), key=v["descriptions"].count),
            temp_min=round(min(v["temps"]), 1),
            temp_max=round(max(v["temps"]), 1),
            humidity=int(sum(v["humidities"]) / len(v["humidities"])),
        )
        for date, v in sorted(daily.items())
        if v["temps"]
    ]


async def get_weather(
    location: str, from_date: str, to_date: str
) -> tuple[WeatherSummary | None, ToolCallMeta]:
    started_at = time.time()
    tool = "get_weather"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{OPENWEATHER_BASE}/forecast",
                params={
                    "q": location,
                    "appid": settings.openweather_api_key,
                    "units": "metric",
                    "cnt": 40,  # max 5-day / 3-hour slots
                },
            )
            resp.raise_for_status()
            data = resp.json()

        city_name = data.get("city", {}).get("name", location)
        forecast_list = data.get("list", [])

        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt   = datetime.strptime(to_date,   "%Y-%m-%d")

        # Try to get entries matching the actual travel dates
        daily = _aggregate_daily(forecast_list, from_dt, to_dt)
        entries = _daily_to_entries(daily)

        forecast_label = city_name
        if not entries:
            # Travel dates are beyond the 5-day forecast window — show what we have
            logger.info(
                f"Weather: no forecast data for travel dates {from_date}→{to_date} "
                f"(likely >5 days out). Falling back to available forecast."
            )
            now = datetime.utcnow()
            fallback_to = now + timedelta(days=5)
            daily = _aggregate_daily(forecast_list, now, fallback_to)
            entries = _daily_to_entries(daily)
            if entries:
                forecast_label = f"{city_name} (current forecast — travel dates beyond 5-day window)"

        # Last resort: current conditions if forecast is also empty
        if not entries:
            logger.info(f"Weather: forecast empty, trying current conditions for {location}")
            async with httpx.AsyncClient(timeout=10) as client:
                cur_resp = await client.get(
                    f"{OPENWEATHER_BASE}/weather",
                    params={
                        "q": location,
                        "appid": settings.openweather_api_key,
                        "units": "metric",
                    },
                )
                cur_resp.raise_for_status()
                cur = cur_resp.json()
            entries = [
                WeatherEntry(
                    date=datetime.utcnow().strftime("%Y-%m-%d"),
                    description=cur["weather"][0]["description"],
                    temp_min=round(cur["main"]["temp_min"], 1),
                    temp_max=round(cur["main"]["temp_max"], 1),
                    humidity=cur["main"]["humidity"],
                )
            ]
            forecast_label = f"{city_name} (current conditions)"

        summary = WeatherSummary(location=forecast_label, entries=entries)

        completed_at = time.time()
        return summary, ToolCallMeta(
            tool=tool,
            status="success",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
        )

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        completed_at = time.time()
        return None, ToolCallMeta(
            tool=tool,
            status="error",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
            error=str(exc),
        )
