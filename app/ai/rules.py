"""Rule-based Dutch keyword intent classifier (fast path)."""

import re
from typing import Optional, Tuple

# Intent constants
BUY_REQUEST = "BUY_REQUEST"
SELL_OFFER = "SELL_OFFER"
STATUS_CHECK = "STATUS_CHECK"
PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"
SUPPORT = "SUPPORT"
ENTRANCE_BLOCKED = "ENTRANCE_BLOCKED"
MISSING_PROOF = "MISSING_PROOF"
GENERAL_QUESTION = "GENERAL_QUESTION"
BROWSE_CATALOG = "BROWSE_CATALOG"
UNKNOWN = "UNKNOWN"

# Dutch keyword patterns (case-insensitive)
# Dutch keyword patterns (case-insensitive)
BUY_KEYWORDS = [
    r"\bzoek\b", r"\bnodig\b", r"\bwil kopen\b", r"\bgezocht\b",
    r"\binteresse\b", r"\bkopen\b", r"\bop zoek\b", r"\bzoeken\b",
    r"\bheb je\b", r"\bheeft u\b", r"\bzijn er\b",
    r"\bbeschikbaar\b.*\bkopen\b", r"\btickets?\s+nodig\b",
    r"\bwillen\b.*\btickets?\b", r"\bwie heeft\b",
    # Natural Dutch: "wil ... tickets", "wil graag", etc.
    r"\bwil\b.*\btickets?\b", r"\bwil\b.*\bkaarten?\b",
    r"\bwil graag\b", r"\bgraag\b.*\btickets?\b",
    # Questions implies buying: "zijn er nog kaarten?", "heeft u tickets?"
    r"\bheeft\b.*\btickets?\b", r"\bheeft\b.*\bkaarten?\b",
    r"\bzijn\b.*\btickets?\b", r"\bzijn\b.*\bkaarten?\b",
    r"\bnog\b.*\btickets?\b", r"\bnog\b.*\bkaarten?\b",
    r"\bbeschikbaar\b.*\?",  # "beschikbaar?" implies asking availability (buyer)
]

SELL_KEYWORDS = [
    r"\bverkoop\b", r"\bte koop\b",
    r"\bheb\b.*\btickets?\b", r"\bheb\b.*\bkaarten?\b", r"\bheb\b.*\bkaartjes\b",
    r"\bverkoop ik\b", r"\baanbieden\b", r"\bwil verkopen\b",
    r"\bwil\b.*\bverkopen\b", r"\btickets?\b.*\bverkopen\b",
    r"\bover\b.*\btickets?\b", r"\bkwijt\b", r"\btikkie\b.*\bverkoop\b",
    r"\bkaarten?\b.*\bverkopen\b", r"\bverkopen\b.*\btickets?\b",
    r"\bkaartjes\b.*\bverkopen\b", r"\bverkopen\b.*\bkaartjes\b",
    # Specific 'beschikbaar' patterns
    r"\bheb\b.*\bbeschikbaar\b",
    r"\btickets?\b.*\bbeschikbaar\b",
    r"\bkaarten?\b.*\bbeschikbaar\b",
    r"\d+\s*beschikbaar\b",
]

STATUS_KEYWORDS = [
    r"\bstatus\b", r"\bhoe staat\b", r"\bwaar is\b", r"\bupdate\b",
    r"\bwanneer\b.*\bcontact\b", r"\bhoe lang\b", r"\bwachten\b",
]

PAYMENT_KEYWORDS = [
    r"\bbetaald\b", r"\bbetaling\b", r"\bovergem[a]akt\b", r"\bgeld\b.*\bgestuurd\b",
    r"\btikkie\b", r"\bbunq\b", r"\bstripe\b", r"\bbankoverschrijving\b",
    r"\bheb\b.*\bbetaald\b", r"\bal\b.*\bbetaald\b", r"\bbetaling\b.*\bgedaan\b",
    r"\bheb ik betaald\b", r"\bis betaald\b", r"\baanbetaling\b.*\bbetaald\b",
    r"\baanbetaling\b.*\bgedaan\b", r"\bgeld\b.*\bovergemaakt\b",
]

SUPPORT_KEYWORDS = [
    r"\bprobleem\b", r"\bklacht\b", r"\bfraud[e]?\b", r"\boplichting\b",
    r"\bnep\b", r"\bhelp\b", r"\bterugbetaling\b", r"\brefund\b",
    r"\bdispuut\b", r"\bniet ontvangen\b",
]

ENTRANCE_BLOCKED_KEYWORDS = [
    r"\bingang\b", r"\bniet binnen\b", r"\bkan niet in\b",
    r"\bgeblokkeerd\b", r"\btoegang\b.*\bgeweigerd\b",
    r"\bkomt niet binnen\b", r"\bkan niet naar binnen\b",
    r"\bniet naar binnen\b", r"\btoegang\b", r"\bsecurity\b",
    r"\bgeweigerd\b.*\bingang\b", r"\bsta bij de ingang\b",
    r"\bdeur\b.*\bniet\b", r"\bticket werkt niet\b",
    r"\bqr.*\bwerkt niet\b", r"\bongeldig\b.*\bticket\b",
]

