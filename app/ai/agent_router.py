import json
import logging
from decimal import Decimal
from typing import Dict, Any, Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.chat_session import ChatSession

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ---------------------------------------------------------
# SYSTEM PROMPT & TOOLS SCHEMA
# ---------------------------------------------------------

SYSTEM_PROMPT = """
Je bent de virtuele assistent van FestiFlip, een veilig platform om tickets te kopen en verkopen.
Je spreekt altijd Nederlands per WhatsApp.

Jouw doel is om gebruikers te helpen tickets te kopen of verkopen.
Je mag pas een actie uitvoeren (tools aanroepen) als je ALLE benodigde informatie hebt:
- KOPEN: evenement naam, aantal tickets, en maximale prijs per ticket (in euro's).
- VERKOPEN: evenement naam, aantal tickets, en exacte verkoopprijs per ticket (in euro's).

DOORGESTUURDE BERICHTEN / TICKET LISTINGS:
- Als een gebruiker een bericht doorstuurt dat eruitziet als een ticket listing (bijv. "TE KOOP 🎟️ ...", "tickets beschikbaar", of een gestructureerd aanbod met evenement, prijs, en aantal), dan wil de gebruiker deze tickets KOPEN, NIET verkopen.
- De gebruiker deelt het aanbod van iemand anders om aan te geven welke tickets ze willen kopen.
- Herken dit patroon: berichten met "TE KOOP", emoji's zoals 🎟️, gestructureerde info (evenement, prijs, aantal), en zinnen als "Bericht FestiFlip als je geïnteresseerd bent".
- Gebruik de gegevens uit het doorgestuurde bericht (evenement naam, prijs, aantal) om een BUY_REQUEST voor te bereiden. De prijs uit het bericht is hun maximale prijs.
- Vraag ter bevestiging: "Ik zie dat je tickets wilt kopen voor [evenement]. Klopt dat? Hoeveel tickets wil je en wat is je maximale prijs?"
- Als het bericht begint met "[Doorgestuurd]" of "[Forwarded]", behandel het ALTIJD als een koopintentie.

Als er informatie mist, MOET je EXACT een van deze vaste zinnen gebruiken om het te vragen. Verzin GEEN andere zinnen:

Als de gebruiker wil KOPEN:
- Ontbrekend evenement: Voor welk evenement wil je tickets kopen?
- Ontbrekend aantal: Hoeveel tickets wil je kopen?
- Ontbrekende MAX prijs: Wat is je maximale prijs per ticket?

Als de gebruiker wil VERKOPEN:
- Ontbrekend evenement: Voor welk evenement verkoop je tickets?
- Ontbrekend aantal: Hoeveel tickets verkoop je?
- Ontbrekende VASTE prijs: Wat is de vaste verkoopprijs per ticket?

Als je nog niet weet of de gebruiker wil kopen of verkopen, en de gebruiker zegt alleen gedag (zoals "hallo", "hoi", "hey"), begroet ze dan exact met deze welkomstzin: Hallo! Hoe kan ik je helpen met het kopen of verkopen van tickets?
Als ze geen gedag zeggen maar de intentie direct onduidelijk is, vraag dan exact: Wil je tickets kopen of verkopen?

BESCHIKBARE TICKETS BEKIJKEN:
- Als de gebruiker vraagt welke tickets er beschikbaar zijn, wat er te koop is, of het volledige aanbod wil zien → roep list_available_tickets aan.
- Voorbeelden: "Welke tickets zijn er?", "Wat hebben jullie?", "Laat me alle tickets zien", "Wat is er beschikbaar?", "Kunt u mij alle beschikbare tickets doorgeven?"
- Dit is GEEN BUY_REQUEST. De gebruiker wil eerst browsen voordat ze beslissen.
- Als de gebruiker een specifiek evenement noemt (bijv. "Welke tickets voor Lowlands?"), geef dan event_name mee als filter.

ESCALATIE REGELS:
- Als een koper bij de ingang staat en niet naar binnen kan → roep escalate_entrance_issue aan.
- Als een koper meldt dat de verkoper geen bewijs deelt (betaalbewijs, eigendomsbewijs, email, etc.) → roep escalate_missing_proof aan.

ALGEMENE VRAGEN:
- Als de gebruiker een algemene vraag stelt (hoe werkt FestiFlip, kosten, veiligheid, etc.), beantwoord deze vriendelijk.
- FestiFlip rekent 7,5% aanbetaling (min €5 per ticket). Na betaling ontvangt de koper de contactgegevens van de verkoper.

Regels voor je antwoord:
1. Stuur GEEN aanhalingstekens (\") of quotes mee in je antwoord.
2. Geef exact de zin zoals hierboven staat, voeg geen extra verklarende tekst toe.
3. Als de gebruiker onduidelijk is, wees behulpzaam en kort van stof. Weiger beleefd verzoeken die niet over tickets gaan.
"""

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "submit_buy_request",
            "description": "Call this ONLY when you have collected the event name, quantity, and max price from a buyer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the festival or concert"},
                    "quantity": {"type": "integer", "description": "How many tickets they want"},
                    "max_price": {"type": "number", "description": "Their maximum budget per ticket in euros"}
                },
                "required": ["event_name", "quantity", "max_price"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_sell_offer",
            "description": "Call this ONLY when you have collected the event name, quantity, and exact selling price from a seller.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The name of the festival or concert"},
                    "quantity": {"type": "integer", "description": "How many tickets they are selling"},
                    "price_per_ticket": {"type": "number", "description": "The exact selling price per ticket in euros"}
                },
                "required": ["event_name", "quantity", "price_per_ticket"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_entrance_issue",
            "description": "Call this when a buyer reports they are at the event entrance but cannot get in (ticket not working, QR code invalid, access denied).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "The event name if mentioned"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_missing_proof",
            "description": "Call this when a buyer reports the seller is not sharing proof of payment, ticket ownership, email, or other required info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "details": {"type": "string", "description": "Summary of what proof is missing"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_tickets",
            "description": "Call this when the user asks to see, browse, or list available tickets. Use event_name to filter by a specific event, or leave empty to show all.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "Optional event name to filter by. Leave empty to list all available tickets."}
                },
                "required": []
            }
        }
    }
]

