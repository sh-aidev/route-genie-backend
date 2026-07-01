from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    google_api_key: str
    google_location_api_key: str
    duffel_api_key: str
    openweather_api_key: str
    rapidapi_key: str = ""      # RapidAPI key — subscribe at rapidapi.com/apidojo/api/booking-com

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


settings = Settings()