MISSING_PROOF_KEYWORDS = [
    r"\bgeen bewijs\b", r"\bbewijs\b.*\bniet\b",
    r"\bbetaalbewijs\b", r"\bniet gedeeld\b",
    r"\bgeen screenshot\b", r"\bgeen email\b",
    r"\bemail niet\b", r"\beigendomsbewijs\b",
    r"\bproof\b", r"\bniet gestuurd\b.*\bbewijs\b",
    r"\bverkoper deelt niet\b", r"\bverkoper stuurt niet\b",
    r"\bverkoper reageert niet\b", r"\bgeen reactie\b.*\bverkoper\b",
    r"\bgeen informatie\b", r"\binfo niet\b",
    r"\bverkoper\b.*\bbewijs\b", r"\bverkoper\b.*\bniet\b.*\bdeel\b",
    r"\bbewijs.*betaling\b", r"\bontbrekend bewijs\b",
]

GENERAL_QUESTION_KEYWORDS = [
    r"\bhoe werkt\b", r"\bwat is\b", r"\bwaarom\b",
    r"\bwanneer\b", r"\bkan ik\b", r"\bis het veilig\b",
    r"\bhoe veilig\b", r"\bkosten\b", r"\bcommissie\b",
    r"\bservicekosten\b", r"\baanbetaling\b.*\bhoeveel\b",
    r"\bhoe lang duurt\b", r"\bhoe zit het\b",
    r"\bwat als\b", r"\bgarantie\b", r"\bveiligheid\b",
    r"\bhoe doe ik\b", r"\buitleg\b", r"\bleg uit\b",
    r"\bis het\b.*\bveilig\b", r"\bhoe\b.*\bveilig\b",
    r"\bwat kost\b", r"\bhoeveel kost\b",
]

BROWSE_CATALOG_KEYWORDS = [
    r"\balle\b.*\btickets?\b", r"\boverzicht\b", r"\baanbod\b",
    r"\blaat.*zien\b", r"\bwat hebben\b", r"\bwelke tickets\b",
    r"\bbeschikbare tickets\b", r"\balle beschikbare\b",
    r"\bwat is er\b.*\bbeschikbaar\b", r"\bwat\b.*\bbe koop\b",
    r"\bdoorgeven\b.*\btickets?\b", r"\btickets?\b.*\bdoorgeven\b",
]


def _match_keywords(message: str, patterns: list) -> int:
    """Count how many keyword patterns match the message."""
    count = 0
    for pattern in patterns:
        if re.search(pattern, message, re.IGNORECASE):
            count += 1
    return count


def classify_by_rules(message: str) -> Tuple[str, float]:
    """Classify a Dutch WhatsApp message using keyword rules.

    Returns:
        Tuple of (intent, confidence)
        Confidence is based on number of matching keywords
    """
    message = message.strip().lower()

    if not message:
        return UNKNOWN, 0.0

    # Forwarded ticket listings → user wants to BUY, not sell
    if message.startswith("[doorgestuurd]") or message.startswith("[forwarded]"):
        return BUY_REQUEST, 0.9

    scores = {
        BUY_REQUEST: _match_keywords(message, BUY_KEYWORDS),
        SELL_OFFER: _match_keywords(message, SELL_KEYWORDS),
        STATUS_CHECK: _match_keywords(message, STATUS_KEYWORDS),
        PAYMENT_CONFIRMATION: _match_keywords(message, PAYMENT_KEYWORDS),
        SUPPORT: _match_keywords(message, SUPPORT_KEYWORDS),
        ENTRANCE_BLOCKED: _match_keywords(message, ENTRANCE_BLOCKED_KEYWORDS),
        MISSING_PROOF: _match_keywords(message, MISSING_PROOF_KEYWORDS),
        GENERAL_QUESTION: _match_keywords(message, GENERAL_QUESTION_KEYWORDS),
        BROWSE_CATALOG: _match_keywords(message, BROWSE_CATALOG_KEYWORDS),
    }

    # SELL override: if 'verkopen' is explicitly in the message, SELL always wins over BUY
    if re.search(r'\bverkopen\b', message, re.IGNORECASE) and scores[BUY_REQUEST] > 0:
        scores[BUY_REQUEST] = 0  # Suppress BUY when user explicitly says 'verkopen'

    # Find the best match
    best_intent = max(scores, key=scores.get)
    best_score = scores[best_intent]

    if best_score == 0:
        return UNKNOWN, 0.0

    # ── Hypothetical question guard ──
    # If the message contains question indicators AND escalation won,
    # override to GENERAL_QUESTION — hypothetical questions are not escalations.
    QUESTION_INDICATORS = [
        r"\bwat als\b", r"\bwat gebeurt\b", r"\bwat doe\b",
        r"\bhoe werkt\b", r"\bhoe zit\b", r"\bhoe doe\b",
        r"\bis het veilig\b", r"\bhoe veilig\b",
        r"\bkan ik\b", r"\bwat kan\b", r"\bwat moet\b",
        r"\bstel dat\b", r"\bstel je voor\b",
    ]
    if best_intent in (ENTRANCE_BLOCKED, MISSING_PROOF):
        for pattern in QUESTION_INDICATORS:
            if re.search(pattern, message, re.IGNORECASE):
                best_intent = GENERAL_QUESTION
                best_score = max(scores[GENERAL_QUESTION], 1)
                break
    # ─────────────────────────────────

    # Calculate confidence based on matches and whether it's clearly dominant
    total_matches = sum(scores.values())
    if total_matches == 0:
        return UNKNOWN, 0.0

    dominance = best_score / total_matches
    # Scale confidence: 1 match = 0.5, 2+ with dominance = higher
    confidence = min(0.5 + (best_score * 0.15) + (dominance * 0.2), 1.0)

    return best_intent, round(confidence, 2)
