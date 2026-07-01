import time
import httpx

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import FlightOption, FlightSegment, FlightSlice, ToolCallMeta

DUFFEL_BASE = "https://api.duffel.com"


def _duffel_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.duffel_api_key}",
        "Duffel-Version": "v2",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse_offers(raw_offers: list[dict], budget: float, max_results: int) -> list[FlightOption]:
    flights: list[FlightOption] = []
    for offer in raw_offers:
        if len(flights) >= max_results:
            break
        amount = float(offer.get("total_amount", 0))
        if amount > budget:
            continue

        slices = []
        for sl in offer.get("slices", []):
            segments = [
                FlightSegment(
                    origin=seg.get("origin", {}).get("iata_code", ""),
                    destination=seg.get("destination", {}).get("iata_code", ""),
                    departing_at=seg.get("departing_at", ""),
                    arriving_at=seg.get("arriving_at", ""),
                    marketing_carrier=seg.get("marketing_carrier", {}).get("name", ""),
                    duration=seg.get("duration"),
                )
                for seg in sl.get("segments", [])
            ]
            slices.append(
                FlightSlice(
                    origin=sl.get("origin", {}).get("iata_code", ""),
                    destination=sl.get("destination", {}).get("iata_code", ""),
                    duration=sl.get("duration"),
                    segments=segments,
                )
            )

        flights.append(
            FlightOption(
                id=offer["id"],
                total_amount=offer.get("total_amount", "0"),
                total_currency=offer.get("total_currency", "USD"),
                slices=slices,
                source="duffel",
            )
        )
    return flights


async def get_all_flights(
    origin_iata: str,
    dest_iata: str,
    from_date: str,
    to_date: str,
    budget: float,
    passengers: int = 1,
    max_results: int = 5,
) -> tuple[list[FlightOption], ToolCallMeta]:
    """
    Searches for round-trip flights using pre-resolved IATA codes.
    Both origin_iata and dest_iata must already be resolved airport/city codes.
    """
    started_at = time.time()
    tool = "get_all_flights"

    try:
        logger.info(f"Flight search: {origin_iata} ↔ {dest_iata} ({from_date} / {to_date}), budget={budget}")

        payload = {
            "data": {
                "slices": [
                    {"origin": origin_iata, "destination": dest_iata, "departure_date": from_date},
                    {"origin": dest_iata, "destination": origin_iata, "departure_date": to_date},
                ],
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": "economy",
            }
        }
        logger.debug(f"Duffel payload: {payload}")

        async with httpx.AsyncClient(headers=_duffel_headers(), timeout=30) as client:
            offer_req_resp = await client.post(
                f"{DUFFEL_BASE}/air/offer_requests",
                json=payload,
                params={"return_offers": "false"},
            )
            if offer_req_resp.status_code >= 400:
                logger.error(f"Duffel offer_requests {offer_req_resp.status_code}: {offer_req_resp.text}")
            offer_req_resp.raise_for_status()
            offer_request_id = offer_req_resp.json()["data"]["id"]

            offers_resp = await client.get(
                f"{DUFFEL_BASE}/air/offers",
                params={
                    "offer_request_id": offer_request_id,
                    "sort": "total_amount",
                    "limit": max_results * 3,
                },
            )
            if offers_resp.status_code >= 400:
                logger.error(f"Duffel offers {offers_resp.status_code}: {offers_resp.text}")
            offers_resp.raise_for_status()
            raw_offers = offers_resp.json().get("data", [])

        flights = _parse_offers(raw_offers, budget, max_results)
        logger.info(f"Found {len(raw_offers)} raw offers, {len(flights)} within budget")

        completed_at = time.time()
        return flights, ToolCallMeta(
            tool=tool,
            status="success",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
        )

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        completed_at = time.time()
        return [], ToolCallMeta(
            tool=tool,
            status="error",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
            error=str(exc),
        )
