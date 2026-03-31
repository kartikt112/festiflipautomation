"""Versioned AI prompts for classification and extraction."""

PROMPT_VERSION = "v1.0"

CLASSIFICATION_PROMPT = """Je bent een WhatsApp ticket-assistent voor FestiFlip.
Analyseer het volgende Nederlandse bericht.
Geef alleen JSON terug.

Datum vandaag: {today}

Belangrijke regels:
1. Interpretatie van 'beschikbaar':
   - "Zijn er tickets beschikbaar?" = BUY_REQUEST
   - "Ik heb tickets beschikbaar" = SELL_OFFER
2. KOPEN vs VERKOPEN – DIT IS HEEL BELANGRIJK:
   - Als de gebruiker het woord 'verkopen', 'verkoop', 'te koop', of 'aanbieden' gebruikt → ALTIJD SELL_OFFER, NOOIT BUY_REQUEST
   - UITZONDERING: DOORGESTUURDE BERICHTEN. Als het bericht begint met "[Doorgestuurd]" of "[Forwarded]", dan is het een doorgestuurd ticket-aanbod van iemand anders. De gebruiker wil deze tickets KOPEN, dus de intent is BUY_REQUEST.
     - Herken ook berichten die eruitzien als een gestructureerde listing (met emoji's, prijs, aantal, en "Bericht FestiFlip als je geïnteresseerd bent") als doorgestuurde berichten → BUY_REQUEST.
     - Bij doorgestuurde berichten: gebruik price_per_ticket als max_price voor de koper.
     - BELANGRIJK: Bij het extraheren van event_name uit doorgestuurde listings, negeer ALTIJD headers zoals "*TE KOOP 🎟️*", "🎟️ GEZOCHT", etc. De echte evenement naam staat NA de header, meestal op de regel met 🎟️ gevolgd door de naam en datum. Voorbeeld: uit "*TE KOOP 🎟️*\n🎟️ thuishaven lammers (2026-06-07)" is de event_name "thuishaven lammers", NIET "*TE KOOP 🎟️*".
   - Als de gebruiker zegt 'ik heb tickets om te verkopen' → SELL_OFFER
   - Als de gebruiker zegt 'ik wil kopen' of 'ik zoek tickets' → BUY_REQUEST
   - Voorbeelden:
     - "Ik heb ook wat tickets om te verkopen" → SELL_OFFER
     - "Ik wil tickets verkopen" → SELL_OFFER
     - "Ik heb 5 kaarten te koop" → SELL_OFFER
     - "Ik zoek tickets voor Lowlands" → BUY_REQUEST
     - "Zijn er nog kaarten beschikbaar?" → BUY_REQUEST
     - "[Doorgestuurd] *TE KOOP 🎟️* thuishaven lammers (2026-06-07) 4 Stuks €80.0 per stuk" → BUY_REQUEST (doorgestuurd aanbod)
3. Prijs extractie:
   - Negeer jaartallen (bv. 2024, 2025) als prijs!
   - Alleen getallen met €, euro, of expliciete context ("prijs is 50") zijn prijzen.
   - Als geen prijs genoemd wordt, zet null.
4. Datum extractie:
   - Gebruik ALTIJD het huidige jaar ({today_year}) of het volgende jaar als de datum al verstreken is.
   - "zaterdag 28 februari" → {today_year}-02-28 (NIET 2024-02-28)
   - "volgende week vrijdag" → bereken de juiste datum op basis van vandaag ({today})
   - Als er geen jaar wordt genoemd, gebruik dan {today_year}.
   - ALS DE GEBRUIKER HELEMAAL GEEN DATUM NOEMT, zet dan null. Vul NOOIT standaard de datum van vandaag in.
5. ESCALATIE vs VRAAG – DIT IS HEEL BELANGRIJK:
   - ENTRANCE_BLOCKED en MISSING_PROOF zijn ALLEEN voor actieve, huidige problemen.
   - Als het bericht een HYPOTHETISCHE vraag is ("Wat als...", "Hoe werkt...", "Stel dat...", "Wat gebeurt er als...", "Wat doe ik als..."), dan is de intent ALTIJD GENERAL_QUESTION.
   - Voorbeelden:
     - "Wat als de verkoper me de tickets niet stuurt?" → GENERAL_QUESTION (hypothetisch)
     - "De verkoper stuurt me de tickets niet!" → MISSING_PROOF (actief probleem)
     - "Wat doe ik als mijn ticket niet werkt bij de ingang?" → GENERAL_QUESTION (hypothetisch)
     - "Ik sta bij de ingang en mijn ticket werkt niet" → ENTRANCE_BLOCKED (actief probleem)
6. Aantallen en Prijzen:
   - quantity MOET een positief geheel getal zijn (groter dan 0). Als de gebruiker een negatief aantal noemt (bijv. -5) of 0 tickets verkoopt, zet quantity op null.
   - BELANGRIJK: Als de gebruiker "een kaartje", "een ticket", of "een kaart" zegt, is "een" waarschijnlijk het LIDWOORD (artikel "a/an"), NIET het getal 1. Zet quantity dan op null zodat we het expliciet kunnen vragen. Alleen als de gebruiker expliciet "1 ticket", "één ticket", of een ander specifiek getal noemt, vul dan quantity in.
   - price_per_ticket en max_price MOETEN positieve getallen zijn (groter dan 0). Als de gebruiker 0 noemt (bijv. "gratis", "0 euro"), zet de prijs op null, behalve als ze écht aangeven nul te willen betalen. Om problemen te voorkomen, laat de AI de prijs parsen maar dwing positieve getallen af.
7. Prijs patronen:
   - "80 per stuk" of "80 per ticket" = prijs (80)
   - "80,-" = prijs (80)
   - "min. 50eur" of "50eur" = prijs (50)
   - "wil er max 50 euro per stuk voor betalen" = max_price (50)
8. Multi-line input zonder labels:
   - Als de gebruiker meerdere regels stuurt zonder labels (bijv. "thuishaven\n7 juni\n4\n80"),
     herken dan: tekstregels = evenement, datumregels = datum, kleine getallen = aantal, grote getallen = prijs.
9. Template-style input:
   - Als de gebruiker "evenement: X" of "evenement, X" of "evenement is X" stuurt,
     extraheer X als event_name. Negeer het woord "evenement" zelf als event_name.
10. Event name extractie:
    - Als de gebruiker een Nederlandse zin stuurt die GEEN evenementnaam bevat
      (bijv. "nee maar k ben verkoper he", "want hoe werkt de betaling",
       "echt 5 evenementen kunnen we dit ff snel in een keer regelen"),
      zet event_name op null.
    - Een evenementnaam is een eigennaam (Dekmantel, Lowlands, Thuishaven),
      NIET een Nederlandse conversationele zin.

Velden:
- intent: BUY_REQUEST, SELL_OFFER, BROWSE_CATALOG, STATUS_CHECK, PAYMENT_CONFIRMATION, SUPPORT, ENTRANCE_BLOCKED, MISSING_PROOF, GENERAL_QUESTION, UNKNOWN
  - BUY_REQUEST: user wants to BUY a specific ticket (they mention an event, quantity, or price)
  - BROWSE_CATALOG: user asks to SEE, BROWSE, or LIST available tickets without specifying what they want to buy. Examples: "Welke tickets zijn er?", "Wat hebben jullie?", "Laat me alle tickets zien", "Wat is er beschikbaar?", "Kunt u mij alle beschikbare tickets doorgeven?"
  - ENTRANCE_BLOCKED: buyer is CURRENTLY at the event entrance and can't get in (only for active issues, NOT hypothetical questions)
  - MISSING_PROOF: buyer is CURRENTLY experiencing an issue where the seller won't share proof (only for active issues, NOT hypothetical questions)
  - GENERAL_QUESTION: user asks ANY question about how things work, including hypothetical scenarios ("wat als", "hoe werkt", "stel dat")
- event_name: string of null
- event_date: string (YYYY-MM-DD) of null
- ticket_type: string of null (bijv. "Weekend", "Dagkaart Vrijdag")
- quantity: integer (groter dan 0) of null
- price_per_ticket: number (groter dan 0) of null
- max_price: number (groter dan 0) of null
- missing_fields: lijst van ontbrekende velden
- confidence: float tussen 0 en 1

Bericht:
"{message}"

Geef JSON terug zonder extra tekst of uitleg."""

EXTRACTION_PROMPT = """Extraheer de volgende gegevens uit het Nederlandse bericht.
Geef alleen JSON terug.

Regels:
- Negeer jaartallen (2024, 2025) als prijs.
- Zoek expliciete bedragen (€, euro).

Velden om te zoeken:
- event_name: string
- event_date: string (YYYY-MM-DD)
- quantity: integer (groter dan 0)
- price_per_ticket: number (groter dan 0)
- max_price: number (groter dan 0)
- first_name: string
- last_name: string

Bericht:
"{message}"

Geef JSON terug met gevonden waarden. Gebruik null voor niet-gevonden velden."""

VERIFICATION_PROMPT = """
Analyze the following search results for an event named "{event_name}".

Search Results:
{search_results}

Determine:
1. Is this a real, upcoming or recent event? (is_real)
2. What are the official ticket types? (e.g. Weekend, Day, Camping)
3. Is there ambiguity? (e.g. User said "Lowlands" but didn't specify Weekend or Day)

Return ONLY JSON:
{{
  "is_real": true/false,
  "official_name": "Full Event Name",
  "ticket_types": ["Weekend", "Friday", "Saturday", "Sunday"],
  "ambiguous": true/false,
  "reasoning": "Explanation"
}}
"""
