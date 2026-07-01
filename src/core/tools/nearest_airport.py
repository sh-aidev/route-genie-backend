import re
import time

from openai import AsyncOpenAI

from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import NearestAirport, ToolCallMeta

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_client = AsyncOpenAI(api_key=settings.openai_api_key)


async def get_nearest_airport(
    location: str,
    role: str = "origin",  # "origin" | "destination" — used in flow metadata label
) -> tuple[NearestAirport | None, ToolCallMeta]:
    """
    Resolves a city name, address, or raw IATA code to the nearest commercial airport.
    Uses an LLM structured-output call so it handles place names, neighbourhoods,
    tourist spots, and ambiguous inputs gracefully.
    If the input is already a 3-letter IATA code it is returned immediately.
    """
    started_at = time.time()
    tool = f"get_nearest_airport_{role}"

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

    try:
        # Short-circuit: input is already a valid IATA code
        code = location.strip().upper()
        if _IATA_RE.match(code):
            logger.info(f"{tool}: {location!r} is already an IATA code → {code}")
            return NearestAirport(iata_code=code, name=code, city_name=code), _meta("success")

        # LLM call with structured output
        user_msg = f"Find the nearest commercial airport to: {location}"
        logger.info(
            f"[LLM INPUT] tool={tool} model=gpt-4o-mini temperature=0 response_format=NearestAirport | "
            f"user_message={user_msg!r}"
        )

        response = await _client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an aviation and geography expert. "
                        "Given any city, region, tourist destination, or place name, "
                        "identify the nearest commercial airport that handles passenger flights. "
                        "Return the airport's official IATA code, full airport name, "
                        "the city it serves, and the city's IATA city code if it differs from the airport code."
                    ),
                },
                {
                    "role": "user",
                    "content": user_msg,
                },
            ],
            response_format=NearestAirport,
            temperature=0,
        )

        airport = response.choices[0].message.parsed
        if airport is None:
            raise ValueError("LLM returned empty structured output")

        usage = response.usage
        logger.info(
            f"[LLM OUTPUT] tool={tool} model=gpt-4o-mini finish_reason={response.choices[0].finish_reason} | "
            f"tokens: prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens} | "
            f"resolved: {location!r} → iata={airport.iata_code} name={airport.name!r} city={airport.city_name!r}"
        )
        return airport, _meta("success")

    except Exception as exc:
        logger.error(f"{tool} failed: {exc}")
        return None, _meta("error", str(exc))
