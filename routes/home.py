
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status

from models import HomeContent, HomeContentData

logger = logging.getLogger("EGB_Backyard_Home")
router = APIRouter()


def _document_to_response(document: HomeContent) -> dict[str, Any]:
    return {
        "hero": document.hero.model_dump(mode="json"),
        "carousel": document.carousel.model_dump(mode="json"),
        "stats": document.stats.model_dump(mode="json"),
        "contacts": document.contacts.model_dump(mode="json"),
        "updated_at": document.updated_at,
    }


@router.get("")
@router.get("/", include_in_schema=False)
async def get_home_content():
    """Return saved homepage content, or 404 until the first save."""
    try:
        document = await HomeContent.find_one({})
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Homepage content has not been configured yet. "
                    "Open the dashboard and save homepage settings."
                ),
            )
        return _document_to_response(document)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to retrieve homepage content.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve homepage content.",
        ) from exc


@router.put("")
@router.put("/", include_in_schema=False)
async def update_home_content(payload: HomeContentData):
    """
    Create or update homepage content.

    IMPORTANT: Attach the existing admin-auth dependency before exposing
    this write endpoint publicly.
    """
    try:
        document = await HomeContent.find_one({})
        now = datetime.now(timezone.utc).isoformat()
        data = payload.model_dump()

        if document is None:
            document = HomeContent(**data, updated_at=now)
            await document.insert()
        else:
            document.hero = payload.hero
            document.carousel = payload.carousel
            document.stats = payload.stats
            document.contacts = payload.contacts
            document.updated_at = now
            await document.save()

        logger.info("Homepage content saved.")
        return {
            **_document_to_response(document),
            "message": "Homepage settings saved successfully.",
        }
    except Exception as exc:
        logger.exception("Failed to save homepage content.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save homepage settings.",
        ) from exc
