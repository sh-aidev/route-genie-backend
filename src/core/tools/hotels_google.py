import time
import uuid

import httpx

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import HotelOption, ToolCallMeta

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"

# Google price_level (0–4) mapped to approximate USD/night midpoints
_PRICE_LEVEL_MAP = {1: 50.0, 2: 100.0, 3: 200.0, 4: 375.0}


def _photo_url(photo_reference: str) -> str:
    return (
        f"{PLACES_PHOTO_URL}?maxwidth=600"
        f"&photoreference={photo_reference}"
        f"&key={settings.google_location_api_key}"
    )


async def get_google_hotels(
    location: str,
    from_date: str,
    to_date: str,
    budget: float,
    currency: str = "USD",
    max_results: int = 10,
) -> tuple[list[HotelOption], ToolCallMeta]:
    started_at = time.time()
    tool = "get_google_hotels"

    def _meta(status: str, error: str | None = None) -> ToolCallMeta:
        completed_at = time.time()
        return ToolCallMeta(
            tool=tool,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
            error=error,
        )

    async def _places_search(client: httpx.AsyncClient, query: str, with_type: bool) -> list:
        params: dict = {"query": query, "key": settings.google_location_api_key}
        if with_type:
            params["type"] = "lodging"
        resp = await client.get(PLACES_TEXT_SEARCH_URL, params=params)
        if resp.status_code >= 400:
            logger.error(f"{tool} {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
        data = resp.json()
        api_status = data.get("status", "UNKNOWN")
        if api_status not in ("OK", "ZERO_RESULTS"):
            raise ValueError(f"Google Places API error: {api_status} — {data.get('error_message', '')}")
        return data.get("results", [])

    try:
        logger.info(f"{tool}: searching hotels in {location!r}")
        async with httpx.AsyncClient(timeout=10) as client:
            # Attempt 1: typed lodging search (most precise)
            results = await _places_search(client, f"hotels in {location}", with_type=True)
            if results:
                logger.info(f"{tool}: type=lodging returned {len(results)} results for {location!r}")
            else:
                logger.info(f"{tool}: type=lodging returned 0 results for {location!r} — retrying with broader text search")
                # Attempt 2: plain text search (catches resorts, guesthouses, etc.)
                results = await _places_search(client, f"best hotels in {location}", with_type=False)
                logger.info(f"{tool}: broad text search returned {len(results)} results for {location!r}")

        hotels: list[HotelOption] = []
        for place in results:
            price_level = place.get("price_level")
            est_price = _PRICE_LEVEL_MAP.get(price_level) if price_level else None

            photos = place.get("photos", [])
            img = _photo_url(photos[0]["photo_reference"]) if photos else None

            geo = place.get("geometry", {}).get("location", {})
            raw_rating = place.get("rating")

            hotel = HotelOption(
                id=place.get("place_id", str(uuid.uuid4())),
                name=place["name"],
                address=place.get("formatted_address", ""),
                rating=round(raw_rating, 1) if raw_rating else None,
                stars=None,
                price_per_night=est_price,
                currency="USD",
                source="google",
                review_count=place.get("user_ratings_total"),
                image_url=img,
                lat=geo.get("lat"),
                lng=geo.get("lng"),
            )
            hotels.append(hotel)
            logger.info(
                f"{tool}: [{len(hotels)}] {hotel.name!r} | "
                f"rating={hotel.rating} ({hotel.review_count or 0} reviews) | "
                f"est. ${hotel.price_per_night}/night | photo={'yes' if img else 'no'}"
            )
            if len(hotels) >= max_results:
                break

        logger.info(f"{tool}: done — {len(hotels)} hotels returned for {location!r}")
        return hotels, _meta("success")

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        return [], _meta("error", str(exc))
