import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from database import close_db, get_db_status, init_db
from routes import analytics, auth, cart, home, orders, products

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(
    os.getenv("STATIC_DIR", str(BASE_DIR / "static"))
).expanduser().resolve()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
if ENVIRONMENT not in {"development", "testing", "staging", "production"}:
    raise RuntimeError(
        "ENVIRONMENT must be development, testing, staging, or production."
    )

IS_PRODUCTION = ENVIRONMENT == "production"
HOST = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"

try:
    PORT = int(os.getenv("PORT", "8000"))
except ValueError as exc:
    raise RuntimeError("PORT must be a valid integer.") from exc

if not 1 <= PORT <= 65535:
    raise RuntimeError("PORT must be between 1 and 65535.")

DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173,"
    "http://127.0.0.1:5173,"
    "http://localhost:5174,"
    "http://127.0.0.1:5174,"
    "http://localhost:3000,"
    "http://127.0.0.1:3000"
)
raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "" if IS_PRODUCTION else DEFAULT_DEV_ORIGINS,
)
ALLOWED_ORIGINS = sorted({
    origin.strip().rstrip("/")
    for origin in raw_origins.split(",")
    if origin.strip()
})

if "*" in ALLOWED_ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS cannot contain '*'; use exact origins.")

for origin in ALLOWED_ORIGINS:
    if not origin.startswith(("http://", "https://")):
        raise RuntimeError(f"Invalid frontend origin: {origin!r}")
    authority = origin.split("://", 1)[1]
    if "/" in authority or "?" in origin or "#" in origin or "*" in origin:
        raise RuntimeError(
            f"Invalid origin {origin!r}; provide scheme and host only, no path."
        )

LOG_LEVEL = os.getenv(
    "LOG_LEVEL", "INFO" if IS_PRODUCTION else "DEBUG"
).strip().upper()
if LOG_LEVEL not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
    LOG_LEVEL = "INFO"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
)
logger = logging.getLogger("EGB_Backyard_API")

for relative in ("uploads/avatars", "uploads/products", "uploads/events"):
    (STATIC_DIR / relative).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting EGB Backyard API (%s)", ENVIRONMENT)
    logger.info("Static files directory: %s", STATIC_DIR)
    app.state.startup_complete = False

    try:
        await init_db()
        db_status = await get_db_status()
        if db_status != "CONNECTED":
            raise RuntimeError(f"MongoDB readiness check failed: {db_status}")

        app.state.startup_complete = True
        logger.info("Database initialization completed.")
        yield
    except Exception:
        logger.exception("Application startup or runtime failed.")
        raise
    finally:
        app.state.startup_complete = False
        await close_db()
        logger.info("EGB Backyard API shutdown completed.")


# ---------------------------------------------------------------------------
# FastAPI application and middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EGB Backyard API",
    version="1.2.0",
    description=(
        "API for EGB Backyard poultry products, customer accounts, orders, "
        "cart, analytics, and storefront content."
    ),
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-CSRF-Token",
    ],
    expose_headers=["Content-Type", "Content-Length"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if IS_PRODUCTION and os.getenv(
        "ENABLE_HSTS", "false"
    ).strip().lower() == "true":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. Please try again later.",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


# Static assets are served from STATIC_DIR at /static/...
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR), check_dir=True, html=False),
    name="static",
)

# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------

app.include_router(home.router, prefix="/api/v1/home", tags=["Home Content"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(products.router, prefix="/api/v1/products", tags=["Products"])
app.include_router(orders.router, prefix="/api/v1/orders", tags=["Orders"])
app.include_router(
    analytics.router, prefix="/api/v1/analytics", tags=["Analytics"]
)
app.include_router(
    cart.router,
    prefix="/api/v1",
    tags=["Cart, Settings, Promotions & Events"],
)


@app.get("/", tags=["Telemetry"])
async def root():
    return {
        "app": "EGB Backyard API",
        "status": "online",
        "environment": ENVIRONMENT,
    }


@app.get("/health", tags=["Telemetry"])
async def health_check():
    db_status = await get_db_status()
    healthy = db_status == "CONNECTED"
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content={
            "app": "EGB Backyard API",
            "status": "healthy" if healthy else "unhealthy",
            "database": db_status,
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=(not IS_PRODUCTION and ENVIRONMENT == "development"),
        workers=1,
        log_level=LOG_LEVEL.lower(),
    )
