import hashlib
import hmac
import os
from typing import Any, Optional, Union

from beanie import Document
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: Optional[bytes] = None):
    """Return (PBKDF2 hash hex, salt bytes). Store the salt safely with the hash."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        try:
            salt = bytes.fromhex(salt)
        except ValueError:
            salt = salt.encode("latin-1")

    password_bytes = str(password).encode("utf-8")
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", password_bytes, salt, 100_000
    )
    return hash_bytes.hex(), salt


def verify_password(
    stored_hash: str, salt: Any, provided_password: str
) -> bool:
    """Constant-time verification for passwords stored using hash_password."""
    if isinstance(salt, str):
        try:
            salt = bytes.fromhex(salt)
        except ValueError:
            salt = salt.encode("latin-1")
    if not isinstance(salt, bytes):
        return False
    new_hash, _ = hash_password(provided_password, salt)
    return hmac.compare_digest(new_hash, str(stored_hash))


# ---------------------------------------------------------------------------
# User and admin
# ---------------------------------------------------------------------------

class User(Document):
    email: EmailStr
    password: str
    salt: Any
    username: str
    fullName: str = ""
    mobile: str = ""
    birthDate: str = ""
    gender: str = "Other"
    facebook: str = ""
    avatar: str = ""
    age: str = "N/A"
    membershipTier: str = "CC Prime"
    status: str = "Active"
    isVerified: bool = False
    is_admin: bool = False
    created_at: str

    class Settings:
        name = "ecom_users"

    @field_validator("age", mode="before")
    @classmethod
    def ensure_age_is_string(cls, value):
        if value is None:
            return "N/A"
        if isinstance(value, (int, float)):
            return str(value)
        cleaned = str(value).strip()
        return cleaned or "N/A"


class AdminUser(Document):
    fullName: str
    birthday: str
    habits: str
    email: EmailStr
    password: str
    salt: str
    created_at: str

    class Settings:
        name = "admin_users"


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class Product(Document):
    name: str
    description: Optional[str] = ""
    price: float
    compare_at_price: Optional[float] = None
    sku: Optional[str] = ""
    inventory: int = 0
    category: str = Field(
        ..., description="Category must be one of: rooster, hen, chick"
    )
    badge: Optional[str] = None
    sizes: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    specifications: dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Settings:
        name = "products"


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderItem(BaseModel):
    id: Optional[Union[str, int]] = None
    product_id: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    price: float = 0.0
    quantity: int = 1
    image: Optional[str] = ""
    category: Optional[str] = ""
    sku: Optional[str] = ""


class ShippingAddress(BaseModel):
    fullName: Optional[str] = ""
    mobileNumber: Optional[str] = ""
    street: Optional[str] = ""
    city: Optional[str] = ""
    region: Optional[str] = ""
    barangay: Optional[str] = ""
    zipCode: Optional[str] = ""
    landmark: Optional[str] = ""
    country: Optional[str] = "Philippines"


class Order(Document):
    user_id: str = "guest"
    order_number: Optional[str] = None
    items: list[OrderItem] = Field(default_factory=list)
    total_amount: float = 0.0
    subtotal: float = 0.0
    total: Optional[float] = None
    shipping_full_name: Optional[str] = ""
    shipping_email: Optional[str] = ""
    shipping_mobile_number: Optional[str] = ""
    shipping_street: Optional[str] = ""
    shipping_barangay: Optional[str] = ""
    shipping_city: Optional[str] = ""
    shipping_region: Optional[str] = ""
    shipping_zip_code: Optional[str] = ""
    shipping_landmark: Optional[str] = ""
    shipping_country: Optional[str] = "Philippines"
    shippingAddress: Optional[Union[ShippingAddress, dict[str, Any]]] = None
    shipping_address: Optional[Union[ShippingAddress, dict[str, Any]]] = None
    status: str = "pending"
    payment_method: str = "cash_on_delivery"
    payment_status: str = "pending"
    notes: Optional[str] = ""
    estimated_delivery: Optional[str] = ""
    date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Settings:
        name = "orders"


# ---------------------------------------------------------------------------
# Coupons and tax settings
# ---------------------------------------------------------------------------

class Coupon(Document):
    code: str
    discount: float
    type: str = "percent"
    minSpend: Optional[float] = 0
    maxDiscount: Optional[float] = None
    description: str
    created_at: Optional[str] = None

    class Settings:
        name = "coupons"


class TaxSettingDocument(Document):
    key: str = "store_tax_rate"
    taxRate: float = 0.08
    updated_at: Optional[str] = None

    class Settings:
        name = "tax_settings"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class Event(Document):
    title: str
    description: str = ""
    event_type: str = "sale"
    discount_amount: float = 0.0
    start_date: str
    end_date: str
    banner_image: Optional[str] = ""
    link_url: Optional[str] = ""
    status: str = "upcoming"
    is_featured: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Settings:
        name = "events"


# Keep this alias for routes that already import EventDocument.
EventDocument = Event


# ---------------------------------------------------------------------------
# Homepage configuration schemas
# ---------------------------------------------------------------------------

class BackgroundConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: str = "image"
    source: str = Field(default="", max_length=15_000_000)
    fallbackImage: str = Field(default="", max_length=15_000_000)

    @field_validator("type")
    @classmethod
    def validate_background_type(cls, value: str) -> str:
        if value not in {"image", "video", "color"}:
            raise ValueError("type must be image, video, or color")
        return value


class HeroConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    badgeText: str = Field(default="", max_length=300)
    badgeFontFamily: Optional[str] = "Inter, sans-serif"
    titleTop: str = Field(default="", max_length=300)
    titleBottom: str = Field(default="", max_length=300)
    titleFontFamily: Optional[str] = "Inter, sans-serif"
    heading: str = Field(default="", max_length=500)
    headingFontFamily: Optional[str] = "Inter, sans-serif"
    narrative: str = Field(default="", max_length=5000)
    narrativeFontFamily: Optional[str] = "Inter, sans-serif"
    ctaText: str = Field(default="", max_length=120)
    ctaPath: str = Field(default="/shop", max_length=500)
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)

    @field_validator("ctaPath")
    @classmethod
    def validate_cta_path(cls, value: str) -> str:
        value = value.strip()
        if value and not value.startswith("/") and not value.startswith("https://"):
            raise ValueError(
                "ctaPath must be an internal path beginning with '/' or an HTTPS URL"
            )
        return value


class CategoryCard(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: Union[int, str]
    title: str = Field(default="", max_length=200)
    titleFontFamily: Optional[str] = "Inter, sans-serif"
    subtitle: str = Field(default="", max_length=200)
    subtitleFontFamily: Optional[str] = "Inter, sans-serif"
    description: str = Field(default="", max_length=2000)
    descriptionFontFamily: Optional[str] = "Inter, sans-serif"
    image: str = Field(default="", max_length=15_000_000)
    path: str = Field(default="", max_length=500)
    fontFamily: Optional[str] = "Inter, sans-serif"


class CarouselConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    eyebrow: str = Field(default="", max_length=200)
    eyebrowFontFamily: Optional[str] = "Inter, sans-serif"
    title: str = Field(default="", max_length=300)
    titleFontFamily: Optional[str] = "Inter, sans-serif"
    cards: list[CategoryCard] = Field(default_factory=list, max_length=30)


class StatItem(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    number: str = Field(default="", max_length=100)
    numberFontFamily: Optional[str] = "Inter, sans-serif"
    label: str = Field(default="", max_length=200)
    labelFontFamily: Optional[str] = "Inter, sans-serif"


class StatsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    eyebrow: str = Field(default="", max_length=200)
    eyebrowFontFamily: Optional[str] = "Inter, sans-serif"
    heading: str = Field(default="", max_length=300)
    headingFontFamily: Optional[str] = "Inter, sans-serif"
    items: list[StatItem] = Field(default_factory=list, max_length=30)


class ContactConfig(BaseModel):
    """Business contact and social links used by homepage components."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=320)
    address: str = Field(default="", max_length=1000)
    facebook: str = Field(default="", max_length=2000)
    instagram: str = Field(default="", max_length=2000)
    tiktok: str = Field(default="", max_length=2000)
    messenger: str = Field(default="", max_length=2000)


class HomeContentData(BaseModel):
    """Validated API payload for homepage settings."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    hero: HeroConfig = Field(default_factory=HeroConfig)
    carousel: CarouselConfig = Field(default_factory=CarouselConfig)
    stats: StatsConfig = Field(default_factory=StatsConfig)
    contacts: ContactConfig = Field(default_factory=ContactConfig)


class HomeContent(Document):
    """Persisted homepage document in the home_content collection."""
    hero: HeroConfig = Field(default_factory=HeroConfig)
    carousel: CarouselConfig = Field(default_factory=CarouselConfig)
    stats: StatsConfig = Field(default_factory=StatsConfig)
    contacts: ContactConfig = Field(default_factory=ContactConfig)
    updated_at: Optional[str] = None

    class Settings:
        name = "home_content"
