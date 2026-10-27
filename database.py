import os
import sys
import logging

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("CC_Database_Layer")

# ---------------------------------------------------------
# ENVIRONMENT CONFIGURATION
# ---------------------------------------------------------

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

DB_NAME = os.getenv("MONGO_DB_NAME", "cc_telemetry").strip()
MONGO_URI = os.getenv("MONGODB_URI", "").strip()

if not MONGO_URI:
    raise RuntimeError(
        "MONGODB_URI is missing. Check your .env file."
    )

if not DB_NAME:
    raise RuntimeError(
        "MONGO_DB_NAME cannot be empty."
    )

# ---------------------------------------------------------
# DOCUMENT MODELS
# StorePartsDocument is intentionally omitted because
# the parts model was removed from this project.
# ---------------------------------------------------------

try:
    from models import (
        User,
        Product,
        Order,
        Coupon,
        TaxSettingDocument,
        HomeContent,
        AdminUser,
    )

    try:
        from models import EventDocument
    except ImportError:
        from models import Event as EventDocument

except ImportError as exc:
    logger.critical(
        "Could not import required document models: %s",
        exc,
        exc_info=True,
    )
    raise

DOCUMENT_MODELS = [
    User,
    Product,
    Order,
    Coupon,
    TaxSettingDocument,
    HomeContent,
    EventDocument,
    AdminUser,
]

# ---------------------------------------------------------
# MONGODB CLIENT
# Use the standard mongodb:// URI with all three Atlas
# hosts to avoid the failing SRV DNS lookup in Termux.
# TLS certificate verification remains enabled.
# ---------------------------------------------------------

client = AsyncIOMotorClient(
    MONGO_URI,
    tls=True,
    serverSelectionTimeoutMS=30000,
    connectTimeoutMS=30000,
    retryWrites=True,
)

db = client[DB_NAME]

logger.info(
    "MongoDB client initialized for database '%s'.",
    DB_NAME,
)

# ---------------------------------------------------------
# INITIALIZE DATABASE AND BEANIE
# Called by the FastAPI lifespan in main.py.
# ---------------------------------------------------------

async def init_db():
    """Verify MongoDB connectivity and initialize Beanie."""

    logger.info(
        "Connecting to MongoDB database '%s'...",
        DB_NAME,
    )

    try:
        await db.command("ping")

        logger.info("MongoDB connection successful.")

        await init_beanie(
            database=db,
            document_models=DOCUMENT_MODELS,
        )

        logger.info("Beanie ODM initialized successfully.")

    except Exception:
        logger.exception(
            "MongoDB connection or Beanie initialization failed."
        )
        raise

# ---------------------------------------------------------
# DATABASE HEALTH STATUS
# Used by main.py or a health-check endpoint.
# ---------------------------------------------------------

async def get_db_status() -> str:
    """Check whether MongoDB is reachable."""

    try:
        await db.command("ping")
        return "CONNECTED"

    except Exception as exc:
        logger.error(
            "MongoDB heartbeat failed: %s",
            exc,
        )
        return f"CONNECTION_FAILED: {exc}"

# ---------------------------------------------------------
# CLOSE DATABASE CONNECTION
# Changed to async def to match the await call in main.py lifespan.
# ---------------------------------------------------------

async def close_db():
    """Close the MongoDB client."""
    client.close()
    logger.info("MongoDB client closed.")
