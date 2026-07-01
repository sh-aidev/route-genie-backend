import time
from openai import AsyncOpenAI

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import FlightOption, HotelOption, LocationDetails, ToolCallMeta, WeatherSummary

_client = AsyncOpenAI(api_key=settings.openai_api_key)


def _build_prompt(
    location: LocationDetails | None,
    flights: list[FlightOption],
    hotels: list[HotelOption],
    weather: WeatherSummary | None,
    from_date: str,
    to_date: str,
    budget: float,
    currency: str,
) -> str:
    dest_name = location.formatted_address if location else "the destination"
    lines = [
        f"Generate a detailed day-by-day travel itinerary for a trip to **{dest_name}**.",
        f"Travel dates: {from_date} → {to_date}",
        f"Total budget: {budget} {currency}",
        "",
    ]

    if location:
        lines += [
            "## Destination",
            f"- Address: {location.formatted_address}",
            f"- Country: {location.country}",
            f"- Coordinates: {location.lat:.4f}, {location.lng:.4f}",
            "",
        ]

    if flights:
        lines.append("## Available Flights (within budget)")
        for i, f in enumerate(flights[:3], 1):
            lines.append(f"**Option {i}** — {f.total_amount} {f.total_currency}")
            for sl in f.slices:
                for seg in sl.segments:
                    lines.append(
                        f"  - {seg.marketing_carrier}: {seg.origin} → {seg.destination}"
                        f"  |  Departs {seg.departing_at}  |  Arrives {seg.arriving_at}"
                        + (f"  |  Duration {seg.duration}" if seg.duration else "")
                    )
        lines.append("")
    else:
        lines += ["## Flights", "No flights found within budget — exclude flight costs from plan.", ""]

    if hotels:
        lines.append("## Recommended Hotels (sorted best value first)")
        for i, h in enumerate(hotels[:5], 1):
            stars_str  = f"{'★' * h.stars}" if h.stars else "unrated"
            rating_str = f"{h.rating}/5" if h.rating else "no rating"
            price_str  = f"~{h.currency} {h.price_per_night:.0f}/night" if h.price_per_night else "price unavailable"
            reviews    = f" ({h.review_count} reviews)" if h.review_count else ""
            lines.append(f"**{i}. {h.name}** [{stars_str}] — {rating_str}{reviews} — {price_str} (via {h.source})")
            lines.append(f"   {h.address}")
        lines.append("")
    else:
        lines += ["## Hotels", "No hotel data available — suggest local accommodation options based on the area.", ""]

    if weather and weather.entries:
        lines.append("## Weather Forecast")
        for e in weather.entries:
            lines.append(
                f"- {e.date}: {e.description.capitalize()}, {e.temp_min}°C – {e.temp_max}°C, humidity {e.humidity}%"
            )
        lines.append("")

    lines += [
        "## Itinerary Requirements",
        "For each day provide:",
        "- Morning, afternoon, and evening activities with specific venue/place names",
        "- Breakfast, lunch, and dinner recommendations with restaurant names",
        "- Estimated cost per activity and meal",
        "- Local transport tips",
        "- Weather-appropriate packing advice where relevant",
        "- Recommend which listed hotel to stay at and why (based on rating + budget fit)",
        "",
        "End with a **Budget Breakdown** table (flights, accommodation, food, activities, misc).",
        "Keep total spend within the stated budget. Format everything as clean, readable Markdown.",
    ]

    return "\n".join(lines)


_MODEL = "gpt-4o-mini"
_SYSTEM_PROMPT = (
    "You are an expert travel planner. Create detailed, practical, and budget-conscious "
    "travel itineraries. Use only the data provided — do not invent flight details."
)


async def create_itinerary(
    location: LocationDetails | None,
    flights: list[FlightOption],
    hotels: list[HotelOption],
    weather: WeatherSummary | None,
    from_date: str,
    to_date: str,
    budget: float,
    currency: str = "USD",
) -> tuple[str, ToolCallMeta]:
    started_at = time.time()
    tool = "create_itinerary"

    try:
        prompt = _build_prompt(location, flights, hotels, weather, from_date, to_date, budget, currency)

        logger.info(
            f"[LLM INPUT] model={_MODEL} max_tokens=2500 temperature=0.7 | "
            f"context: dest={location.formatted_address if location else 'unknown'} "
            f"dates={from_date}→{to_date} budget={budget}{currency} "
            f"flights={len(flights)} hotels={len(hotels)} weather_days={len(weather.entries) if weather else 0} | "
            f"prompt_chars={len(prompt)} system_chars={len(_SYSTEM_PROMPT)}"
        )

        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            temperature=0.7,
        )

        itinerary = response.choices[0].message.content or ""
        usage = response.usage

        logger.info(
            f"[LLM OUTPUT] model={_MODEL} finish_reason={response.choices[0].finish_reason} | "
            f"tokens: prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens} | "
            f"output_chars={len(itinerary)} | preview: {itinerary[:120].replace(chr(10), ' ')!r}"
        )

        completed_at = time.time()
        return itinerary, ToolCallMeta(
            tool=tool,
            status="success",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
        )

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        completed_at = time.time()
        return f"Itinerary generation failed: {exc}", ToolCallMeta(
            tool=tool,
            status="error",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(completed_at - started_at) * 1000,
            error=str(exc),
        )
