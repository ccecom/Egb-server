import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from beanie import PydanticObjectId
from models import TaxSettingDocument, Coupon, EventDocument

logger = logging.getLogger("CommercePrime_Cart")
router = APIRouter(tags=["Settings, Promos & Cart Validation"])

# =================================================================
# PYDANTIC MODELS
# =================================================================

class TaxSettingsUpdate(BaseModel):
    taxRate: float = Field(..., ge=0.0, le=1.0)

class CouponCreate(BaseModel):
    code: str
    discount: float
    type: str = "percent"  # 'percent' | 'fixed' | 'shipping'
    minSpend: Optional[float] = 0
    maxDiscount: Optional[float] = None
    description: str

class CouponValidationRequest(BaseModel):
    code: str
    subtotal: float

class GameRewardClaim(BaseModel):
    code: str
    discount: float
    type: str = "fixed"  # 'percent' | 'fixed'
    description: str = "Mini-Game Reward"

class EventCreate(BaseModel):
    title: str
    description: str = ""
    event_type: str = "sale"
    discount_amount: float = 0.0
    start_date: str
    end_date: str
    status: str = "active"  
    is_featured: bool = False

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    discount_amount: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    is_featured: Optional[bool] = None


# =================================================================
# TAX CONFIGURATION ENDPOINTS
# =================================================================

@router.get("/tax")
async def get_tax_rate():
    """Retrieve current store-wide tax percentage from MongoDB"""
    try:
        setting = await TaxSettingDocument.find_one(TaxSettingDocument.key == "store_tax_rate")
        if setting:
            return {"taxRate": setting.taxRate}
    except Exception as e:
        logger.error(f"Error fetching tax rate: {e}", exc_info=True)
    return {"taxRate": 0.08}

@router.put("/tax")
async def update_tax_rate(payload: TaxSettingsUpdate):
    """Update store-wide tax percentage dynamically in MongoDB"""
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        setting = await TaxSettingDocument.find_one(TaxSettingDocument.key == "store_tax_rate")
        if setting:
            setting.taxRate = payload.taxRate
            setting.updated_at = now_str
            await setting.save()
        else:
            new_setting = TaxSettingDocument(
                key="store_tax_rate",
                taxRate=payload.taxRate,
                updated_at=now_str
            )
            await new_setting.insert()
            
        return {"success": True, "taxRate": payload.taxRate, "message": "Tax rate updated successfully."}
    except Exception as e:
        logger.error(f"Error updating tax rate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error updating tax rate.")


# =================================================================
# COUPONS & PROMOS ENDPOINTS
# =================================================================

@router.get("/coupons", response_model=List[dict])
async def get_all_coupons():
    """Retrieve all store coupons from MongoDB"""
    try:
        coupons = await Coupon.find_all().to_list()
        return [
            {
                "id": str(c.id),
                "code": c.code,
                "discount": c.discount,
                "type": c.type,
                "minSpend": c.minSpend,
                "maxDiscount": c.maxDiscount,
                "description": c.description
            }
            for c in coupons
        ]
    except Exception as e:
        logger.error(f"Error fetching coupons: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching coupons.")