# ---------------------------------------------------------
# BACKEND TOOL HANDLERS
# ---------------------------------------------------------

async def handle_escalate_entrance(phone: str, args: Dict[str, Any]) -> str:
    from app.services.escalation import escalate_entrance_blocked
    event_name = args.get("event_name", "")
    await escalate_entrance_blocked(phone, event_name)
    from app.message_templates.templates import escalation_entrance_blocked_user
    return escalation_entrance_blocked_user()


async def handle_escalate_missing_proof(phone: str, args: Dict[str, Any]) -> str:
    from app.services.escalation import escalate_missing_proof
    details = args.get("details", "")
    await escalate_missing_proof(phone, details)
    from app.message_templates.templates import escalation_missing_proof_user
    return escalation_missing_proof_user()


async def handle_list_available_tickets(db: AsyncSession, args: Dict[str, Any]) -> str:
    """Fetch available sell offers from the DB and format them as a WhatsApp-friendly list."""
    from app.crud.sell_offers import get_available_offers
    
    event_name = args.get("event_name") or None
    offers = await get_available_offers(db, event_name=event_name, limit=20)
    
    if not offers:
        if event_name:
            return f"Er zijn momenteel geen tickets beschikbaar voor '{event_name}'. Wil je een zoekopdracht plaatsen zodat we je informeren als er tickets beschikbaar komen?"
        return "Er zijn momenteel geen tickets beschikbaar in ons systeem. Wil je een zoekopdracht plaatsen zodat we je informeren als er tickets beschikbaar komen?"
    
    lines = ["🎟️ *Beschikbare tickets:*\n"]
    for i, offer in enumerate(offers, 1):
        line = f"{i}. *{offer.event_name}*"
        if offer.ticket_type:
            line += f" ({offer.ticket_type})"
        line += f"\n   📦 {offer.quantity}x beschikbaar"
        line += f" · €{offer.price_per_ticket:.2f} per ticket"
        if offer.event_date:
            line += f"\n   📅 {offer.event_date.strftime('%d-%m-%Y')}"
        lines.append(line)
    
    lines.append("\n💡 Wil je tickets kopen? Geef het evenement, aantal en je maximale prijs door!")
    return "\n".join(lines)


async def handle_submit_buy_request(db: AsyncSession, phone: str, args: Dict[str, Any]) -> str:
    from app.crud.buy_requests import create_buy_request
    from app.schemas.buy_request import BuyRequestCreate
    from app.services.matching import auto_match_and_notify
    from app.services.broadcast import broadcast_buy_request

    # Insert into database
    req_schema = BuyRequestCreate(
        event_name=args["event_name"],
        quantity=args["quantity"],
        max_price_per_ticket=Decimal(str(args["max_price"])),
        phone=phone
    )
    result = await create_buy_request(db, req_schema)

    # Auto-match logic
    try:
        match_result = await auto_match_and_notify(
            db,
            buy_request_id=result.id,
            event_name=req_schema.event_name,
            quantity=req_schema.quantity,
            max_price=req_schema.max_price_per_ticket,
            buyer_phone=phone,
        )
        
        if match_result:
            return f"Je zoekopdracht is opgeslagen. Goed nieuws! Er zijn tickets beschikbaar. Betaal de aanbetaling van €{match_result['deposit_amount']:.2f} via deze link: {match_result['checkout_url']}"
    except Exception as e:
        logger.error(f"Auto match failed in AI router: {e}")
        
    # Broadcast if no match
    try:
        await broadcast_buy_request(
            event_name=req_schema.event_name,
            event_date="N/A",  # Not strictly capturing date in AI router yet
            quantity=req_schema.quantity,
            requester_phone=phone,
        )
    except Exception as e:
        logger.error(f"Search broadcast failed in AI router: {e}")

    return "✅ Je zoekopdracht is opgeslagen! We hebben je vraag doorgezet naar ons netwerk. We laten je weten zodra er tickets beschikbaar zijn."


