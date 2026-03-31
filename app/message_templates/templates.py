"""Dutch WhatsApp message templates – all messages sent to buyers and sellers."""

from decimal import Decimal


def format_date(date_str: str) -> str:
    """Format a date string to DD/MM/YY for user display.

    Accepts YYYY-MM-DD, DD-MM-YYYY, or already formatted strings.
    Returns the original string if parsing fails.
    """
    if not date_str:
        return date_str
    try:
        from datetime import datetime
        # Try YYYY-MM-DD first (internal format)
        if len(date_str) == 10 and date_str[4] == "-":
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%d/%m/%y")
        # Try DD-MM-YYYY
        if len(date_str) == 10 and date_str[2] == "-":
            dt = datetime.strptime(date_str, "%d-%m-%Y")
            return dt.strftime("%d/%m/%y")
    except (ValueError, IndexError):
        pass
    return date_str


def availability_message(available_count: int) -> str:
    return f"Nog {available_count} stuk(s) beschikbaar."


def deposit_payment_message(
    deposit_amount: Decimal, remaining_amount: Decimal, stripe_link: str
) -> str:
    return (
        f"🙏 Betaal €{deposit_amount:.2f} voor \"Ticket aanbetaling\" via {stripe_link}\n\n"
        f"Overige €{remaining_amount:.2f} betaal je direct aan de verkoper."
    )


def payment_received_message(seller_name: str, seller_phone: str) -> str:
    steps = (
        "De stappen zijn als volgt:\n"
        "1. Je ontvangt het telefoonnummer van de verkoper.\n"
        "2. Stuur altijd direct een berichtje naar de verkoper.\n"
        "3. Geef aan welke tickets je hebt gekocht en hoeveel stuks.\n"
        "4. De verkoper stuurt jou een betaalverzoek van het bedrag exclusief onze servicekosten.\n"
        "5. Laat de verkoper de tickets op naam zetten (indien mogelijk).\n"
        "6. Ontvang de tickets."
    )
    return (
        "Betaling ontvangen ✅\n\n"
        "Hier zijn de contactgegevens van de verkoper:\n"
        f"Naam: {seller_name}\n"
        f"Telefoon: {seller_phone}\n\n"
        f"{steps}"
    )


def reservation_expired_message() -> str:
    return (
        "⏰ Je reservering is verlopen omdat de betaling niet op tijd is ontvangen.\n"
        "Het ticket is weer beschikbaar voor anderen.\n"
        "Neem contact met ons op als je alsnog wilt kopen."
    )


def seller_confirmation_message(
    price_per_ticket: float = 0, quantity: int = 1
) -> str:
    """Immediate confirmation after seller saves offer. Steps only, NO calculation."""
    lines = [
        "De stappen zijn als volgt voor jou als verkoper:\n",
        "1. Wij sturen de aanbetaling naar de koper (7,5% met een minimum van €5 per ticket).",
        "2. Zodra deze is betaald, ontvangt de koper jouw nummer en stuurt diegene jou een appje.",
        "3. Daarna kan jij de koper een betaalverzoek sturen van jouw deel. (Verkoopprijs - 7,5%/€5 per ticket)",
        "4. Leg even aan de koper uit of je gelijk het ticket kan opsturen, of dat je het ticket op naam zet en handmatig naar diegene stuurt wanneer ze zijn te downloaden.",
        "5. Laat de koper altijd eerst betalen, voordat je het ticket op naam zet of doorstuurt.",
    ]
    return "\n".join(lines)


