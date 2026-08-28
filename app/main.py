from fastapi import FastAPI

from app.admin import router as admin_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="WohnWerk",
    description="Austria-first home and job matching service",
    version="0.1.0",
)
app.include_router(admin_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "wohnwerk",
        "country": settings.country_code,
        "ai_enabled": settings.ai_enabled,
    }
