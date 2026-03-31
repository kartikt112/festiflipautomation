import asyncio
import logging
from app.services.verifier import verifier

logging.basicConfig(level=logging.INFO)

async def test_verificaion():
    events = [
        "Lowlands",
        "Pinkpop",
        "Mysteryland",
        "NonExistentFestivalX123"
    ]
    
    print(f"{'EVENT':<25} | {'REAL':<5} | {'AMBIGUOUS':<9} | {'TYPES'}")
    print("-" * 100)
    
    # DEBUG: Try simple search with backends
    from duckduckgo_search import DDGS
    
    print("DEBUG: Testing default backend...")
    try:
        print(DDGS().text("Lowlands Festival", max_results=1))
    except Exception as e: print(e)

    print("DEBUG: Testing 'lite' backend...")
    try:
        print(DDGS().text("Lowlands Festival", backend="lite", max_results=1))
    except Exception as e: print(e)
    
    print("DEBUG: Testing 'html' backend...")
    try:
        print(DDGS().text("Lowlands Festival", backend="html", max_results=1))
    except Exception as e: print(e)

    for event in events:
        try:
            result = await verifier.verify_event(event)
            types = ", ".join(result.get("ticket_types", [])[:3])
            print(f"{event:<25} | {str(result.get('is_real')):<5} | {str(result.get('ambiguous')):<9} | {types}")
        except Exception as e:
            print(f"{event:<25} | ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_verificaion())
