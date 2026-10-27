import base64
import binascii
import datetime
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import Product
from security_dependencies import require_admin

logger = logging.getLogger("EGB_Backyard_Products")

router = APIRouter(tags=["Products"])

ALLOWED_CATEGORIES = {"rooster", "hen", "chick"}
ALLOWED_STATUSES = {"active", "draft", "archived"}

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "products"
IMAGE_URL_PREFIX = "/static/uploads/products"

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES_PER_UPLOAD = 10

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
    "gif": (b"GIF87a", b"GIF89a"),
}

ALLOWED_IMAGE_DATA_HEADERS = {
    "data:image/jpeg;base64": "jpg",
    "data:image/jpg;base64": "jpg",
    "data:image/png;base64": "png",
    "data:image/webp;base64": "webp",
    "data:image/gif;base64": "gif",
}


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=2, max_length=160)
    description: str = Field(default="", max_length=10000)
    price: float = Field(..., ge=0, le=1_000_000_000, allow_inf_nan=False)
    compare_at_price: float | None = Field(
        default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    sku: str = Field(default="", max_length=100)
    inventory: int = Field(default=0, ge=0, le=1_000_000_000)
    category: str
    badge: str | None = Field(default=None, max_length=80)
    sizes: list[str] = Field(default_factory=list, max_length=100)
    colors: list[str] = Field(default_factory=list, max_length=100)
    images: list[str] = Field(default_factory=list, max_length=30)
    specifications: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ALLOWED_CATEGORIES:
            raise ValueError("Category must be rooster, hen, or chick.")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ALLOWED_STATUSES:
            raise ValueError("Status must be active, draft, or archived.")
        return value

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Image paths must be non-empty strings.")

            if value.lower().startswith("data:"):
                header, separator, _encoded = value.partition(",")
                if not separator or header.lower() not in ALLOWED_IMAGE_DATA_HEADERS:
                    raise ValueError(
                        "Use a valid JPEG, PNG, WebP, or GIF Base64 data URL."
                    )
                continue

            if not (
                value.startswith("/static/uploads/products/")
                or value.startswith("https://")
                or value.startswith("http://")
            ):
                raise ValueError("Unsupported image path.")
        return values


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    price: float | None = Field(
        default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    compare_at_price: float | None = Field(
        default=None, ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    sku: str | None = Field(default=None, max_length=100)
    inventory: int | None = Field(default=None, ge=0, le=1_000_000_000)
    category: str | None = None
    badge: str | None = Field(default=None, max_length=80)
    sizes: list[str] | None = Field(default=None, max_length=100)
    colors: list[str] | None = Field(default=None, max_length=100)
    images: list[str] | None = Field(default=None, max_length=30)
    specifications: dict[str, Any] | None = None
    status: str | None = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in ALLOWED_CATEGORIES:
            raise ValueError("Category must be rooster, hen, or chick.")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in ALLOWED_STATUSES:
            raise ValueError("Status must be active, draft, or archived.")
        return value

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None

        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Image paths must be non-empty strings.")

            if value.lower().startswith("data:"):
                header, separator, _encoded = value.partition(",")
                if not separator or header.lower() not in ALLOWED_IMAGE_DATA_HEADERS:
                    raise ValueError(
                        "Use a valid JPEG, PNG, WebP, or GIF Base64 data URL."
                    )
                continue

            if not (
                value.startswith("/static/uploads/products/")
                or value.startswith("https://")
                or value.startswith("http://")
            ):
                raise ValueError("Unsupported image path.")
        return values


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def format_product_dto(
    doc: Product, is_list_view: bool = False
) -> dict[str, Any]:
    """
    Returns product data with image paths the frontend can display.
    Paths look like: /static/uploads/products/<uuid>.jpg
    Frontend should prefix with API origin, e.g.:
      http://127.0.0.1:8000/static/uploads/products/<uuid>.jpg
    """
    product_id = str(doc.id)
    raw_images = list(getattr(doc, "images", None) or [])

    # Keep only usable image strings
    images: list[str] = []
    for item in raw_images:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value:
            continue
        # Never return residual base64 blobs in API responses
        if value.lower().startswith("data:"):
            continue
        images.append(value)

    return {
        "_id": product_id,
        "id": product_id,
        "name": doc.name,
        "description": getattr(doc, "description", "") or "",
        "price": doc.price,
        "compare_at_price": getattr(doc, "compare_at_price", None),
        "sku": getattr(doc, "sku", "") or "",
        "inventory": getattr(doc, "inventory", 0) or 0,
        "category": doc.category,
        "badge": getattr(doc, "badge", None),
        "sizes": getattr(doc, "sizes", None) or [],
        "colors": getattr(doc, "colors", None) or [],
        "images": images[:1] if is_list_view else images,
        "specifications": getattr(doc, "specifications", None) or {},
        "status": getattr(doc, "status", "active") or "active",
        "created_at": getattr(doc, "created_at", None),
        "updated_at": getattr(doc, "updated_at", None),
    }


def save_base64_image(value: str) -> str:
    """Decode a supported Base64 data URL and save it as an image file."""
    if not isinstance(value, str) or not value.lower().startswith("data:"):
        return value

    header, separator, encoded = value.partition(",")
    if not separator:
        raise HTTPException(
            status_code=400, detail="Malformed Base64 image data URL."
        )

    image_type = ALLOWED_IMAGE_DATA_HEADERS.get(header.lower())
    if image_type is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported Base64 image format. Use JPEG, PNG, WebP, or GIF.",
        )

    max_encoded_size = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    if len(encoded) > max_encoded_size:
        raise HTTPException(
            status_code=413, detail="Each image must be 8 MB or smaller."
        )

    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid Base64 image data."
        ) from exc

    if not content:
        raise HTTPException(status_code=400, detail="The image file is empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Each image must be 8 MB or smaller."
        )

    valid_signature = any(
        content.startswith(signature)
        for signature in IMAGE_SIGNATURES[image_type]
    )
    if image_type == "webp":
        valid_signature = (
            len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )

    if not valid_signature:
        raise HTTPException(
            status_code=415,
            detail="Image content does not match its declared format.",
        )

    filename = f"{uuid.uuid4().hex}.{image_type}"
    destination = UPLOAD_DIR / filename
    try:
        with destination.open("xb") as output:
            output.write(content)
    except OSError as exc:
        logger.exception("Failed to save decoded product image")
        raise HTTPException(
            status_code=500, detail="Unable to save product image."
        ) from exc

    return f"{IMAGE_URL_PREFIX}/{filename}"


def convert_product_images(images: list[str] | None) -> list[str] | None:
    """Convert Base64 data URLs to saved paths; keep normal URLs/paths."""
    if images is None:
        return None

    saved_paths: list[str] = []
    newly_created_paths: list[str] = []
    try:
        for image_value in images:
            image_path = save_base64_image(image_value)
            saved_paths.append(image_path)
            if isinstance(image_value, str) and image_value.lower().startswith(
                "data:"
            ):
                newly_created_paths.append(image_path)
        return saved_paths
    except Exception:
        for image_path in newly_created_paths:
            filename = image_path.rsplit("/", 1)[-1]
            (UPLOAD_DIR / filename).unlink(missing_ok=True)
        raise


async def read_image(upload: UploadFile) -> tuple[bytes, str]:
    original_name = upload.filename or ""
    extension = Path(original_name).suffix.lower()

    allowed_extensions = {
        ".jpg": "jpg",
        ".jpeg": "jpg",
        ".png": "png",
        ".webp": "webp",
        ".gif": "gif",
    }

    image_type = allowed_extensions.get(extension)
    if image_type is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Use JPG, JPEG, PNG, WebP, or GIF.",
        )

    content = await upload.read(MAX_IMAGE_BYTES + 1)
    await upload.close()

    if not content:
        raise HTTPException(status_code=400, detail="The image file is empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Each image must be 8 MB or smaller."
        )

    valid_signature = any(
        content.startswith(signature)
        for signature in IMAGE_SIGNATURES[image_type]
    )
    if image_type == "webp":
        valid_signature = (
            content.startswith(b"RIFF")
            and len(content) >= 12
            and content[8:12] == b"WEBP"
        )

    if not valid_signature:
        raise HTTPException(
            status_code=415,
            detail="The uploaded file does not match its image extension.",
        )

    return content, image_type


