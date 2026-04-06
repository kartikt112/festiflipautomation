"""Admin dashboard router – server-rendered HTML pages."""

import logging
import io
import csv
from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.crud import sell_offers as sell_crud
from app.crud import buy_requests as buy_crud
from app.crud import reservations as res_crud
from app.crud import payments as pay_crud
from app.models.sell_offer import VerificationStatus, OfferStatus
from app.models.user import User
from app.models.webhook_log import WebhookLog
from app.services.stripe_service import create_refund
from sqlalchemy import select, func

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="app/templates")


# ─── Dashboard ───

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Main admin dashboard with stats."""
    from app.models.sell_offer import SellOffer
    from app.models.buy_request import BuyRequest
    from app.models.reservation import Reservation
    from app.models.payment import Payment

    # Get counts
    offers_result = await db.execute(select(func.count(SellOffer.id)))
    offers_count = offers_result.scalar() or 0

    available_result = await db.execute(
        select(func.count(SellOffer.id)).where(SellOffer.status == OfferStatus.AVAILABLE)
    )
    available_count = available_result.scalar() or 0

    requests_result = await db.execute(select(func.count(BuyRequest.id)))
    requests_count = requests_result.scalar() or 0

    reservations_result = await db.execute(select(func.count(Reservation.id)))
    reservations_count = reservations_result.scalar() or 0

    payments_result = await db.execute(select(func.count(Payment.id)))
    payments_count = payments_result.scalar() or 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "offers_count": offers_count,
        "available_count": available_count,
        "requests_count": requests_count,
        "reservations_count": reservations_count,
        "payments_count": payments_count,
    })


# ─── Listings ───

@router.get("/listings", response_class=HTMLResponse)
async def listings(request: Request, db: AsyncSession = Depends(get_db)):
    """View all sell offers."""
    offers = await sell_crud.get_all_offers(db)
    return templates.TemplateResponse("listings.html", {
        "request": request,
        "offers": offers,
    })


# ─── Buy Requests ───

@router.get("/requests", response_class=HTMLResponse)
async def buy_requests_page(request: Request, db: AsyncSession = Depends(get_db)):
    """View all buy requests."""
    requests_list = await buy_crud.get_all_requests(db)
    return templates.TemplateResponse("requests.html", {
        "request": request,
        "buy_requests": requests_list,
    })


# ─── Reservations ───

@router.get("/reservations", response_class=HTMLResponse)
async def reservations_page(request: Request, db: AsyncSession = Depends(get_db)):
    """View all reservations."""
    reservations = await res_crud.get_all_reservations(db)
    return templates.TemplateResponse("reservations.html", {
        "request": request,
        "reservations": reservations,
    })


# ─── Payments ───

@router.get("/payments", response_class=HTMLResponse)
async def payments_page(request: Request, db: AsyncSession = Depends(get_db)):
    """View all payments."""
    payments = await pay_crud.get_all_payments(db)
    return templates.TemplateResponse("payments.html", {
        "request": request,
        "payments": payments,
    })


# ─── Seller Verification ───

@router.get("/sellers", response_class=HTMLResponse)
async def sellers_page(request: Request, db: AsyncSession = Depends(get_db)):
    """View all sellers with verification status (unverified first)."""
    from app.models.sell_offer import SellOffer
    result = await db.execute(
        select(SellOffer)
        .order_by(
            # Unverified first, then verified, then trusted
            (SellOffer.verification_status == VerificationStatus.UNVERIFIED).desc(),
            SellOffer.created_at.desc(),
        )
    )
    sellers = list(result.scalars().all())
    return templates.TemplateResponse("sellers.html", {
        "request": request,
        "sellers": sellers,
    })


@router.post("/sellers/{offer_id}/verify")
async def verify_seller(
    offer_id: int,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Manually verify a seller."""
    try:
        v_status = VerificationStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")

    await sell_crud.verify_seller(db, offer_id, v_status)
    await db.commit()
    return {"status": "ok", "verification_status": status}


# ─── Blacklist ───

