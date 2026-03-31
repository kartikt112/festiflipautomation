import asyncio
from app.config import settings
from app.services.stripe_service import create_deposit_session

async def test():
    try:
        res = await create_deposit_session(123, 5.0, "Test Event", "test@example.com")
        print("Success:", res)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
