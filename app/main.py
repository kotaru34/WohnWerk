from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.admin import router as admin_router
from app.catalog import router as catalog_router
from app.config import get_settings
from app.http_normalization import NormalizeHouseQueryMiddleware
from app.matches import router as matches_router
from app.ops import router as ops_router
from app.product_ui import router as product_ui_router
from app.product_ui_middleware import ProductUiMiddleware
from app.property_page_liveness import PropertyPageLivenessMiddleware
from app.site import router as site_router
from app.version import __version__

settings = get_settings()

app = FastAPI(
    title="WohnWerk",
    description="Austria-first home and job matching service",
    version=__version__,
)
app.add_middleware(PropertyPageLivenessMiddleware)
app.add_middleware(ProductUiMiddleware)
app.add_middleware(NormalizeHouseQueryMiddleware)
app.include_router(product_ui_router)
app.include_router(catalog_router)
app.include_router(site_router)
app.include_router(admin_router)
app.include_router(ops_router)
app.include_router(matches_router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/houses", status_code=307)


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "wohnwerk",
        "version": __version__,
        "country": settings.country_code,
        "ai_enabled": settings.ai_enabled,
    }
