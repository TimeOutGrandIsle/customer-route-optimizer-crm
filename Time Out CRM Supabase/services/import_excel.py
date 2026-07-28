import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

from services.geocoding import geocode_address


# =========================
# EXPECTED COLUMNS
# =========================
REQUIRED_COLUMNS = ["name", "address"]
OPTIONAL_COLUMNS = ["service", "last_service", "notes"]


# =========================
# CLEANING
# =========================
def clean_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def normalize_row(row: Dict) -> Dict:
    return {
        "name": clean_value(row.get("name")),
        "address": clean_value(row.get("address")),
        "service": clean_value(row.get("service")),
        "last_service": clean_value(row.get("last_service")),
        "notes": clean_value(row.get("notes")),
    }


# =========================
# VALIDATION
# =========================
def validate_row(row: Dict) -> bool:
    return bool(row.get("name")) and bool(row.get("address"))


# =========================
# GEOCODE + ENRICH
# =========================
def enrich_row(row: Dict, auto_geocode: bool = True) -> Dict:
    if auto_geocode and (not row.get("lat") or not row.get("lng")):
        geo = geocode_address(row["address"])
        if geo:
            row["lat"] = geo["lat"]
            row["lng"] = geo["lng"]
            row["geocode_source"] = geo["source"]

    row["imported_at"] = datetime.now().isoformat()
    return row


# =========================
# IMPORT EXCEL
# =========================
def import_excel(filepath: str, auto_geocode: bool = True) -> List[Dict]:
    """
    Returns list of customer dicts ready for DB insert or session state.
    """
    df = pd.read_excel(filepath)

    # normalize columns
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    customers: List[Dict] = []

    for _, row in df.iterrows():
        data = normalize_row(row.to_dict())

        if not validate_row(data):
            continue

        data = enrich_row(data, auto_geocode=auto_geocode)
        customers.append(data)

    return customers


# =========================
# EXPORT TEMPLATE
# =========================
def generate_template(filepath: str):
    """
    Creates an Excel template users can download.
    """
    df = pd.DataFrame([
        {
            "name": "",
            "address": "",
            "service": "",
            "last_service": "",
            "notes": ""
        }
    ])

    df.to_excel(filepath, index=False)


# =========================
# BULK IMPORT HELPERS
# =========================
def import_and_prepare_for_db(filepath: str) -> List[Dict]:
    """
    Alias for DB-ready import.
    """
    return import_excel(filepath, auto_geocode=True)