import time
import httpx

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import LocationDetails, ToolCallMeta

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


async def get_location_details(location: str) -> tuple[LocationDetails | None, ToolCallMeta]:
    started_at = time.time()
    tool = "get_location_details"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                GEOCODE_URL,
                params={"address": location, "key": settings.google_location_api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("results"):
            raise ValueError(f"No geocoding results for: {location!r}")

        result = data["results"][0]
        geo = result["geometry"]["location"]

        country = next(
            (c["long_name"] for c in result.get("address_components", []) if "country" in c["types"]),
            "",
        )

        details = LocationDetails(
            name=location,
            formatted_address=result.get("formatted_address", location),
            lat=geo["lat"],
            lng=geo["lng"],
            country=country,
        )

        completed_at = time.time()
        return details, ToolCallMeta(
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
