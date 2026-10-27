import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from bson import ObjectId
from models import User

logger = logging.getLogger("CommercePrime_Analytics")
router = APIRouter()


# ---------------------------------------------------------
# ROUTE 1: Dashboard Metrics
# ---------------------------------------------------------
@router.get('/analytics')
async def get_admin_analytics():
    try:
        total_users = await User.count()
        verified_users = await User.find({"isVerified": True}).count()
        active_users = await User.find({"status": "Active"}).count()

        verified_percentage = 0
        if total_users > 0:
            verified_percentage = round((verified_users / total_users) * 100)

        return {
            "success": True,
            "totalUsers": total_users,
            "verifiedPercentage": f"{verified_percentage}%",
            "verifiedAccounts": verified_users,
            "activeStatus": active_users
        }

    except Exception as e:
        logger.error(f"Analytics retrieval error: {e}", exc_info=True)
        # Note: Retained JSON structure to avoid frontend breakage
        return JSONResponse(
            status_code=500, 
            content={"success": False, "message": "Server error while fetching metrics."}
        )


# ---------------------------------------------------------
# ROUTE 2: Get All Users
# ---------------------------------------------------------
@router.get('/users')
async def get_all_users():
    try:
        users = await User.find_all().to_list()
        users_list = []

        for user in users:
            # Convert to dictionary and handle sensitive data securely
            user_data = user.dict() if hasattr(user, 'dict') else dict(user)
            
            # Convert ObjectId to string
            if hasattr(user, 'id'):
                user_data["_id"] = str(user.id)
            elif '_id' in user_data:
                user_data["_id"] = str(user_data["_id"])
            
            # Remove sensitive fields before sending to frontend
            user_data.pop("salt", None)
            user_data.pop("password", None)
            
            users_list.append(user_data)

        return {"success": True, "users": users_list}

    except Exception as e:
        logger.error(f"Error fetching users for admin panel: {e}", exc_info=True)
        return JSONResponse(
            status_code=500, 
            content={"success": False, "message": "Server error while fetching user list."}
        )


# ---------------------------------------------------------
# ROUTE 3: Delete User
# ---------------------------------------------------------
@router.delete('/users/{user_id}')
async def delete_user(user_id: str):
    try:
        if not ObjectId.is_valid(user_id):
            return JSONResponse(
                status_code=400, 
                content={"success": False, "message": "Invalid user ID format."}
            )

        user = await User.get(user_id)
        
        if not user:
            return JSONResponse(
                status_code=404, 
                content={"success": False, "message": "User not found."}
            )

        await user.delete()
        logger.info(f"Admin deleted user account: {user_id}")
        return {"success": True, "message": "User deleted successfully."}

    except Exception as e:
        logger.error(f"Server error while deleting user {user_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500, 
            content={"success": False, "message": "Server error processing account deletion."}
        )
