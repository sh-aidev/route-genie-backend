import asyncio
import time

from src.core.tools.flights import get_all_flights
from src.core.tools.hotels_google import get_google_hotels
from src.core.tools.hotels_rapidapi import get_rapidapi_hotels
from src.core.tools.itinerary import create_itinerary
from src.core.tools.location import get_location_details
from src.core.tools.nearest_airport import get_nearest_airport
from src.core.tools.weather import get_weather
from src.utils.logger import logger
from src.utils.models import (
    HotelOption,
    ItineraryRequest,
    ItineraryResponse,
    ToolCallMeta,
)


def _skipped_meta(tool: str, reason: str = "Skipped — airport resolution failed") -> ToolCallMeta:
    now = time.time()
    return ToolCallMeta(
        tool=tool, status="skipped",
        started_at=now, completed_at=now, duration_ms=0, error=reason,
    )


def _merge_hotels(
    google: list[HotelOption],
    booking: list[HotelOption],
    max_results: int = 10,
) -> list[HotelOption]:
    """
    Combine both hotel sources and rank by best value:
      1. Stars descending  (higher star = better)
      2. Rating descending (higher rating = better)
      3. Price ascending   (cheaper = better)
    Hotels with no price info are ranked last.
    """
    combined = google + booking
    combined.sort(key=lambda h: (
        -(h.stars or 0),
        -(h.rating or 0.0),
        h.price_per_night if h.price_per_night is not None else float("inf"),
    ))
    return combined[:max_results]


async def run_itinerary_agent(req: ItineraryRequest) -> ItineraryResponse:
    logger.info(
        f"Agent started | origin={req.origin!r} → destination={req.location!r} "
        f"| {req.from_date} → {req.to_date} | budget={req.budget} {req.currency}"
    )

    # ── Phase 1: parallel data gathering ──────────────────────────────────────
    (
        (location, loc_meta),
        (weather, weather_meta),
        (origin_airport, origin_airport_meta),
        (dest_airport, dest_airport_meta),
    ) = await asyncio.gather(
        get_location_details(req.location),
        get_weather(req.location, req.from_date, req.to_date),
        get_nearest_airport(req.origin, role="origin"),
        get_nearest_airport(req.location, role="destination"),
    )

    loc_meta            = loc_meta.model_copy(update={"phase": 1, "parallel": True})
    weather_meta        = weather_meta.model_copy(update={"phase": 1, "parallel": True})
    origin_airport_meta = origin_airport_meta.model_copy(update={"phase": 1, "parallel": True})
    dest_airport_meta   = dest_airport_meta.model_copy(update={"phase": 1, "parallel": True})

    errors: dict[str, str] = {}
    if loc_meta.status == "error":
        errors["location"] = loc_meta.error or "Location lookup failed"
    if weather_meta.status == "error":
        errors["weather"] = weather_meta.error or "Weather fetch failed"
    if origin_airport_meta.status == "error":
        errors["origin_airport"] = origin_airport_meta.error or "Origin airport resolution failed"
    if dest_airport_meta.status == "error":
        errors["destination_airport"] = dest_airport_meta.error or "Destination airport resolution failed"

    # ── Phase 2: parallel flight + hotel search ────────────────────────────────
    # All 4 run concurrently; flights need resolved IATA codes, hotels need location.
    if origin_airport and dest_airport:
        (
            (flights,         duffel_meta),
            (google_hotels,   google_hotels_meta),
            (booking_hotels,  booking_hotels_meta),
        ) = await asyncio.gather(
            get_all_flights(
                origin_iata=origin_airport.iata_code,
                dest_iata=dest_airport.iata_code,
                from_date=req.from_date,
                to_date=req.to_date,
                budget=req.budget,
                passengers=req.passengers,
            ),
            get_google_hotels(
                location=req.location,
                from_date=req.from_date,
                to_date=req.to_date,
                budget=req.budget,
                currency=req.currency,
            ),
            get_rapidapi_hotels(
                location=req.location,
                from_date=req.from_date,
                to_date=req.to_date,
                budget=req.budget,
                currency=req.currency,
                passengers=req.passengers,
            ),
        )
        flights.sort(key=lambda f: float(f.total_amount))
    else:
        flights, google_hotels, booking_hotels = [], [], []
        duffel_meta         = _skipped_meta("get_all_flights")
        google_hotels_meta  = _skipped_meta("get_google_hotels", "Skipped — location resolution failed")
        booking_hotels_meta = _skipped_meta("get_rapidapi_hotels", "Skipped — location resolution failed")
        errors["flights"] = "Skipped — airport resolution failed"

    if duffel_meta.status == "error":
        errors["flights"] = duffel_meta.error or "Flight search failed"
    if google_hotels_meta.status == "error":
        errors["google_hotels"] = google_hotels_meta.error or "Google hotel search failed"
    if booking_hotels_meta.status == "error":
        errors["booking_hotels"] = booking_hotels_meta.error or "Booking.com hotel search failed"

    # Tag Phase 2 — all parallel
    duffel_meta         = duffel_meta.model_copy(update={"phase": 2, "parallel": True})
    google_hotels_meta  = google_hotels_meta.model_copy(update={"phase": 2, "parallel": True})
    booking_hotels_meta = booking_hotels_meta.model_copy(update={"phase": 2, "parallel": True})

    hotels = _merge_hotels(google_hotels, booking_hotels)

    logger.info(
        f"Flights: {len(flights)} total | "
        f"Hotels: {len(google_hotels)} google + {len(booking_hotels)} booking = {len(hotels)} total"
    )

    # ── Phase 3: LLM synthesis ────────────────────────────────────────────────
    itinerary, itin_meta = await create_itinerary(
        location=location,
        flights=flights,
        hotels=hotels,
        weather=weather,
        from_date=req.from_date,
        to_date=req.to_date,
        budget=req.budget,
        currency=req.currency,
    )
    if itin_meta.status == "error":
        errors["itinerary"] = itin_meta.error or "Itinerary generation failed"

    itin_meta = itin_meta.model_copy(update={"phase": 3, "parallel": False})

    logger.info(f"Agent complete | errors={list(errors.keys()) or 'none'}")

    return ItineraryResponse(
        itinerary=itinerary,
        flights=flights,
        hotels=hotels,
        weather=weather,
        location=location,
        origin_airport=origin_airport,
        destination_airport=dest_airport,
        flow_metadata=[
            loc_meta,
            weather_meta,
            origin_airport_meta,
            dest_airport_meta,
            duffel_meta,
            google_hotels_meta,
            booking_hotels_meta,
            itin_meta,
        ],
        errors=errors,
    )