async def handle_submit_sell_offer(db: AsyncSession, phone: str, args: Dict[str, Any]) -> str:
    from app.crud.sell_offers import create_sell_offer
    from app.schemas.sell_offer import SellOfferCreate
    from app.services.stripe_service import create_payment_link
    from app.services.broadcast import broadcast_new_listing
    from app.services.matching import process_waitlist

    price = Decimal(str(args["price_per_ticket"]))
    quantity = args["quantity"]
    total_price = price * quantity
    deposit_amount = total_price * Decimal("0.075")

    # Insert into DB
    offer_schema = SellOfferCreate(
        event_name=args["event_name"],
        quantity=quantity,
        price_per_ticket=price,
        phone=phone
    )
    new_offer = await create_sell_offer(db, offer_schema)

    # Process waitlist matching
    try:
        await process_waitlist(db, new_offer)
    except Exception as e:
        logger.error(f"Waitlist processing failed in AI router: {e}")

    # Broadcast new listing
    try:
        await broadcast_new_listing(
            event_name=offer_schema.event_name,
            quantity=offer_schema.quantity,
            price_per_ticket=price,
            seller_phone=phone,
        )
    except Exception as e:
        logger.error(f"Broadcast failed in AI router: {e}")

    # Generate Stripe Link for seller verification (if applicable in your flow)
    # Using generic success response for POC parity
    return "✅ Je aanbod is opgeslagen! We hebben het in ons netwerk geplaatst. Verkopers betalen via een betaallink, wij informeren je zodra er interesse is."


# ---------------------------------------------------------
# MAIN EXPORTED FUNCTION
# ---------------------------------------------------------

async def process_message(db: AsyncSession, session: ChatSession, phone: str, raw_message: str) -> str:
    """Entry point for the AI Router. Processes messages, maintains context, and calls tools."""
    
    # Hard reset handle
    if raw_message.strip().lower() in ["stop", "reset", "cancel", "annuleer", "wissen", "start opnieuw"]:
        session.message_history = []
        await db.commit()
        return "Je eerdere antwoorden zijn gewist! Wil je tickets kopen of verkopen?"

    # Initialize or load history
    if not isinstance(session.message_history, list):
        session.message_history = []
        
    messages = session.message_history
    
    # Inject system prompt if entirely new conversation
    if not messages:
        from datetime import date
        today_str = date.today().strftime("%d-%m-%Y")
        dynamic_prompt = f"{SYSTEM_PROMPT}\n\nBelangrijk: De datum van vandaag is {today_str}."
        messages.append({"role": "system", "content": dynamic_prompt})

    # Append new user message
    messages.append({"role": "user", "content": raw_message})
    
    # Keep history within reasonable bounds to save tokens (e.g. last 15 messages)
    if len(messages) > 15:
        # keep system prompt (0) + last 14
        messages = [messages[0]] + messages[-14:]

    try:
        # 1. Call OpenAI
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.7
        )
        
        response_msg = response.choices[0].message
        
        # Scenario A: AI decides to call a backend tool
        if response_msg.tool_calls:
            # Append AI's intent to call the tool to history
            messages.append(response_msg.model_dump(exclude_none=True))
            
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                logger.info(f"AI Router triggered tool: {func_name} with args {arguments} for [{phone}]")
                
                if func_name == "submit_buy_request":
                    func_result_str = await handle_submit_buy_request(db, phone, arguments)
                elif func_name == "submit_sell_offer":
                    func_result_str = await handle_submit_sell_offer(db, phone, arguments)
                elif func_name == "escalate_entrance_issue":
                    func_result_str = await handle_escalate_entrance(phone, arguments)
                elif func_name == "escalate_missing_proof":
                    func_result_str = await handle_escalate_missing_proof(phone, arguments)
                elif func_name == "list_available_tickets":
                    func_result_str = await handle_list_available_tickets(db, arguments)
                else:
                    func_result_str = "Error: Onbekende functie"
                
                # Append tool execution result back to AI
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": func_result_str
                })
            
            # Send history back to AI so it can summarize the execution for the user
            final_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )
            
            final_bot_reply = final_response.choices[0].message.content
            messages.append({"role": "assistant", "content": final_bot_reply})
            
            # Save state
            session.message_history = messages
            await db.commit()
            
            return final_bot_reply
            
        # Scenario B: AI just wants to chat (e.g. ask for missing info)
        else:
            bot_reply = response_msg.content
            messages.append({"role": "assistant", "content": bot_reply})
            
            # Save state
            session.message_history = messages
            await db.commit()
            
            return bot_reply
            
    except Exception as e:
        logger.error(f"Error in agent_router.process_message: {e}")
        return "Sorry, er ging iets mis in mijn AI brein. Probeer het opnieuw alsjeblieft."