@router.post("/users/{user_id}/blacklist")
async def blacklist_user(
    user_id: int,
    reason: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Blacklist a user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.blacklisted = True
    user.blacklist_reason = reason
    await db.commit()
    return {"status": "ok", "user_id": user_id}


# ─── Refund ───

@router.post("/payments/{payment_id}/refund")
async def refund_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a Stripe refund for a payment."""
    from app.models.payment import Payment, PaymentStatus
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if not payment.stripe_payment_intent_id:
        raise HTTPException(status_code=400, detail="No Stripe payment intent")

    try:
        refund = await create_refund(payment.stripe_payment_intent_id)
        payment.status = PaymentStatus.REFUNDED
        await db.commit()
        return {"status": "ok", "refund_id": refund.get("id")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Webhook Logs ───

@router.get("/webhooks", response_class=HTMLResponse)
async def webhook_logs(request: Request, db: AsyncSession = Depends(get_db)):
    """View webhook event logs."""
    result = await db.execute(
        select(WebhookLog).order_by(WebhookLog.created_at.desc()).limit(100)
    )
    logs = list(result.scalars().all())
    return templates.TemplateResponse("webhook_logs.html", {
        "request": request,
        "logs": logs,
    })


# ─── Excel Export ───

@router.get("/export/{table}")
async def export_table(table: str, db: AsyncSession = Depends(get_db)):
    """Export table data as CSV (Excel-compatible)."""
    from app.models.sell_offer import SellOffer
    from app.models.buy_request import BuyRequest
    from app.models.reservation import Reservation

    model_map = {
        "sell_offers": SellOffer,
        "buy_requests": BuyRequest,
        "reservations": Reservation,
    }

    if table not in model_map:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")

    model = model_map[table]
    result = await db.execute(select(model).order_by(model.created_at.desc()))
    records = list(result.scalars().all())

    if not records:
        return StreamingResponse(
            io.StringIO("No data"),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table}.csv"},
        )

    # Build CSV
    output = io.StringIO()
    columns = [c.name for c in model.__table__.columns]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()

    for record in records:
        row = {col: getattr(record, col, None) for col in columns}
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={table}.csv"},
    )


# ─── Event Configuration (Price Rules + Editions) ───

@router.get("/events", response_class=HTMLResponse)
async def events_config_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Manage event price rules and edition settings."""
    from app.crud.event_configs import get_all_configs
    configs = await get_all_configs(db)
    return templates.TemplateResponse("event_configs.html", {
        "request": request,
        "configs": configs,
    })


@router.post("/events/create")
async def create_event_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new event config."""
    from app.models.event_config import EventConfig
    data = await request.form()

    event_date = None
    if data.get("event_date"):
        from datetime import date
        try:
            event_date = date.fromisoformat(str(data["event_date"]))
        except ValueError:
            pass

    min_price = float(data["min_price"]) if data.get("min_price") else None
    max_price = float(data["max_price"]) if data.get("max_price") else None

    config = EventConfig(
        event_keyword=str(data["event_keyword"]).strip(),
        event_date=event_date,
        min_price=min_price,
        max_price=max_price,
        ask_edition=bool(data.get("ask_edition")),
        notes=str(data.get("notes", "")).strip() or None,
    )
    db.add(config)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/events", status_code=303)


@router.post("/events/{config_id}/delete")
async def delete_event_config(config_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an event config."""
    from app.crud.event_configs import get_config_by_id
    config = await get_config_by_id(db, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.delete(config)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/events", status_code=303)


@router.post("/events/{config_id}/update")
async def update_event_config(
    config_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update an event config."""
    from app.crud.event_configs import get_config_by_id
    config = await get_config_by_id(db, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    data = await request.form()

    config.event_keyword = str(data["event_keyword"]).strip()

    if data.get("event_date"):
        from datetime import date
        try:
            config.event_date = date.fromisoformat(str(data["event_date"]))
        except ValueError:
            config.event_date = None
    else:
        config.event_date = None

    config.min_price = float(data["min_price"]) if data.get("min_price") else None
    config.max_price = float(data["max_price"]) if data.get("max_price") else None
    config.ask_edition = bool(data.get("ask_edition"))
    config.notes = str(data.get("notes", "")).strip() or None

    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/events", status_code=303)


# ─── Reseller Inventory ───

@router.get("/resellers", response_class=HTMLResponse)
async def resellers_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Manage reseller inventory."""
    from app.models.fixed_reseller import FixedReseller
    from app.models.reseller_inventory import ResellerInventory

    resellers_result = await db.execute(select(FixedReseller).order_by(FixedReseller.name))
    resellers = list(resellers_result.scalars().all())

    inventory_result = await db.execute(
        select(ResellerInventory).order_by(ResellerInventory.created_at.desc())
    )
    inventory = list(inventory_result.scalars().all())

    return templates.TemplateResponse("resellers.html", {
        "request": request,
        "resellers": resellers,
        "inventory": inventory,
    })


@router.post("/resellers/create")
async def create_reseller(request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new fixed reseller."""
    from app.models.fixed_reseller import FixedReseller
    data = await request.form()

    reseller = FixedReseller(
        name=str(data["name"]).strip(),
        phone=str(data.get("phone", "")).strip() or None,
        pricing_model=str(data.get("pricing_model", "")).strip() or None,
        notes=str(data.get("notes", "")).strip() or None,
    )
    db.add(reseller)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/resellers", status_code=303)


@router.post("/resellers/inventory/add")
async def add_inventory_item(request: Request, db: AsyncSession = Depends(get_db)):
    """Add a ticket to reseller inventory."""
    from app.models.reseller_inventory import ResellerInventory
    data = await request.form()

    event_date = None
    if data.get("event_date"):
        from datetime import date
        try:
            event_date = date.fromisoformat(str(data["event_date"]))
        except ValueError:
            pass

    item = ResellerInventory(
        reseller_id=int(data["reseller_id"]),
        event_name=str(data["event_name"]).strip(),
        event_date=event_date,
        ticket_type=str(data.get("ticket_type", "")).strip() or None,
        quantity=int(data.get("quantity", 1)),
        price_per_ticket=float(data["price_per_ticket"]),
        notes=str(data.get("notes", "")).strip() or None,
    )
    db.add(item)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/resellers", status_code=303)


@router.post("/resellers/inventory/{item_id}/delete")
async def delete_inventory_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an inventory item."""
    from app.models.reseller_inventory import ResellerInventory
    result = await db.execute(select(ResellerInventory).where(ResellerInventory.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/resellers", status_code=303)


# ─── Chat Dashboard ───

@router.get("/chats", response_class=HTMLResponse)
async def chats_page(
    request: Request,
    phone: str = None,
    db: AsyncSession = Depends(get_db),
):
    """View all WhatsApp conversations."""
    from app.models.chat_message import ChatMessage
    from sqlalchemy import distinct

    # Get all unique contacts with their last message + count
    contacts_query = await db.execute(
        select(
            ChatMessage.phone,
            func.count(ChatMessage.id).label("count"),
            func.max(ChatMessage.created_at).label("last_time"),
        )
        .group_by(ChatMessage.phone)
        .order_by(func.max(ChatMessage.created_at).desc())
    )
    contacts_raw = contacts_query.all()

    contacts = []
    for row in contacts_raw:
        # Get last message text for preview
        last_msg_result = await db.execute(
            select(ChatMessage.body)
            .where(ChatMessage.phone == row.phone)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_body = last_msg_result.scalar() or ""

        contacts.append({
            "phone": row.phone,
            "count": row.count,
            "last_message": last_body,
            "last_time": row.last_time.strftime("%H:%M") if row.last_time else "",
        })

    # Get messages for selected phone
    messages = []
    if phone:
        msgs_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.phone == phone)
            .order_by(ChatMessage.created_at.asc())
        )
        messages = list(msgs_result.scalars().all())

    # Check if bot is paused for selected phone
    bot_paused = False
    if phone:
        from app.models.chat_session import ChatSession
        sess_result = await db.execute(select(ChatSession).where(ChatSession.phone == phone))
        sess = sess_result.scalar_one_or_none()
        if sess:
            bot_paused = getattr(sess, "bot_paused", False)

    return templates.TemplateResponse("chats.html", {
        "request": request,
        "contacts": contacts,
        "selected_phone": phone,
        "messages": messages,
        "bot_paused": bot_paused,
    })


@router.post("/chats/send")
async def send_chat_message(request: Request, db: AsyncSession = Depends(get_db)):
    """Send a WhatsApp message from the admin dashboard."""
    from app.models.chat_message import ChatMessage, MessageDirection
    from app.services.whatsapp import send_text_message

    data = await request.json()
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()

    if not phone or not message:
        raise HTTPException(status_code=400, detail="Phone and message are required")

    try:
        await send_text_message(phone, message)
        db.add(ChatMessage(phone=phone, direction=MessageDirection.OUTBOUND, body=message))
        await db.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Admin send message failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chats/stream")
async def chat_stream(phone: str, db: AsyncSession = Depends(get_db)):
    """SSE endpoint for real-time chat updates. Streams new messages as they arrive."""
    from fastapi.responses import StreamingResponse
    from app.models.chat_message import ChatMessage
    import asyncio
    import json

    async def event_generator():
        last_id = 0
        # Get the latest message ID as starting point
        result = await db.execute(
            select(func.max(ChatMessage.id)).where(ChatMessage.phone == phone)
        )
        last_id = result.scalar() or 0

        while True:
            await asyncio.sleep(1.5)  # Poll interval
            try:
                # Check for new messages since last_id
                result = await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.phone == phone, ChatMessage.id > last_id)
                    .order_by(ChatMessage.id.asc())
                )
                new_msgs = list(result.scalars().all())

                if new_msgs:
                    last_id = new_msgs[-1].id
                    for msg in new_msgs:
                        data = json.dumps({
                            "id": msg.id,
                            "direction": msg.direction.value,
                            "body": msg.body,
                            "time": msg.created_at.strftime("%I:%M %p"),
                            "date": msg.created_at.strftime("%d %B %Y"),
                        })
                        yield f"data: {data}\n\n"
                else:
                    yield ": keepalive\n\n"
            except Exception:
                yield ": error\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chats/pause")
async def toggle_bot_pause(request: Request, db: AsyncSession = Depends(get_db)):
    """Toggle bot on/off for a specific chat. When paused, bot won't auto-reply."""
    from app.models.chat_session import ChatSession
    from app.crud.chat_sessions import get_or_create_session

    data = await request.json()
    phone = data.get("phone", "").strip()
    paused = data.get("paused", True)

    if not phone:
        raise HTTPException(status_code=400, detail="Phone is required")

    session = await get_or_create_session(db, phone)
    session.bot_paused = bool(paused)
    await db.commit()

    status = "paused" if paused else "active"
    logger.info(f"Bot {status} for {phone}")
    return {"status": "ok", "bot_paused": session.bot_paused}


@router.post("/chats/reset")
async def reset_chat_session(request: Request, db: AsyncSession = Depends(get_db)):
    """Reset a user's chat session from the admin dashboard."""
    from app.models.chat_session import ChatSession

    data = await request.json()
    phone = data.get("phone", "").strip()

    if not phone:
        raise HTTPException(status_code=400, detail="Phone is required")

    result = await db.execute(select(ChatSession).where(ChatSession.phone == phone))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()

    return {"status": "ok"}


@router.post("/chats/upload")
async def upload_and_send_media(
    phone: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload and send a media file via WhatsApp from the admin dashboard."""
    from app.models.chat_message import ChatMessage, MessageDirection
    from app.services.whatsapp import upload_media_to_whatsapp, send_media_by_type

    if not phone:
        raise HTTPException(status_code=400, detail="Phone is required")

    content = await file.read()
    mime = file.content_type or "application/octet-stream"

    # Determine media type
    if mime.startswith("image/"):
        media_type = "image"
    elif mime.startswith("video/"):
        media_type = "video"
    elif mime.startswith("audio/"):
        media_type = "audio"
    else:
        media_type = "document"

    type_emoji = {"image": "📷", "video": "🎥", "audio": "🎤", "document": "📄"}
    label = f"[{type_emoji.get(media_type, '📎')} {media_type.title()}]"
    if caption:
        label += f" {caption}"

    # Upload to WhatsApp
    media_id = await upload_media_to_whatsapp(content, mime, file.filename)
    if not media_id:
        raise HTTPException(status_code=500, detail="Media upload to WhatsApp failed")

    # Send to user
    await send_media_by_type(phone, media_id, media_type, caption or None)

    # Log in chat
    db.add(ChatMessage(phone=phone, direction=MessageDirection.OUTBOUND, body=label, message_type=media_type))
    await db.commit()

    return {"status": "ok", "media_type": media_type}
