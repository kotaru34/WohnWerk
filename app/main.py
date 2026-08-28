from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.admin import router as admin_router
from app.catalog import router as catalog_router
from app.config import get_settings
from app.matches import router as matches_router
from app.site import router as site_router

settings = get_settings()

app = FastAPI(
    title="WohnWerk",
    description="Austria-first home and job matching service",
    version="0.1.0",
)
app.include_router(catalog_router)
app.include_router(site_router)
app.include_router(admin_router)
app.include_router(matches_router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/houses", status_code=307)


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "wohnwerk",
        "country": settings.country_code,
        "ai_enabled": settings.ai_enabled,
    }
