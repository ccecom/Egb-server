import os
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field
from jose import JWTError, jwt
from beanie import PydanticObjectId

from models import User, AdminUser, Order, hash_password, verify_password

# ── Logging Configuration ─────────────────────────────────
logger = logging.getLogger("CommercePrime_Auth")

# ── Environment & Security Settings ───────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "cc-eshop-super-secret-key-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

router = APIRouter(tags=["Authentication"])


# =========================================================================
# ADMIN SCHEMAS (Email + Password only)
# =========================================================================
class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminSetupRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=6)


class AdminUpdateRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6)


# =========================================================================
# CUSTOMER USER SCHEMAS
# =========================================================================
class UserRegister(BaseModel):
    fullName: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    mobile: Optional[str] = None
    birthDate: Optional[str] = None
    gender: Optional[str] = "Other"
    facebook: Optional[str] = None
    age: Optional[Any] = None


class UserLogin(BaseModel):
    email: str
    password: str


class VerifyRequest(BaseModel):
    clientSequence: List[int]


class UserUpdate(BaseModel):
    fullName: Optional[str] = Field(None, min_length=2, max_length=100)
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    mobile: Optional[str] = None
    birthDate: Optional[str] = None
    gender: Optional[str] = None
    facebook: Optional[str] = None
    avatar: Optional[str] = None
    age: Optional[Any] = None


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "_id": str(user.id),
        "fullName": user.fullName or "",
        "username": user.username or "",
        "email": user.email or "",
        "mobile": user.mobile or "",
        "birthDate": user.birthDate or "",
        "gender": user.gender or "Other",
        "facebook": user.facebook or "",
        "avatar": user.avatar or "",
        "age": user.age or "N/A",
        "membershipTier": user.membershipTier or "CC Prime",
        "accountStatus": user.status or "Active",
        "status": user.status or "Active",
        "isVerified": bool(user.isVerified),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at if hasattr(user, 'created_at') else "",
    }


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """For normal customer endpoints only"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role", "user")

        if user_id is None:
            logger.warning("JWT validation failed: 'sub' claim missing.")
            raise credentials_exception

        # Reject admin tokens on customer endpoints
        if role == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin token cannot access user endpoints"
            )

        obj_id = PydanticObjectId(user_id)
    except JWTError as e:
        logger.warning(f"JWT validation failed: {str(e)}")
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {str(e)}", exc_info=True)
        raise credentials_exception

    try:
        user = await User.get(obj_id)
        if user is None:
            logger.warning(f"JWT validation failed: User {user_id} not found in database.")
            raise credentials_exception
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error while fetching current user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_current_admin(token: Annotated[str, Depends(oauth2_scheme)]) -> AdminUser:
    """Dependency for admin-only routes"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id: str = payload.get("sub")
        role: str = payload.get("role")

        if admin_id is None or role != "super_admin":
            raise credentials_exception

        obj_id = PydanticObjectId(admin_id)
    except JWTError:
        raise credentials_exception
    except Exception:
        raise credentials_exception

    try:
        admin = await AdminUser.get(obj_id)
        if admin is None:
            raise credentials_exception
        return admin
    except Exception:
        raise credentials_exception


# =========================================================================
# ADMIN ROUTES (Email + Password only)
# =========================================================================
@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    try:
        admin = await AdminUser.find_one({"email": req.email.strip().lower()})
    except Exception as e:
        logger.error(f"Database error during admin login query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password"
    )

    if not admin:
        logger.warning(f"Admin login failed: Account not found for email {req.email}")
        raise auth_error

    if not verify_password(admin.password, admin.salt, req.password.strip()):
        logger.warning(f"Admin login failed: Invalid password for {req.email}")
        raise auth_error

    logger.info(f"Successful admin login for: {admin.email}")

    access_token = create_access_token(
        data={"sub": str(admin.id), "role": "super_admin"},
        expires_delta=timedelta(minutes=60 * 24)  # 24 hours
    )

    return {
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "admin_email": admin.email,
        "role": "super_admin"
    }


@router.put("/admin/update/{admin_id}")
async def update_admin_info(
    admin_id: str,
    update_data: AdminUpdateRequest,
    current_admin: AdminUser = Depends(get_current_admin)
):
    try:
        admin = await AdminUser.get(PydanticObjectId(admin_id))
    except Exception as e:
        logger.error(f"Invalid admin ID format submitted: {admin_id} - Error: {e}")
        raise HTTPException(status_code=400, detail="Invalid admin ID format")

    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")

    try:
        if update_data.email is not None:
            admin.email = update_data.email.strip().lower()
        if update_data.password is not None:
            hashed_pw, salt = hash_password(update_data.password)
            if isinstance(salt, bytes):
                salt = salt.hex()
            admin.password = hashed_pw
            admin.salt = salt

        await admin.save()
        logger.info(f"Admin information updated successfully for ID: {admin_id}")
        
    except Exception as e:
        logger.error(f"Database error updating admin {admin_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while updating admin data.")

    return {
        "success": True,
        "message": "Admin account information updated successfully",
        "admin": {
            "id": str(admin.id),
            "email": admin.email
        }
    }


@router.post("/admin/setup")
async def setup_initial_admin(req: AdminSetupRequest):
    """
    Create the first admin account.
    Only email + password are required.
    """
    try:
        email = req.email.strip().lower()
        exists = await AdminUser.find_one({"email": email})
        if exists:
            return {"success": False, "message": "Admin with this email already exists."}

        hashed_pw, salt = hash_password(req.password)
        if isinstance(salt, bytes):
            salt = salt.hex()
            
        now = datetime.now(timezone.utc).isoformat()

        new_admin = AdminUser(
            email=email,
            password=hashed_pw,
            salt=salt,
            fullName="",
            birthday="",
            habits="",
            created_at=now
        )
        await new_admin.insert()
        logger.info(f"Initial admin user '{email}' successfully created.")
        
        return {
            "success": True,
            "message": "Admin account created successfully.",
            "admin_id": str(new_admin.id),
            "email": new_admin.email
        }
    except Exception as e:
        logger.error(f"Failed to setup initial admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during admin setup.")