def seller_buyer_found_message(
    event_name: str,
    price_per_ticket: float,
    quantity: int,
) -> str:
    """Message sent to seller AFTER a buyer has paid the deposit. Includes calculation."""
    from decimal import Decimal, ROUND_HALF_UP

    lines = [
        f"Goed nieuws! We hebben een koper gevonden voor je tickets *{event_name}*. 🎉\n",
        "De koper heeft jouw nummer ontvangen en stuurt jou een appje. "
        "Jij kan de koper een betaalverzoek sturen van jouw deel. (Verkoopprijs - 7,5% / €5 per ticket).\n",
        "- Leg even aan de koper uit of je gelijk het ticket kan opsturen, of dat je het ticket op naam zet en handmatig naar diegene stuurt wanneer ze zijn te downloaden.",
        "- Laat de koper altijd eerst betalen, voordat je het ticket op naam zet of doorstuurt.",
    ]

    # Calculate the seller payout
    try:
        _price_valid = price_per_ticket and float(price_per_ticket) > 0
        _qty_valid = quantity and int(quantity) > 0
    except (ValueError, TypeError):
        _price_valid = False
        _qty_valid = False

    if _price_valid and _qty_valid:
        try:
            price = Decimal(str(price_per_ticket))
            qty = int(quantity)
            total = price * qty

            # FestiFlip share: 7.5% with minimum €5 per ticket
            share_pct = (total * Decimal("0.075")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            share_min = Decimal("5") * qty
            festiflip_share = max(share_pct, share_min)

            seller_payout = total - festiflip_share

            if seller_payout < 0:
                lines.append(
                    f"\n⚠️ Let op: de ticketprijs (€{price:.2f}) is lager dan onze "
                    f"minimale commissie (€5 per ticket). Neem contact op met ons team."
                )
            else:
                lines.append(
                    f"\n💰 *Berekening:*\n"
                    f"Totaal: {qty}x €{price:.2f} = €{total:.2f}\n"
                    f"FestiFlip commissie (7,5%, min €5/ticket): -€{festiflip_share:.2f}\n"
                    f"───────────────────\n"
                    f"Jij kan de koper een betaalverzoek van *€{seller_payout:.2f}* sturen."
                )
        except Exception:
            pass

    lines.append(
        "\n─────────────────\n"
        "🎟️ Heb je nog meer tickets te verkopen? Typ *ja* voor een nieuw formulier."
    )
    return "\n".join(lines)


# FestiFlip contact number — always use this in group broadcasts instead of user's number
FESTIFLIP_CONTACT = "+31 6 12899608"


def event_sale_broadcast(
    event_name: str,
    event_date: str,
    quantity: int,
    price: Decimal,
    section: str = "",
    seat_info: str = "",
) -> str:
    """Public listing – NO exact seat numbers shown (compliance rule)."""
    lines = [
        f"🎟️ {event_name} ({format_date(event_date)})",
        f"{quantity} Stuks ({seat_info})" if seat_info else f"{quantity} Stuks",
        f"💰 €{price:.2f} per stuk",
    ]
    if section:
        lines.append(f"🪑 {section}")
    lines.append(f"📥 Bericht FestiFlip {FESTIFLIP_CONTACT} als je geïnteresseerd bent!")
    return "\n".join(lines)


def searching_broadcast(
    event_name: str, event_date: str, quantity: int
) -> str:
    """Group broadcast for buy requests — uses OP ZOEK template.
    NEVER includes the buyer's phone number.
    """
    date_str = f"({format_date(event_date)})" if event_date else ""
    return (
        f"*OP ZOEK🚨*\n\n"
        f"🎟️ {event_name} {date_str}\n"
        f"🔢 {quantity} Stuks\n"
        f"📥 Bericht FestiFlip {FESTIFLIP_CONTACT} als je deze tickets hebt en wilt verkopen!"
    )


def buy_request_group_broadcast(
    event_name: str,
    event_date: str,
    quantity: int,
    max_price: str = "N/A",
) -> str:
    """Group notification for new buy requests.
    NEVER includes the buyer's phone number — always shows FestiFlip contact.
    """
    date_str = f"({format_date(event_date)})" if event_date else ""
    return (
        f"*🚨 OP ZOEK 🚨*\n\n"
        f"🎟️ {event_name} {date_str}\n"
        f"🔢 {quantity} Stuks\n"
        f"💰 Max prijs: €{max_price}\n"
        f"📥 Bericht FestiFlip {FESTIFLIP_CONTACT} als je deze tickets hebt en wilt verkopen!"
    )


def sell_offer_group_broadcast(
    event_name: str,
    event_date: str,
    quantity: int,
    price_per_ticket: str = "N/A",
) -> str:
    """Group notification for new sell offers.
    NEVER includes the seller's phone number — always shows FestiFlip contact.
    """
    date_str = f"({format_date(event_date)})" if event_date else ""
    return (
        f"*TE KOOP 🎟️*\n\n"
        f"🎟️ {event_name} {date_str}\n"
        f"🔢 {quantity} Stuks\n"
        f"💰 €{price_per_ticket} per stuk\n"
        f"📥 Bericht FestiFlip {FESTIFLIP_CONTACT} als je geïnteresseerd bent!"
    )


def ask_missing_field(field_name: str, intent: str = "BUY_REQUEST", lang: str = "nl") -> str:
    """Generate follow-up question for missing data fields."""
    if lang == "en":
        if intent == "SELL_OFFER":
            questions = {
                "event_name": "Which event is it for?",
                "event_date": "When is the event?",
                "quantity": "How many tickets do you have?",
                "max_price": "What price per ticket?",
                "price_per_ticket": "What price per ticket?",
                "first_name": "What's your first name?",
                "last_name": "And your last name?",
                "phone": "What number can the buyer reach you on?",
                "proof_reference": "Can you send a screenshot of your tickets?",
            }
        else:
            questions = {
                "event_name": "Which event are you looking for?",
                "event_date": "When is it?",
                "quantity": "How many tickets do you need?",
                "max_price": "What's the max you want to pay per ticket?",
                "price_per_ticket": "How much per ticket?",
                "first_name": "What's your first name?",
                "last_name": "And your last name?",
                "phone": "What number can we reach you on?",
                "proof_reference": "Can you send a screenshot of your tickets?",
            }
        return questions.get(field_name, f"Can you provide the {field_name}?")

    if intent == "SELL_OFFER":
        questions = {
            "event_name": "Welk evenement is het?",
            "event_date": "Wanneer is het?",
            "quantity": "Hoeveel tickets heb je?",
            "max_price": "Wat wil je ervoor vragen per ticket?",
            "price_per_ticket": "Wat wil je ervoor vragen per ticket?",
            "first_name": "Wat is je voornaam?",
            "last_name": "En je achternaam?",
            "phone": "Op welk nummer kan de koper je bereiken?",
            "proof_reference": "Kun je een screenshot sturen van je tickets?",
        }
    else:
        questions = {
            "event_name": "Naar welk evenement zoek je?",
            "event_date": "Wanneer is het?",
            "quantity": "Hoeveel tickets heb je nodig?",
            "max_price": "Wat is het maximale dat je wilt betalen per ticket?",
            "price_per_ticket": "Hoeveel wil je uitgeven per ticket?",
            "first_name": "Wat is je voornaam?",
            "last_name": "En je achternaam?",
            "phone": "Op welk nummer kunnen we je bereiken?",
            "proof_reference": "Kun je een screenshot sturen van je tickets?",
        }
    return questions.get(field_name, f"Kun je de {field_name} doorgeven?")


def welcome_message(lang: str = "nl") -> str:
    if lang == "en":
        return (
            "Hey! 👋 Welcome to FestiFlip.\n\n"
            "Want to buy or sell tickets? "
            "Just tell me what you're looking for or what you have to sell, "
            "and we'll sort it out!"
        )
    return (
        "Hey! 👋 Welkom bij FestiFlip.\n\n"
        "Wil je tickets kopen of verkopen? "
        "Vertel me gewoon wat je zoekt of wat je te koop hebt, "
        "dan regelen we het!"
    )


def broadcast_listing_message(
    event_name: str,
    quantity: int,
    price_per_ticket,
) -> str:
    """Broadcast message sent to subscribers when a seller lists new tickets."""
    return (
        "🎫 *Nieuw aanbod op FestiFlip!*\n\n"
        f"🎟️ Evenement: *{event_name}*\n"
        f"🔢 Aantal: {quantity} ticket(s)\n"
        f"💰 Prijs: €{price_per_ticket:.2f} per stuk\n\n"
        "Interesse? Stuur ons een bericht met:\n"
        f"\"Ik wil tickets kopen voor {event_name}\"\n\n"
        "📲 Wees er snel bij, op = op!"
    )


def waitlist_match_message(
    event_name: str,
    deposit_amount: Decimal,
    checkout_url: str,
) -> str:
    """Notification for buyers on the waitlist when a match is found."""
    return (
        f"🎉 Goed nieuws! Er zijn tickets beschikbaar gekomen voor {event_name}!\n\n"
        "Omdat je hier eerder naar zocht, hebben we ze voor je gereserveerd.\n\n"
        f"💳 Betaal de aanbetaling van €{deposit_amount:.2f} om je tickets definitief te claimen:\n"
        f"{checkout_url}\n\n"
        "⏰ Let op: deze reservering vervalt over 60 minuten als je niet betaalt."
    )


def sell_fill_template(event_name: str = "", event_date: str = "", quantity: str = "", price: str = "", lang: str = "nl") -> str:
    """Fill-in template for sellers to submit all details in one message."""
    if lang == "en":
        return (
            "Send me the following info (can be in one message):\n\n"
            f"Event: {event_name}\n"
            f"Date: {event_date}\n"
            f"Quantity: {quantity}\n"
            f"Price per ticket: €{price}\n\n"
            "Or just type it in your own words, that works too!"
        )
    return (
        "Stuur me even de volgende info (mag in één bericht):\n\n"
        f"Evenement: {event_name}\n"
        f"Datum: {event_date}\n"
        f"Aantal: {quantity}\n"
        f"Prijs per ticket: €{price}\n\n"
        "Of typ het gewoon in je eigen woorden, dat kan ook!"
    )


def buy_fill_template(event_name: str = "", event_date: str = "", quantity: str = "", price: str = "", lang: str = "nl") -> str:
    """Fill-in template for buyers to submit all details in one message."""
    if lang == "en":
        return (
            "Send me the following info (can be in one message):\n\n"
            f"Event: {event_name}\n"
            f"Date: {event_date}\n"
            f"Quantity: {quantity}\n"
            f"Max price per ticket: €{price}\n\n"
            "Or just type it in your own words, that works too!"
        )
    return (
        "Stuur me even de volgende info (mag in één bericht):\n\n"
        f"Evenement: {event_name}\n"
        f"Datum: {event_date}\n"
        f"Aantal: {quantity}\n"
        f"Max prijs per ticket: €{price}\n\n"
        "Of typ het gewoon in je eigen woorden, dat kan ook!"
    )


# ─── Escalation Templates ───


def escalation_entrance_blocked_owner(buyer_phone: str, event_name: str = "") -> str:
    """Message sent to owner when a buyer can't enter the event."""
    event_str = f" voor *{event_name}*" if event_name else ""
    return (
        "🚨 *ESCALATIE – Toegang Geweigerd* 🚨\n\n"
        f"Een koper staat bij de ingang{event_str} maar kan niet naar binnen.\n\n"
        f"📱 Koper telefoon: {buyer_phone}\n\n"
        "Neem zo snel mogelijk contact op met deze koper."
    )


def escalation_entrance_blocked_user() -> str:
    """Reassurance message sent to the buyer who can't enter."""
    return (
        "We hebben je melding ontvangen! 🙏\n\n"
        "Ons team is direct op de hoogte gebracht en neemt zo snel "
        "mogelijk contact met je op om dit op te lossen.\n\n"
        "Houd je telefoon bij de hand. 📱"
    )


def escalation_missing_proof_owner(buyer_phone: str, details: str = "") -> str:
    """Message sent to owner when a buyer reports missing proof from seller."""
    details_str = f"\n📝 Details: {details}" if details else ""
    return (
        "🚨 *ESCALATIE – Ontbrekend Bewijs* 🚨\n\n"
        "Een koper meldt dat de verkoper geen bewijs deelt "
        "(betaalbewijs, eigendomsbewijs, e-mailadres, of andere benodigde gegevens).\n\n"
        f"📱 Koper telefoon: {buyer_phone}"
        f"{details_str}\n\n"
        "Neem zo snel mogelijk contact op om te bemiddelen."
    )


def escalation_missing_proof_user() -> str:
    """Reassurance message sent to the buyer who reported missing proof."""
    return (
        "We hebben je melding ontvangen! 🙏\n\n"
        "Ons team is op de hoogte gebracht en gaat uitzoeken "
        "waarom de verkoper de benodigde informatie niet deelt.\n\n"
        "We nemen zo snel mogelijk contact met je op. 📱"
    )


# ─── Duplicate Offer Detection Templates ───


def duplicate_offer_question(
    existing_event_name: str,
    existing_quantity: int,
    existing_price: float,
) -> str:
    """Ask seller if they want to update an existing listing or add new tickets."""
    return (
        f"⚠️ Je hebt al een actief aanbod voor *{existing_event_name}*:\n"
        f"🔢 {existing_quantity} ticket(s) à €{existing_price:.2f}\n\n"
        "Wil je dit aanbod *bijwerken* met de nieuwe gegevens, "
        "of zijn dit *nieuwe* tickets?\n\n"
        "1️⃣ Typ *bijwerken* om je bestaande aanbod te updaten\n"
        "2️⃣ Typ *nieuw* om een extra aanbod toe te voegen"
    )


# ─── Seller Availability Check Templates ───


def seller_availability_check(
    event_name: str, quantity: int, price_per_ticket: float
) -> str:
    """Ask seller if they still have the ticket (for offers >2h old)."""
    return (
        f"Hoi! 👋\n\n"
        f"Er is een koper geïnteresseerd in jouw tickets:\n\n"
        f"🎟️ {event_name}\n"
        f"🔢 Aantal: {quantity}\n"
        f"💰 Prijs: €{price_per_ticket:.2f} per ticket\n\n"
        f"Heb je deze tickets nog beschikbaar?\n\n"
        f"Typ *ja* om te bevestigen of *nee* als ze niet meer beschikbaar zijn."
    )


def buyer_waiting_for_seller(event_name: str) -> str:
    """Tell the buyer we found a match but are confirming with the seller."""
    return (
        f"🎟️ Goed nieuws! We hebben een verkoper gevonden voor {event_name}!\n\n"
        "We vragen de verkoper of de tickets nog beschikbaar zijn. "
        "Zodra dit bevestigd is, sturen we je direct een betaallink. 💳\n\n"
        "Je hoort zo snel mogelijk van ons! ⏳"
    )
