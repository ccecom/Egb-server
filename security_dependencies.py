
import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger("EGB_Backyard_Security")

# Use the same secret and algorithm that your login route uses to sign tokens.
JWT_SECRET_KEY = (
    os.getenv("SECRET_KEY", "").strip()
    or os.getenv("JWT_SECRET_KEY", "").strip()
)

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256").strip()

# Keep the accepted algorithms explicit.
ALLOWED_JWT_ALGORITHMS = {"HS256"}

if JWT_ALGORITHM not in ALLOWED_JWT_ALGORITHMS:
    logger.error("Unsupported JWT algorithm configured: %s", JWT_ALGORITHM)

bearer = HTTPBearer(auto_error=False)

ADMIN_ROLES = {
    "admin",
    "administrator",
    "super_admin",
    "superadmin",
}


def authentication_error(
    detail: str = "Authentication required.",
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    """
    Validate the signed JWT and return normalized user claims.

    The token must contain a valid subject ('sub'). Tokens issued by the
    login endpoint should also contain an expiration ('exp') claim.
    """

    if not JWT_SECRET_KEY or JWT_ALGORITHM not in ALLOWED_JWT_ALGORITHMS:
        logger.error("JWT authentication is not configured correctly.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server.",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error()

    token = credentials.credentials

    try:
        claims = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={
                "require_sub": True,
            },
        )
    except JWTError:
        raise authentication_error(
            "Invalid or expired access token."
        ) from None

    if not isinstance(claims, dict):
        raise authentication_error("Invalid access token payload.")

    subject = claims.get("sub")

    if not isinstance(subject, (str, int)) or not str(subject).strip():
        raise authentication_error("Invalid access token subject.")

    # Normalize role claims without treating arbitrary users as admins.
    raw_role = (
        claims.get("role")
        or claims.get("user_role")
        or claims.get("account_role")
        or ""
    )

    role = str(raw_role).strip().lower()

    # Preserve signed claims and provide consistent fields to route handlers.
    user: dict[str, Any] = {
        **claims,
        "id": str(subject),
        "role": role,
    }

    return user


async def require_admin(
    user: dict[str, Any] = Depends(require_current_user),
) -> dict[str, Any]:
    """
    Require an administrator for product creation, editing, deletion,
    image uploads, and other protected administrative operations.
    """

    role = str(user.get("role", "")).strip().lower()

    # Support an explicit boolean admin claim in a signed token.
    # The login endpoint must set this claim only for verified admins.
    is_admin_claim = user.get("is_admin") is True
    is_super_admin_claim = user.get("is_super_admin") is True

    if (
        role not in ADMIN_ROLES
        and not is_admin_claim
        and not is_super_admin_claim
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )

    return user
