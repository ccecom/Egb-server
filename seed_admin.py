import asyncio
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment first
load_dotenv()

from database import init_db, client   # reuse the already configured client
from models import AdminUser, hash_password

async def inject_admin():
    print("🔄 Initializing database connection...")
    
    try:
        await init_db()
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return

    ADMIN_EMAIL = "akosilanggo"
    ADMIN_PASSWORD = "pogiakopalagi"

    print(f"🧹 Clearing old admin with email: {ADMIN_EMAIL}")
    try:
        await AdminUser.find({"email": ADMIN_EMAIL}).delete()
    except Exception as e:
        print(f"⚠️ Warning while clearing: {e}")

    print("🔐 Hashing password...")
    hashed_pw, salt = hash_password(ADMIN_PASSWORD)
    
    if isinstance(salt, bytes):
        salt = salt.hex()
        
    now = datetime.now(timezone.utc).isoformat()
    
    print("📥 Creating admin account...")
    try:
        new_admin = AdminUser(
            email=ADMIN_EMAIL,
            password=hashed_pw,
            salt=salt,
            fullName="",
            birthday="",
            habits="",
            created_at=now
        )
        
        await new_admin.insert()
        print("\n✅ SUCCESS! Admin account created.")
        print(f"Email    : {ADMIN_EMAIL}")
        print(f"Password : {ADMIN_PASSWORD}")
    except Exception as e:
        print(f"❌ Failed to create admin: {e}")

if __name__ == "__main__":
    asyncio.run(inject_admin())