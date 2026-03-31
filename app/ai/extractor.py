"""Entity extraction from AI classification responses."""

from typing import Dict, List, Optional
from datetime import datetime


# Required fields per intent
# event_date is optional for BUYERS (they may not know the exact date)
# but REQUIRED for SELLERS (needed to list the ticket properly).
REQUIRED_FIELDS = {
    "BUY_REQUEST": ["event_name", "quantity", "max_price"],
    "SELL_OFFER": ["event_name", "event_date", "quantity", "price_per_ticket"],
}


def validate_entities(intent: str, entities: dict) -> List[str]:
    """Check which required fields are missing for a given intent.

    Args:
        intent: Classified intent
        entities: Extracted entity dict

    Returns:
        List of missing field names
    """
    required = REQUIRED_FIELDS.get(intent, [])
    missing = []

    for field in required:
        value = entities.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)

    return missing


def normalize_entities(entities: dict) -> dict:
    """Normalize extracted entities to standard formats.

    - Dates to YYYY-MM-DD
    - Quantities to int
    - Prices to float
    """
    result = dict(entities)

    # Sanitize event_name: strip newlines, take only first line
    if result.get("event_name") and isinstance(result["event_name"], str):
        first_line = result["event_name"].split("\n")[0].strip()
        if first_line:
            result["event_name"] = first_line
        else:
            result["event_name"] = None

    # Normalize quantity
    if result.get("quantity") is not None:
        try:
            result["quantity"] = int(result["quantity"])
        except (ValueError, TypeError):
            result["quantity"] = None

    # Normalize prices
    for price_field in ["price_per_ticket", "max_price"]:
        if result.get(price_field) is not None:
            try:
                result[price_field] = float(result[price_field])
            except (ValueError, TypeError):
                result[price_field] = None

    # Normalize date
    if result.get("event_date") is not None:
        val = str(result["event_date"]).strip().lower()
        
        # Dutch + English month mapping
        dutch_months = {
            "januari": "01", "februari": "02", "maart": "03", "april": "04",
            "mei": "05", "juni": "06", "juli": "07", "augustus": "08",
            "september": "09", "oktober": "10", "november": "11", "december": "12",
            "jan": "01", "feb": "02", "mrt": "03", "apr": "04", # short forms
            "jun": "06", "jul": "07", "aug": "08", "sep": "09", "okt": "10", "nov": "11", "dec": "12",
            # English month names
            "january": "01", "february": "02", "march": "03",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "october": "10",
        }
        
        # Replace textual months with numbers
        for name, num in dutch_months.items():
            if name in val:
                val = val.replace(name, num)
        
        # Clean up delimiters: 26 08 -> 26-08
        val = val.replace(" ", "-").replace("/", "-")
        
        current_year = datetime.now().year
        
        # Try formats
        parsed_date = None
        for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d-%m"]:
            try:
                dt = datetime.strptime(val, fmt)
                # If parsed as 1900 (no year provided), fix year
                if dt.year == 1900:
                    dt = dt.replace(year=current_year)
                    # Only roll to next year if the date is >3 months in the past.
                    # Events within the last 3 months are likely still relevant
                    # (e.g. selling leftover tickets, resolving disputes).
                    from datetime import timedelta
                    if dt < datetime.now() - timedelta(days=90):
                         dt = dt.replace(year=current_year + 1)
                
                parsed_date = dt
                break
            except ValueError:
                continue
        
        if parsed_date:
            result["event_date"] = parsed_date.strftime("%Y-%m-%d")
        else:
            # removing invalid date string to avoid validation error, 
            # OR keep it allowed? Schema requires Date.
            # If we can't parse it, we should probably set it to None 
            # so the user is asked again? Or accept string?
            # Setting to None will make 'validate_entities' flag it as missing again?
            # But the user just provided it.
            # We strictly need a Date object for DB.
            result["event_date"] = None
            
    return result


def merge_collected_data(existing: dict, new_entities: dict) -> dict:
    """Merge newly extracted entities into already-collected data.

    Only updates fields that are None or missing in existing data.
    """
    merged = dict(existing)
    for key, value in new_entities.items():
        if value is not None and (key not in merged or merged[key] is None):
            merged[key] = value
    return merged
