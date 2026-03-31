import asyncio
import logging
import sys
from unittest.mock import AsyncMock, patch
from sqlalchemy import text
from app.database import async_session, init_db
from app.ai.state_machine import process_message

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

BUYER_PHONE = "+316TESTBUYER"
SELLER_PHONE = "+316TESTSELLER"
EVENT_NAME = "Tomorrowland 2026"

async def clean_slate(db):
    """Clean up test data."""
    logger.info("Cleaning up previous test data...")
    try:
        await db.execute(text("DELETE FROM chat_sessions WHERE phone IN (:b, :s)"), {"b": BUYER_PHONE, "s": SELLER_PHONE})
        await db.execute(text("DELETE FROM buy_requests WHERE phone = :p"), {"p": BUYER_PHONE})
        await db.execute(text("DELETE FROM sell_offers WHERE phone = :p"), {"p": SELLER_PHONE})
        await db.commit()
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

async def run_conversation(db, phone, messages):
    """Run a sequence of messages for a user."""
    logger.info(f"--- Conversation with {phone} ---")
    for msg in messages:
        print(f"USER ({phone}): {msg}")
        reply = await process_message(db, phone, msg)
        print(f"BOT: {reply}")
        await asyncio.sleep(0.5)

async def test_waitlist_flow():
    # Helper to print captured messages
    captured_messages = []
    
    async def mock_send_text_message(phone, body):
        print(f"\n[MOCK WHATSAPP] To: {phone} | Body: {body}\n")
        captured_messages.append({"to": phone, "body": body})
        return {"status": "success"}

    # Patch the send_text_message function where it is used
    # It is imported in app.services.matching and app.services.game_logic? No, app.services.matching
    # We patch it globally in app.services.whatsapp
    with patch("app.services.whatsapp.send_text_message", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = mock_send_text_message
        
        async with async_session() as db:
            await clean_slate(db)
            
            # 1. Buyer Flow (Creates Waitlist Entry)
            logger.info("Step 1: Buyer requests unavailable ticket")
            await run_conversation(db, BUYER_PHONE, [
                f"Ik zoek 1 ticket voor {EVENT_NAME}",
                "Weekend", #  Handle ambiguity (Weekend vs Day)
                "25 juli", # Handle date prompt
                "ja"       # Confirm details
            ])
            
            # Verify Buyer got the "saved" message
            # The last bot reply should indicate it's saved.
            
            # 2. Seller Flow (Triggers Match)
            logger.info("Step 2: Seller lists matching ticket")
            await run_conversation(db, SELLER_PHONE, [
                f"Ik heb 1 ticket te koop voor {EVENT_NAME}",
                "Weekend", # Ambiguity
                "25 juli", # Date
                "75 euro", # Price
                "ja" # Confirm details
            ])
            
            # 3. Verification
            logger.info("Step 3: Verifying Waitlist Notification")
            
            # Check if Buyer received a notification
            buyer_notifications = [m for m in captured_messages if m["to"] == BUYER_PHONE]
            
            if buyer_notifications:
                print("\n✅ SUCCESS: Buyer received notification!")
                for n in buyer_notifications:
                    print(f"   Message: {n['body']}")
                    if "checkout" in n['body'].lower() or "betaal" in n['body'].lower():
                        print("   (Contains Payment Link)")
            else:
                print("\n❌ FAILURE: Buyer did NOT receive notification.")
                
            await clean_slate(db)

if __name__ == "__main__":
    asyncio.run(test_waitlist_flow())
