import time
import uuid
from datetime import datetime

import httpx

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import HotelOption, ToolCallMeta

RAPIDAPI_HOST = "booking-com15.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}"


def _headers() -> dict[str, str]:
    return {
        "x-rapidapi-key": settings.rapidapi_key,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }


def _nights(from_date: str, to_date: str) -> int:
    return max(
        (datetime.strptime(to_date, "%Y-%m-%d") - datetime.strptime(from_date, "%Y-%m-%d")).days,
        1,
    )


async def get_rapidapi_hotels(
    location: str,
    from_date: str,
    to_date: str,
    budget: float,
    currency: str = "USD",
    passengers: int = 1,
    max_results: int = 10,
) -> tuple[list[HotelOption], ToolCallMeta]:
    started_at = time.time()
    tool = "get_rapidapi_hotels"

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

    if not settings.rapidapi_key:
        logger.warning(f"{tool}: RAPIDAPI_KEY not set — skipping")
        return [], _meta("skipped", "RAPIDAPI_KEY not configured")

    nights = _nights(from_date, to_date)
    hotel_budget = budget * 0.35

    def _403_msg() -> str:
        return (
            "Booking.com (v15) subscription required — "
            "subscribe at https://rapidapi.com/DataCrawler/api/booking-com15"
        )

    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=15) as client:
            # Step 1 — resolve city name to dest_id
            loc_resp = await client.get(
                f"{RAPIDAPI_BASE}/api/v1/hotels/searchDestination",
                params={"query": location},
            )
            if loc_resp.status_code in (403, 429):
                msg = _403_msg() if loc_resp.status_code == 403 else "RapidAPI rate limit hit (429) — retry later"
                logger.warning(f"{tool}: {msg}")
                return [], _meta("skipped", msg)
            if loc_resp.status_code >= 400:
                logger.error(f"{tool} searchDestination {loc_resp.status_code}: {loc_resp.text[:300]}")
            loc_resp.raise_for_status()

            loc_body = loc_resp.json()
            destinations = loc_body.get("data", [])
            if not destinations:
                raise ValueError(f"No Booking.com destination found for: {location!r}")

            dest = next(
                (d for d in destinations if d.get("dest_type") in ("city", "region")),
                destinations[0],
            )
            dest_id   = dest["dest_id"]
            dest_type = dest.get("dest_type", "city")
            logger.info(f"{tool}: resolved {location!r} → dest_id={dest_id} ({dest_type})")

            # Step 2 — search hotels
            search_resp = await client.get(
                f"{RAPIDAPI_BASE}/api/v1/hotels/searchHotels",
                params={
                    "dest_id": dest_id,
                    "search_type": dest_type.upper(),
                    "arrival_date": from_date,
                    "departure_date": to_date,
                    "adults": passengers,
                    "room_qty": 1,
                    "currency_code": currency.upper(),
                    "languagecode": "en-us",
                    "sort_by": "popularity",
                },
            )
            if search_resp.status_code in (403, 429):
                msg = _403_msg() if search_resp.status_code == 403 else "RapidAPI rate limit hit (429) — retry later"
                logger.warning(f"{tool}: {msg}")
                return [], _meta("skipped", msg)
            if search_resp.status_code >= 400:
                logger.error(f"{tool} searchHotels {search_resp.status_code}: {search_resp.text[:300]}")
            search_resp.raise_for_status()

            raw_hotels = search_resp.json().get("data", {}).get("hotels", [])

        hotels: list[HotelOption] = []
        for h in raw_hotels:
            prop = h.get("property", {})

            # Price
            price_bd  = prop.get("priceBreakdown", {})
            gross     = price_bd.get("grossPrice", {})
            total     = float(gross.get("value") or 0)
            per_night = round(total / nights, 2) if total else None
            h_currency = gross.get("currency", currency)

            if total and total > hotel_budget * 1.2:
                continue

            # Rating — reviewScore is 0–10; normalise to 0–5
            raw_score = prop.get("reviewScore")
            rating = round(float(raw_score) / 2, 1) if raw_score else None

            # Stars
            stars = None
            star_data = h.get("basicPropertyData", {}).get("starRating", {})
            if star_data.get("value"):
                stars = int(star_data["value"])
            elif prop.get("qualityClass"):
                stars = int(prop["qualityClass"])

            photos = prop.get("photoUrls", [])

            hotels.append(
                HotelOption(
                    id=str(h.get("hotel_id", uuid.uuid4())),
                    name=prop.get("name", ""),
                    address=prop.get("wishlistName", ""),
                    rating=rating,
                    stars=stars,
                    price_per_night=per_night,
                    total_price=round(total, 2) if total else None,
                    currency=h_currency,
                    source="booking",
                    review_count=prop.get("reviewCount"),
                    image_url=photos[0] if photos else None,
                    lat=float(prop["latitude"]) if prop.get("latitude") else None,
                    lng=float(prop["longitude"]) if prop.get("longitude") else None,
                )
            )
            if len(hotels) >= max_results:
                break

        logger.info(f"{tool}: {len(hotels)} hotels from Booking.com for {location!r}")
        return hotels, _meta("success")

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        return [], _meta("error", str(exc))
