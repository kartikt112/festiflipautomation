"""FestiFlip – FastAPI Application Entry Point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import init_db, get_db
from app.routers import health, whatsapp, stripe_webhook, admin, whapi_webhook
from app.services.scheduler import start_scheduler, stop_scheduler

# Configure logging – stdout always; rotating file only in development
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan – startup and shutdown hooks."""
    # Startup
    logger.info(f"Starting FestiFlip ({settings.APP_ENV})")

    # Initialize database (creates tables if using SQLite for dev)
    if "sqlite" in settings.DATABASE_URL:
        await init_db()
        logger.info("SQLite database initialized")

    # Start background scheduler
    start_scheduler()

    yield

    # Shutdown
    stop_scheduler()
    logger.info("FestiFlip shutting down")


# Create FastAPI app
app = FastAPI(
    title="FestiFlip",
    description="WhatsApp Ticket Marketplace Automation – Deposit-Based System",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
from pathlib import Path as _Path
_static_dir = _Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Register routers
app.include_router(health.router)
app.include_router(whatsapp.router)
app.include_router(stripe_webhook.router)
app.include_router(admin.router)
app.include_router(whapi_webhook.router)


@app.get("/")
async def root():
    return {
        "service": "FestiFlip",
        "status": "running",
        "docs": "/docs",
        "admin": "/admin/",
    }


@app.get("/payment/success")
async def payment_success(session_id: str = "", db: AsyncSession = Depends(get_db)):
    """Handle Stripe payment success redirect.
    
    Verifies payment with Stripe and completes the reservation,
    sending seller contact info to the buyer via WhatsApp.
    """
    if not session_id:
        return {"status": "error", "message": "No session ID provided."}

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Verify payment with Stripe
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status == "paid":
            # Find and complete the reservation
            from app.crud.reservations import get_reservation_by_stripe_session
            from app.services.reservation import complete_reservation
            
            reservation = await get_reservation_by_stripe_session(db, session_id)
            if reservation and reservation.status.value == "PENDING":
                payment_intent_id = checkout_session.payment_intent or ""
                await complete_reservation(
                    db,
                    reservation_id=reservation.id,
                    stripe_payment_intent_id=payment_intent_id,
                    webhook_event_id=f"success_page_{session_id}",
                )
                logger.info(f"Payment completed via success page for session {session_id}")
            
            return {
                "status": "success",
                "message": "Betaling ontvangen! Je ontvangt de contactgegevens van de verkoper via WhatsApp.",
                "session_id": session_id,
            }
        else:
            return {
                "status": "pending",
                "message": "Betaling wordt verwerkt. Je ontvangt bericht zodra deze is bevestigd.",
                "session_id": session_id,
            }
    except Exception as e:
        logger.error(f"Payment success page error: {e}")
        return {
            "status": "processing",
            "message": "Je betaling wordt verwerkt. Je ontvangt bericht via WhatsApp zodra alles bevestigd is.",
            "session_id": session_id,
        }


@app.get("/payment/cancel")
async def payment_cancel():
    return {
        "status": "cancelled",
        "message": "Betaling geannuleerd. Je reservering is nog actief tot de timer verloopt.",
    }
