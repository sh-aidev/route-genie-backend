from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


# ── Request ──────────────────────────────────────────────────────────────────

class ItineraryRequest(BaseModel):
    location: str = Field(..., description="Destination city or place name (e.g. 'Paris', 'Tokyo', 'CCU')")
    origin: str = Field("New York", description="Origin city or location (e.g. 'New York', 'London', 'JFK')")
    from_date: str = Field(..., description="Departure date (YYYY-MM-DD)")
    to_date: str = Field(..., description="Return date (YYYY-MM-DD)")
    budget: float = Field(..., description="Total travel budget")
    currency: str = Field("USD", description="Budget currency code")
    passengers: int = Field(1, ge=1, le=9)


# ── Tool output models ────────────────────────────────────────────────────────

class NearestAirport(BaseModel):
    iata_code: str
    name: str
    city_name: str
    iata_city_code: Optional[str] = None


class LocationDetails(BaseModel):
    name: str
    formatted_address: str
    lat: float
    lng: float
    country: str
    description: Optional[str] = None


class FlightSegment(BaseModel):
    origin: str
    destination: str
    departing_at: str
    arriving_at: str
    marketing_carrier: str
    duration: Optional[str] = None


class FlightSlice(BaseModel):
    origin: str
    destination: str
    duration: Optional[str] = None
    segments: list[FlightSegment]


class FlightOption(BaseModel):
    id: str
    total_amount: str
    total_currency: str
    slices: list[FlightSlice]
    source: str = "duffel"  # "duffel" | "rapidapi" — lets the UI show provider badges


class WeatherEntry(BaseModel):
    date: str
    description: str
    temp_min: float
    temp_max: float
    humidity: int


class WeatherSummary(BaseModel):
    location: str
    unit: str = "celsius"
    entries: list[WeatherEntry]


class HotelOption(BaseModel):
    id: str
    name: str
    address: str
    rating: Optional[float] = None       # 0–5 scale (normalised from source)
    stars: Optional[int] = None          # official star classification 1–5
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None  # total for stay duration
    currency: str = "USD"
    source: str = "google"              # "google" | "booking"
    review_count: Optional[int] = None
    image_url: Optional[str] = None
    booking_url: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


# ── Flow metadata (for frontend diagram) ─────────────────────────────────────

class ToolCallMeta(BaseModel):
    tool: str
    status: str          # "success" | "error" | "skipped"
    started_at: float
    completed_at: float
    duration_ms: float
    error: Optional[str] = None
    phase: int = 1       # execution phase (1, 2, 3 …) — defines vertical ordering in diagram
    parallel: bool = False  # True → tool ran concurrently with others in the same phase


# ── Response ──────────────────────────────────────────────────────────────────

class ItineraryResponse(BaseModel):
    itinerary: str
    flights: list[FlightOption]
    hotels: list[HotelOption] = []
    weather: Optional[WeatherSummary] = None
    location: Optional[LocationDetails] = None
    origin_airport: Optional[NearestAirport] = None
    destination_airport: Optional[NearestAirport] = None
    flow_metadata: list[ToolCallMeta]
    errors: dict[str, str] = {}