@router.post("/upload-images")
async def upload_product_images(
    files: list[UploadFile] = File(...),
    _admin: Any = Depends(require_admin),
):
    """Upload image files from the device gallery."""
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one image.")
    if len(files) > MAX_IMAGES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Upload no more than {MAX_IMAGES_PER_UPLOAD} images at once.",
        )

    saved_paths: list[str] = []
    try:
        for upload in files:
            content, image_type = await read_image(upload)
            filename = f"{uuid.uuid4().hex}.{image_type}"
            destination = UPLOAD_DIR / filename
            with destination.open("xb") as output:
                output.write(content)
            saved_paths.append(f"{IMAGE_URL_PREFIX}/{filename}")

        return {"success": True, "images": saved_paths}

    except HTTPException:
        for image_path in saved_paths:
            filename = image_path.rsplit("/", 1)[-1]
            (UPLOAD_DIR / filename).unlink(missing_ok=True)
        raise
    except Exception as exc:
        for image_path in saved_paths:
            filename = image_path.rsplit("/", 1)[-1]
            (UPLOAD_DIR / filename).unlink(missing_ok=True)
        logger.exception("Product image upload failed")
        raise HTTPException(
            status_code=500, detail="Unable to save product images."
        ) from exc


@router.get("")
async def list_products(
    category: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(
        default=None, alias="status", max_length=20
    ),
    skip: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=100, ge=1, le=200),
):
    """
    List products.

    - No status param → all statuses (admin dashboard needs drafts/archived).
    - status=active|draft|archived → filter by that status.
    - Optional category=rooster|hen|chick
    """
    query: dict[str, Any] = {}

    if category:
        category = category.strip().lower()
        if category not in ALLOWED_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category.")
        query["category"] = category

    if status_filter:
        status_value = status_filter.strip().lower()
        if status_value not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status.")
        query["status"] = status_value

    try:
        products = (
            await Product.find(query)
            .sort("-_id")
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return [format_product_dto(item, is_list_view=True) for item in products]
    except Exception as exc:
        logger.exception("Failed to list products")
        raise HTTPException(
            status_code=500, detail="Unable to fetch products."
        ) from exc


@router.get("/{product_id}")
async def get_single_product(product_id: str):
    """
    Return a single product by id (any status).
    Admin detail view needs draft/archived products and their images.
    """
    try:
        product = await Product.get(product_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Invalid product ID."
        ) from exc

    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    return format_product_dto(product)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    _admin: Any = Depends(require_admin),
):
    now = utc_now()
    payload = data.model_dump()

    # Base64 → files under /static/uploads/products/
    payload["images"] = convert_product_images(payload.get("images", [])) or []
    payload["created_at"] = now
    payload["updated_at"] = now

    try:
        product = Product(**payload)
        await product.insert()
        return format_product_dto(product)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create product")
        raise HTTPException(
            status_code=500, detail="Failed to create product."
        ) from exc


@router.put("/{product_id}")
async def edit_product(
    product_id: str,
    data: ProductUpdate,
    _admin: Any = Depends(require_admin),
):
    try:
        product = await Product.get(product_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Invalid product ID."
        ) from exc

    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return format_product_dto(product)

    if "images" in changes and changes["images"] is not None:
        changes["images"] = convert_product_images(changes["images"]) or []

    changes["updated_at"] = utc_now()

    try:
        await product.set(changes)
        return format_product_dto(product)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update product %s", product_id)
        raise HTTPException(
            status_code=500, detail="Failed to update product."
        ) from exc


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product(
    product_id: str,
    _admin: Any = Depends(require_admin),
):
    try:
        product = await Product.get(product_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Invalid product ID."
        ) from exc

    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    try:
        await product.delete()
    except Exception as exc:
        logger.exception("Failed to delete product %s", product_id)
        raise HTTPException(
            status_code=500, detail="Failed to delete product."
        ) from exc