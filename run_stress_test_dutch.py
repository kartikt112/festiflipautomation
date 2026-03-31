
import asyncio
import logging
from app.ai.classifier import classify_message

# Reduce logging noise
logging.basicConfig(level=logging.ERROR)

import asyncio
import logging
import os

# Set env for testing (if needed)
# os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"

from app.database import get_db, engine, Base, async_session
from app.ai.state_machine import process_message
from sqlalchemy import text # For cleanup if needed

# Reduce logging noise
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("app.services.verifier")
logger.setLevel(logging.INFO)

async def run_stress_test():
    print(f"{'MESSAGE':<50} | {'REPLY':<80}")
    print("-" * 130)
    
    # Initialize DB tables if not exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Use a fixed phone number for testing session persistence
    phone = "+31612345678"

    async with engine.connect() as conn:
         # Optional: Clear session for fresh start
         await conn.execute(text("DELETE FROM chat_sessions WHERE phone = :p"), {"p": phone})
         await conn.commit()

    # Full Stress Test Suite
    TEST_CASES = [
        # Buy Requests
        "ik zoek 2 tickets voor Lowlands",
        "ticket gezocht voor Pinkpop 2025",
        "ik wil graag naar Mysteryland, heb je kaarten?",
        "gezocht: 2x tickets Coldpley",  # Misspelling
        
        # Sell Offers
        "ik heb 3 kaarten over voor Defqon.1",
        "te koop: 2 tickets concert Taylor Swift, 100 euro per stuk",
        "ik kan niet meer gaan naar Lowlands, wie wil mijn ticket overnemen?",
        
        # Status / Info
        "wat zijn de kosten?",
        "hoe werkt dit precies?",
        "is mijn betaling al binnen?",
        "ik heb betaald maar nog geen mail gehad",
        
        # Edge Cases / Ambiguity
        "Lowlands",  # Just event name
        "ik zoek tickets",  # Missing event
        "heb je nog iets voor morgen?",
        "ik wil van mijn tickets af",
        
        # Mixed / Complex
        "ik zoek 2 kaartjes voor Lowlands, mag max 150 euro kosten",
        "ticket gezocht, prijs maakt niet uit, als ik maar kan gaan",
    ]

    print(f"{'MESSAGE':<60} | {'BOT REPLY'}")
    print("-" * 120)

    for msg in TEST_CASES:
        print(f"\nUSER: {msg}")
        try:
            # Create a fresh session for each major test case to avoid carry-over state affecting independent tests
            # For a true stress test of state machine, we might want persistence, but for intent checks, fresh is better.
            # actually, let's keep one session per 'user' but maybe reset between unrelated intents? 
            # simplest: just run them sequentially. The state machine handles 'start over'.
            
            async with async_session() as db:
                # We use a slight delay to ensure DB commits don't race in this tight loop
                await asyncio.sleep(0.5) 
                
                reply = await process_message(db, phone, msg)
                print(f"BOT: {reply}")
                
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run_stress_test())