# =========================================================================
# CUSTOMER USER REGISTRATION & AUTHENTICATION
# =========================================================================
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    try:
        existing_email = await User.find_one({"email": user_data.email})
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        existing_username = await User.find_one({"username": user_data.username})
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        hashed_pw, salt = hash_password(user_data.password)
        if isinstance(salt, bytes):
            salt = salt.hex()
            
        now = datetime.now(timezone.utc).isoformat()

        new_user = User(
            email=user_data.email,
            password=hashed_pw,
            salt=salt,
            username=user_data.username,
            fullName=user_data.fullName,
            mobile=user_data.mobile or "",
            birthDate=user_data.birthDate or "",
            gender=user_data.gender or "Other",
            facebook=user_data.facebook or "",
            avatar="",
            age=str(user_data.age) if user_data.age else "N/A",
            membershipTier="CC Prime",
            status="Active",
            isVerified=True,
            is_admin=False,
            created_at=now,
        )

        await new_user.insert()
        logger.info(f"New customer registered and verified: {new_user.email}")

        return {
            "success": True,
            "message": "Registration and verification successful",
            "user": user_to_dict(new_user),
            "userId": str(new_user.id),
            "_id": str(new_user.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error during user registration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during registration.")


@router.post("/login")
async def login(request: Request):
    email = ""
    password = ""
    content_type = request.headers.get("content-type", "")
    
    try:
        if "application/x-www-form-urlencoded" in content_type:
            form_data = await request.form()
            email = form_data.get("username")
            password = form_data.get("password")
        else:
            json_data = await request.json()
            email = json_data.get("email")
            password = json_data.get("password")
    except Exception as e:
        logger.warning(f"Failed to parse login request payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid request payload")

    if not email or not password:
        logger.warning("Login failed: Missing email or password in request.")
        raise HTTPException(status_code=400, detail="Email and password are required")

    try:
        user = await User.find_one({"email": email})
    except Exception as e:
        logger.error(f"Database error during user login query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not user:
        logger.warning(f"Customer login failed: Account not found for email {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(user.password, user.salt, password):
        logger.warning(f"Customer login failed: Invalid password for {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "Active":
        logger.warning(f"Login blocked: Account {email} is not active. Status: {user.status}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    logger.info(f"Successful customer login for: {email}")

    return {
        "success": True,
        "message": "Login successful",
        "token": access_token,
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_to_dict(user),
        "_id": str(user.id),
        "userId": str(user.id),
    }


@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user)):
    return user_to_dict(current_user)


@router.put("/profile")
async def update_profile(update_data: UserUpdate, current_user: User = Depends(get_current_user)):
    try:
        if update_data.username and update_data.username != current_user.username:
            existing = await User.find_one({"username": update_data.username})
            if existing:
                logger.info(f"Profile update failed: Username collision ({update_data.username}) by user {current_user.id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already taken",
                )
            current_user.username = update_data.username

        if update_data.fullName is not None:
            current_user.fullName = update_data.fullName
        if update_data.mobile is not None:
            current_user.mobile = update_data.mobile
        if update_data.birthDate is not None:
            current_user.birthDate = update_data.birthDate
        if update_data.gender is not None:
            current_user.gender = update_data.gender
        if update_data.facebook is not None:
            current_user.facebook = update_data.facebook
        if update_data.avatar is not None:
            current_user.avatar = update_data.avatar
        if update_data.age is not None:
            current_user.age = str(update_data.age).strip() or "N/A"

        await current_user.save()
        logger.info(f"Profile updated successfully for user ID: {current_user.id}")
        return user_to_dict(current_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error updating profile for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while updating profile.")


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return user_to_dict(current_user)


@router.get("/{user_id}")
async def get_user_by_id(user_id: str, current_user: User = Depends(get_current_user)):
    try:
        obj_id = PydanticObjectId(user_id)
    except Exception as e:
        logger.warning(f"Invalid user ID format requested: {user_id} - Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID format"
        )
    
    try:
        user = await User.get(obj_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found"
            )
        return user_to_dict(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error fetching user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/verify/{user_id}")
async def verify_user(user_id: str, data: VerifyRequest):
    try:
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found"
            )
        
        user.isVerified = True
        await user.save()
        logger.info(f"User {user_id} successfully verified.")
        
        return {
            "success": True, 
            "message": "User verified successfully",
            "userId": str(user.id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during verification process for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID format or verification failed"
        )


@router.delete("/me")
@router.delete("/{user_id}")
async def delete_user(user_id: Optional[str] = None, current_user: User = Depends(get_current_user)):
    target_id = user_id or str(current_user.id)

    if not current_user.is_admin and target_id != str(current_user.id):
        logger.warning(f"Unauthorized deletion attempt by user {current_user.id} on target {target_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission to delete this account"
        )

    try:
        obj_id = PydanticObjectId(target_id)
    except Exception as e:
        logger.warning(f"Invalid User ID format for deletion: {target_id} - Error: {e}")
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    try:
        target_user = await User.get(obj_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        await Order.find({"user_id": target_id}).delete()
        await target_user.delete()
        
        logger.info(f"User {target_id} and associated orders were completely deleted.")

        return {
            "success": True,
            "message": f"User {target_id} and all associated orders deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error while deleting user {target_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during account deletion.")