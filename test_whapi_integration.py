from dotenv import load_dotenv
load_dotenv()

import asyncio
from app.services.whapi import send_group_notification

import logging
logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing Buy Request Notification...")
    await send_group_notification("📢 *Nieuwe Zoekopdracht!*\nIemand zoekt 2x ticket(s) voor *Awakenings*.\nMax prijs: €50.0\nTelefoon: 31612345678")
    
    print("Testing Sell Offer Notification...")
    await send_group_notification("🎟️ *Nieuw Aanbod!*\nIemand biedt 2x ticket(s) aan voor *Awakenings*.\nPrijs per ticket: €50.0\nTelefoon: 31612345678")
    print("Test finished.")

if __name__ == "__main__":
    asyncio.run(main())