@router.post("/coupons", status_code=status.HTTP_201_CREATED)
async def create_coupon(coupon: CouponCreate):
    """Create a promotional voucher in MongoDB with duplicate check"""
    try:
        code_upper = coupon.code.upper().strip()
        
        existing_coupon = await Coupon.find_one(Coupon.code == code_upper)
        if existing_coupon:
            raise HTTPException(status_code=400, detail="Coupon code already exists.")
        
        new_coupon = Coupon(
            code=code_upper,
            discount=coupon.discount,
            type=coupon.type,
            minSpend=coupon.minSpend or 0,
            maxDiscount=coupon.maxDiscount,
            description=coupon.description,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        await new_coupon.insert()

        return {
            "message": "Coupon created successfully", 
            "coupon": {
                "id": str(new_coupon.id),
                "code": new_coupon.code,
                "discount": new_coupon.discount,
                "type": new_coupon.type,
                "minSpend": new_coupon.minSpend,
                "maxDiscount": new_coupon.maxDiscount,
                "description": new_coupon.description
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating coupon: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error creating coupon.")

@router.post("/coupons/claim-game-reward", status_code=status.HTTP_201_CREATED)
async def claim_game_reward(payload: GameRewardClaim):
    """Save a dynamically generated mini-game reward coupon into MongoDB"""
    try:
        code_upper = payload.code.upper().strip()
        
        existing_coupon = await Coupon.find_one(Coupon.code == code_upper)
        if existing_coupon:
            raise HTTPException(status_code=400, detail="Reward code already claimed or registered.")
        
        new_coupon = Coupon(
            code=code_upper,
            discount=payload.discount,
            type=payload.type,
            minSpend=0.0,
            description=payload.description,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        await new_coupon.insert()

        return {
            "success": True,
            "message": "Reward claimed successfully",
            "coupon": {
                "id": str(new_coupon.id),
                "code": new_coupon.code,
                "discount": new_coupon.discount,
                "type": new_coupon.type,
                "description": new_coupon.description
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming game reward: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error processing reward.")

@router.post("/coupons/validate")
async def validate_coupon_code(payload: CouponValidationRequest):
    """Secure server-side coupon validation for the cart page"""
    try:
        code_upper = payload.code.upper().strip()
        
        coupon = await Coupon.find_one(Coupon.code == code_upper)
        if not coupon:
            raise HTTPException(status_code=404, detail="Invalid coupon code.")
            
        if payload.subtotal < (coupon.minSpend or 0):
            raise HTTPException(
                status_code=400, 
                detail=f"Minimum spend of ₱{coupon.minSpend} required for this coupon."
            )
            
        # Calculate exact discount value server-side
        if coupon.type == 'percent':
            discount_value = (payload.subtotal * coupon.discount) / 100
            if coupon.maxDiscount and discount_value > coupon.maxDiscount:
                discount_value = coupon.maxDiscount
        else:
            discount_value = coupon.discount

        return {
            "success": True,
            "coupon": {
                "code": coupon.code,
                "type": coupon.type,
                "discount": coupon.discount,
                "calculatedDiscount": discount_value,
                "description": coupon.description
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating coupon: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error validating coupon.")

@router.delete("/coupons/{code}")
async def delete_coupon(code: str):
    """Delete a coupon code from MongoDB"""
    try:
        code_upper = code.upper().strip()
        coupon_doc = await Coupon.find_one(Coupon.code == code_upper)
        if not coupon_doc:
            raise HTTPException(status_code=404, detail="Coupon not found.")
        
        await coupon_doc.delete()
        return {"message": f"Coupon {code_upper} deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting coupon: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error deleting coupon.")


# =================================================================
# STORE EVENTS & CAMPAIGNS ENDPOINTS (Unified & Filterable)
# =================================================================

@router.get("/events", response_model=List[dict])
async def get_all_events(status_filter: Optional[str] = None, event_type: Optional[str] = None):
    """Retrieve all scheduled events with optional filtering by status or type."""
    try:
        query = {}
        if status_filter:
            query["status"] = status_filter.lower().strip()
        if event_type:
            query["event_type"] = event_type.lower().strip()
            
        events = await EventDocument.find(query).to_list()
        return [
            {
                "id": str(e.id),
                "title": e.title,
                "description": e.description,
                "event_type": e.event_type,
                "discount_amount": e.discount_amount,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "status": e.status.lower(),
                "is_featured": e.is_featured
            }
            for e in events
        ]
    except Exception as e:
        logger.error(f"Error fetching events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching events.")

@router.get("/events/{event_id}")
async def get_event_by_id(event_id: str):
    """Retrieve a single event by its ID."""
    if not PydanticObjectId.is_valid(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format.")

    try:
        event = await EventDocument.get(PydanticObjectId(event_id))
        if not event:
            raise HTTPException(status_code=404, detail="Event not found.")
            
        return {
            "id": str(event.id),
            "title": event.title,
            "description": event.description,
            "event_type": event.event_type,
            "discount_amount": event.discount_amount,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "status": event.status.lower(),
            "is_featured": event.is_featured
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching event {event_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching event.")

@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(event: EventCreate):
    """Schedule a new store event or promotional sale in MongoDB"""
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        new_event = EventDocument(
            title=event.title,
            description=event.description,
            event_type=event.event_type,
            discount_amount=event.discount_amount,
            start_date=event.start_date,
            end_date=event.end_date,
            status=event.status.lower().strip(),
            is_featured=event.is_featured,
            created_at=now_str,
            updated_at=now_str
        )
        await new_event.insert()
        
        return {
            "message": "Event scheduled successfully",
            "event": {
                "id": str(new_event.id),
                "title": new_event.title,
                "description": new_event.description,
                "event_type": new_event.event_type,
                "discount_amount": new_event.discount_amount,
                "start_date": new_event.start_date,
                "end_date": new_event.end_date,
                "status": new_event.status,
                "is_featured": new_event.is_featured
            }
        }
    except Exception as e:
        logger.error(f"Error creating event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error creating event.")

@router.put("/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdate):
    """Update an existing event or change its status"""
    if not PydanticObjectId.is_valid(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format.")

    try:
        event_doc = await EventDocument.get(PydanticObjectId(event_id))
        if not event_doc:
            raise HTTPException(status_code=404, detail="Event not found.")

        update_data = payload.model_dump(exclude_unset=True)
        if "status" in update_data and update_data["status"]:
            update_data["status"] = update_data["status"].lower().strip()

        for key, value in update_data.items():
            setattr(event_doc, key, value)

        event_doc.updated_at = datetime.now(timezone.utc).isoformat()
        await event_doc.save()

        return {"message": "Event updated successfully", "event_id": event_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating event {event_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error updating event.")

@router.delete("/events/{event_id}")
async def delete_event(event_id: str):
    """Delete a scheduled event from MongoDB by its ID"""
    if not PydanticObjectId.is_valid(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format.")

    try:
        event_doc = await EventDocument.get(PydanticObjectId(event_id))
        if not event_doc:
            raise HTTPException(status_code=404, detail="Event not found.")
        
        await event_doc.delete()
        return {"message": f"Event {event_id} deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event {event_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error deleting event.")
