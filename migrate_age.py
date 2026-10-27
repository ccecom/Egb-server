import asyncio
from models import User
from database import init_db

async def migrate_user_data():
    print("🚀 Starting database migration...")

    await init_db()

    # Fix users where age is not a string
    updated_count = 0
    async for user in User.find({}):
        needs_update = False

        # Fix age field
        if not isinstance(user.age, str):
            user.age = str(user.age) if user.age is not None else "N/A"
            needs_update = True
            print(f"Fixed age for: {user.email} → {user.age}")

        # You can add more fixes here if needed
        # Example: fix other fields
        # if not isinstance(user.mobile, str):
        #     user.mobile = str(user.mobile) if user.mobile else ""

        if needs_update:
            await user.save()
            updated_count += 1

    print(f"\n✅ Migration completed! Updated {updated_count} users.")

if __name__ == "__main__":
    asyncio.run(migrate_user_data())