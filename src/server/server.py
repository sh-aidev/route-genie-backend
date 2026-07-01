import httpx
import uvicorn
from fastapi import FastAPI, APIRouter, Query
from fastapi.middleware.cors import CORSMiddleware

from src.core.agent import run_itinerary_agent
from src.utils.config import settings
from src.utils.logger import logger
from src.utils.models import ItineraryRequest, ItineraryResponse


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/itinerary/create", response_model=ItineraryResponse, status_code=200)
    async def create_itinerary(req: ItineraryRequest) -> ItineraryResponse:
        logger.info(f"POST /itinerary/create — {req.location}")
        return await run_itinerary_agent(req)

    @router.get("/places/autocomplete")
    async def places_autocomplete(query: str = Query(..., min_length=2)):
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/autocomplete/json",
                params={
                    "input": query,
                    "types": "geocode",
                    "key": settings.google_location_api_key,
                },
            )
        predictions = resp.json().get("predictions", [])
        return [
            {"description": p["description"], "place_id": p["place_id"]}
            for p in predictions
        ]

    @router.get("/health")
    async def health():
        return {"status": "ok"}

    return router


class RouteGenieServer:
    def __init__(self) -> None:
        self.app = FastAPI(
            title="Route Genie API",
            description="AI-powered travel itinerary generator",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.include_router(_build_router(), prefix="/api/v1")

    def run(self) -> None:
        uvicorn.run(
            self.app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
