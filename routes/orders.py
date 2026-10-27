import datetime
import logging
import math
from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from models import Order, Product
from security_dependencies import require_current_user, require_admin

logger = logging.getLogger("CommercePrime_Orders")
router = APIRouter(tags=["Orders"])

ORDER_STATUSES = {"pending", "processing", "confirmed", "shipped", "delivered", "cancelled"}
PAYMENT_STATUSES = {"pending", "paid", "failed", "refunded"}
PAYMENT_METHODS = {"cash_on_delivery", "cod", "card", "gcash", "maya", "bank_transfer"}

def user_value(user: Any, *keys: str) -> str | None:
    for key in keys:
        value = user.get(key) if isinstance(user, dict) else getattr(user, key, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None

def authenticated_user_id(user: Any) -> str:
    value = user_value(user, "id", "_id", "user_id", "sub")
    if not value:
        raise HTTPException(status_code=401, detail="Authenticated account has no user ID.")
    return value

def require_valid_object_id(value: str) -> PydanticObjectId:
    try:
        return PydanticObjectId(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order ID format.")

class OrderItemSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str | int | None = None
    product_id: str | None = Field(default=None)
    name: str = Field(default="Product")
    title: str | None = Field(default=None)
    price: float = Field(default=0.0)
    quantity: int = Field(default=1)
    image: str = Field(default="")
    category: str = Field(default="")
    sku: str = Field(default="")

    @model_validator(mode="before")  
    @classmethod  
    def normalize_item(cls, data: Any) -> Any:  
        if isinstance(data, dict):  
            data = dict(data)  
            if not data.get("name") and data.get("title"):  
                data["name"] = data["title"]  
            if not data.get("name"):  
                data["name"] = "Product"  
              
            try:  
                data["price"] = float(data.get("price") or 0.0)  
            except (ValueError, TypeError):  
                data["price"] = 0.0  

            try:  
                data["quantity"] = int(data.get("quantity") or 1)  
            except (ValueError, TypeError):  
                data["quantity"] = 1  

            for field in ["image", "category", "sku", "product_id"]:  
                val = data.get(field)  
                if val is None:  
                    data[field] = ""  
                else:  
                    data[field] = str(val)  
              
            if data.get("image") and len(data["image"]) > 2048:  
                data["image"] = ""  

        return data

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    items: list[OrderItemSchema] = Field(..., min_length=1, max_length=100)
    subtotal: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    total_amount: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    total: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    shipping_full_name: str = Field(default="", max_length=200)
    shipping_email: str = Field(default="", max_length=320)
    shipping_mobile_number: str = Field(default="", max_length=40)
    shipping_street: str = Field(default="", max_length=300)
    shipping_barangay: str = Field(default="", max_length=150)
    shipping_city: str = Field(default="", max_length=150)
    shipping_region: str = Field(default="", max_length=150)
    shipping_zip_code: str = Field(default="", max_length=30)
    shipping_landmark: str = Field(default="", max_length=300)
    shipping_country: str = Field(default="Philippines", max_length=100)
    shipping_address: dict[str, Any] | None = None
    shippingAddress: dict[str, Any] | None = None
    payment_method: str = "cash_on_delivery"
    notes: str = Field(default="", max_length=2000)

    @field_validator("payment_method")  
    @classmethod  
    def validate_payment_method(cls, value: str) -> str:  
        value = (value or "cash_on_delivery").strip().lower()  
        if value not in PAYMENT_METHODS:  
            return "cash_on_delivery"  
        return value  

    @model_validator(mode="before")  
    @classmethod  
    def normalize_shipping(cls, data: Any) -> Any:  
        if not isinstance(data, dict):  
            return data  
        data = dict(data)  
        addr = data.get("shipping_address") or data.get("shippingAddress")  
        if isinstance(addr, dict):  
            mapping = {  
                "full_name": "shipping_full_name", "fullName": "shipping_full_name",  
                "name": "shipping_full_name", "email": "shipping_email",  
                "phone": "shipping_mobile_number", "mobile": "shipping_mobile_number",  
                "mobileNumber": "shipping_mobile_number", "mobile_number": "shipping_mobile_number",  
                "address_line1": "shipping_street", "street": "shipping_street",  
                "address": "shipping_street", "address_line2": "shipping_barangay",  
                "barangay": "shipping_barangay", "city": "shipping_city",  
                "state": "shipping_region", "region": "shipping_region",  
                "province": "shipping_region", "postal_code": "shipping_zip_code",  
                "zipCode": "shipping_zip_code", "zip_code": "shipping_zip_code",  
                "zip": "shipping_zip_code", "landmark": "shipping_landmark",  
                "country": "shipping_country",  
            }  
            for source, destination in mapping.items():  
                if not data.get(destination) and addr.get(source):  
                    data[destination] = addr[source]  
        return data

class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str

    @field_validator("status")  
    @classmethod  
    def validate_status(cls, value: str) -> str:  
        value = value.strip().lower()  
        if value not in ORDER_STATUSES:  
            raise ValueError(f"Status must be one of {sorted(ORDER_STATUSES)}")  
        return value

class OrderETAUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estimated_delivery: str = Field(..., min_length=1, max_length=120)

class OrderUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    estimated_delivery: str | None = Field(default=None, max_length=120)
    estimatedDelivery: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    delivery_note: str | None = Field(default=None, max_length=2000)
    payment_status: str | None = None

    @field_validator("status")  
    @classmethod  
    def validate_status(cls, value: str | None) -> str | None:  
        if value is None:  
            return value  
        value = value.strip().lower()  
        if value not in ORDER_STATUSES:  
            raise ValueError(f"Status must be one of {sorted(ORDER_STATUSES)}")  
        return value  

    @field_validator("payment_status")  
    @classmethod  
    def validate_payment_status(cls, value: str | None) -> str | None:  
        if value is None:  
            return value  
        value = value.strip().lower()  
        if value not in PAYMENT_STATUSES:  
            raise ValueError(f"Payment status must be one of {sorted(PAYMENT_STATUSES)}")  
        return value

def format_order(order: Order) -> dict[str, Any]:
    raw_addr = getattr(order, "shippingAddress", None) or getattr(order, "shipping_address", None)
    if hasattr(raw_addr, "model_dump"):
        raw_addr = raw_addr.model_dump()
    if not isinstance(raw_addr, dict):
        raw_addr = {}
    addr = {
        "fullName": raw_addr.get("fullName") or raw_addr.get("full_name") or getattr(order, "shipping_full_name", ""),
        "email": raw_addr.get("email") or getattr(order, "shipping_email", ""),
        "mobileNumber": raw_addr.get("mobileNumber") or raw_addr.get("phone") or getattr(order, "shipping_mobile_number", ""),
        "street": raw_addr.get("street") or raw_addr.get("address_line1") or getattr(order, "shipping_street", ""),
        "barangay": raw_addr.get("barangay") or raw_addr.get("address_line2") or getattr(order, "shipping_barangay", ""),
        "city": raw_addr.get("city") or getattr(order, "shipping_city", ""),
        "region": raw_addr.get("region") or raw_addr.get("state") or getattr(order, "shipping_region", ""),
        "zipCode": raw_addr.get("zipCode") or raw_addr.get("postal_code") or getattr(order, "shipping_zip_code", ""),
        "landmark": raw_addr.get("landmark") or getattr(order, "shipping_landmark", ""),
        "country": raw_addr.get("country") or getattr(order, "shipping_country", "Philippines"),
    }
    order_id = str(order.id)
    total = float(getattr(order, "total_amount", None) or getattr(order, "total", 0) or 0)
    subtotal = float(getattr(order, "subtotal", None) or total)
    return {
        "_id": order_id, "id": order_id, "order_id": order_id,
        "order_number": getattr(order, "order_number", None) or f"ORD-{order_id[-8:].upper()}",
        "user_id": str(getattr(order, "user_id", "guest") or "guest"),
        "items": getattr(order, "items", []) or [],
        "total_amount": total, "total": total, "subtotal": subtotal,
        "shipping_full_name": addr["fullName"], "shipping_email": addr["email"],
        "shipping_mobile_number": addr["mobileNumber"], "shipping_street": addr["street"],
        "shipping_barangay": addr["barangay"], "shipping_city": addr["city"],
        "shipping_region": addr["region"], "shipping_zip_code": addr["zipCode"],
        "shipping_landmark": addr["landmark"], "shipping_country": addr["country"],
        "shipping_address": addr, "shippingAddress": addr,
        "customer_name": addr["fullName"], "customer_email": addr["email"],
        "customer_phone": addr["mobileNumber"],
        "payment_method": getattr(order, "payment_method", "cash_on_delivery"),
        "payment_status": getattr(order, "payment_status", "pending"),
        "status": getattr(order, "status", "pending"),
        "estimated_delivery": getattr(order, "estimated_delivery", "") or "",
        "notes": getattr(order, "notes", "") or "",
        "date": getattr(order, "date", None) or getattr(order, "created_at", ""),
        "created_at": getattr(order, "created_at", ""),
        "updated_at": getattr(order, "updated_at", ""),
    }

def ensure_owner_or_admin(order: Order, user: Any) -> None:
    uid = authenticated_user_id(user)
    role = (user_value(user, "role", "user_role") or "").lower()
    if role in {"admin", "administrator", "super_admin"}:
        return
    if str(getattr(order, "user_id", "")) != uid:
        raise HTTPException(status_code=404, detail="Order not found.")

@router.get("")
@router.get("/")
async def list_orders(
    current_user: Any = Depends(require_current_user),
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
):
    uid = authenticated_user_id(current_user)
    role = (user_value(current_user, "role", "user_role") or "").lower()
    query: dict[str, Any] = {}
    if role not in {"admin", "administrator", "super_admin"}:
        query["user_id"] = uid
    if status_filter:
        normalized = status_filter.strip().lower()
        if normalized not in ORDER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid order status.")
        query["status"] = normalized
    try:
        orders = await Order.find(query).sort("-_id").limit(500).to_list()
        return [format_order(order) for order in orders]
    except Exception:
        logger.exception("Failed to list orders")
        raise HTTPException(status_code=500, detail="Failed to fetch orders.")

@router.get("/user/{user_id}")
async def get_user_orders(user_id: str, current_user: Any = Depends(require_current_user)):
    uid = authenticated_user_id(current_user)
    role = (user_value(current_user, "role", "user_role") or "").lower()
    if role not in {"admin", "administrator", "super_admin"} and user_id != uid:
        raise HTTPException(status_code=403, detail="You cannot access another user's orders.")
    try:
        orders = await Order.find(Order.user_id == user_id).sort("-_id").limit(500).to_list()
        return [format_order(order) for order in orders]
    except Exception:
        logger.exception("Failed to fetch orders for user")
        raise HTTPException(status_code=500, detail="Failed to fetch user orders.")

@router.get("/{order_id}")
async def get_order_by_id(order_id: str, current_user: Any = Depends(require_current_user)):
    order = await Order.get(require_valid_object_id(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    ensure_owner_or_admin(order, current_user)
    return format_order(order)

@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_order(order_data: OrderCreate, current_user: Any = Depends(require_current_user)):
    uid = authenticated_user_id(current_user)
    verified_items = []
    computed_subtotal = 0.0

    for item in order_data.items:  
        if not item.product_id:  
            raise HTTPException(  
                status_code=status.HTTP_400_BAD_REQUEST,  
                detail=f"Product ID is required for item '{item.name}'."  
            )  

        try:  
            product_obj_id = PydanticObjectId(item.product_id)  
        except Exception:  
            raise HTTPException(  
                status_code=status.HTTP_400_BAD_REQUEST,  
                detail=f"Invalid product ID format: {item.product_id}"  
            )  

        product = await Product.get(product_obj_id)  
        if not product:  
            raise HTTPException(  
                status_code=status.HTTP_404_NOT_FOUND,  
                detail=f"Product not found or no longer available: {item.product_id}"  
            )  

        server_price = float(getattr(product, "price", 0.0))  
        quantity = int(item.quantity)  
        computed_subtotal += server_price * quantity  

        product_image = (  
            getattr(product, "image", None)  
            or getattr(product, "imageUrl", None)  
            or getattr(product, "img", None)  
            or getattr(product, "image_url", None)  
            or item.image  
            or ""  
        )  

        product_category = getattr(product, "category", None) or item.category or ""  
        product_sku = getattr(product, "sku", None) or item.sku or ""  
        product_name = getattr(product, "name", None) or getattr(product, "title", None) or item.name or "Product"  

        verified_items.append({  
            "product_id": str(product.id),  
            "name": str(product_name),  
            "price": server_price,  
            "quantity": quantity,  
            "image": str(product_image),  
            "category": str(product_category),  
            "sku": str(product_sku),  
        })  

    if not math.isfinite(computed_subtotal) or computed_subtotal <= 0:  
        raise HTTPException(status_code=422, detail="Order total must be greater than zero.")  

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()  
    shipping = {  
        "fullName": order_data.shipping_full_name, "email": order_data.shipping_email,  
        "mobileNumber": order_data.shipping_mobile_number, "street": order_data.shipping_street,  
        "barangay": order_data.shipping_barangay, "city": order_data.shipping_city,  
        "region": order_data.shipping_region, "zipCode": order_data.shipping_zip_code,  
        "landmark": order_data.shipping_landmark, "country": order_data.shipping_country or "Philippines",  
    }  
    try:  
        order = Order(  
            user_id=uid,  
            order_number=None,  
            items=verified_items,  
            subtotal=computed_subtotal,  
            total=computed_subtotal,  
            total_amount=computed_subtotal,  
            shipping_full_name=shipping["fullName"], shipping_email=shipping["email"],  
            shipping_mobile_number=shipping["mobileNumber"], shipping_street=shipping["street"],  
            shipping_barangay=shipping["barangay"], shipping_city=shipping["city"],  
            shipping_region=shipping["region"], shipping_zip_code=shipping["zipCode"],  
            shipping_landmark=shipping["landmark"], shipping_country=shipping["country"],  
            shippingAddress=shipping, shipping_address=shipping,  
            payment_method=order_data.payment_method,  
            payment_status="pending", status="pending",  
            estimated_delivery="", notes=order_data.notes,  
            date=now, created_at=now, updated_at=now,  
        )  
        await order.insert()  
        if not getattr(order, "order_number", None):  
            order.order_number = f"ORD-{str(order.id)[-8:].upper()}"  
            await order.save()  
        return {"success": True, "message": "Order created successfully",  
                "order_id": str(order.id), "_id": str(order.id), "order": format_order(order)}  
    except HTTPException:  
        raise  
    except Exception:  
        logger.exception("Failed to create order")  
        raise HTTPException(status_code=500, detail="Failed to create order.")

@router.patch("/{order_id}/status")
@router.put("/{order_id}/status")
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    current_user: Any = Depends(require_current_user),
):
    order = await Order.get(require_valid_object_id(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    
    uid = authenticated_user_id(current_user)
    role = (user_value(current_user, "role", "user_role") or "").lower()
    is_admin = role in {"admin", "administrator", "super_admin"}
    is_owner = str(getattr(order, "user_id", "")) == uid

    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Access denied.")

    if not is_admin:
        if payload.status != "cancelled":
            raise HTTPException(status_code=403, detail="Customers can only cancel their own orders.")
        current_status = str(getattr(order, "status", "pending")).lower()
        if current_status not in {"pending", "processing"}:
            raise HTTPException(status_code=400, detail=f"Order cannot be cancelled in '{current_status}' status.")

    order.status = payload.status
    order.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        await order.save()
        return format_order(order)
    except Exception:
        logger.exception("Failed to update order status")
        raise HTTPException(status_code=500, detail="Failed to update order status.")

@router.put("/{order_id}/eta")
async def update_order_eta(order_id: str, payload: OrderETAUpdate, _admin: Any = Depends(require_admin)):
    order = await Order.get(require_valid_object_id(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    order.estimated_delivery = payload.estimated_delivery.strip()
    order.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        await order.save()
        return format_order(order)
    except Exception:
        logger.exception("Failed to update order ETA")
        raise HTTPException(status_code=500, detail="Failed to update order ETA.")

@router.put("/{order_id}")
async def update_order(order_id: str, payload: OrderUpdateSchema, _admin: Any = Depends(require_admin)):
    order = await Order.get(require_valid_object_id(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    updates = payload.model_dump(exclude_unset=True)
    if "estimatedDelivery" in updates:
        updates.setdefault("estimated_delivery", updates.pop("estimatedDelivery"))
    if "delivery_note" in updates:
        updates.setdefault("notes", updates.pop("delivery_note"))
    updates.pop("estimatedDelivery", None)
    updates.pop("delivery_note", None)
    updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        await order.set(updates)
        return format_order(order)
    except Exception:
        logger.exception("Failed to update order")
        raise HTTPException(status_code=500, detail="Failed to update order.")

@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: str, _admin: Any = Depends(require_admin)):
    order = await Order.get(require_valid_object_id(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    try:
        await order.delete()
    except Exception:
        logger.exception("Failed to delete order")
        raise HTTPException(status_code=500, detail="Failed to delete order.")
