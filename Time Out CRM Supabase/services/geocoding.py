
# Time Out Lawncare CRM
# Geocoding Services

# Version 2.0


from __future__ import annotations

import os
import time
import logging
from math import radians, sin, cos, sqrt, atan2
from typing import Dict, Optional

import pandas as pd
import requests
import streamlit as st

from geopy.exc import (
    GeocoderTimedOut,
    GeocoderUnavailable,
    GeocoderServiceError,
)

from geopy.geocoders import Nominatim

from data.database import (
    dataframe,
    execute,
    get_customers,
    update_customer_coordinates,
)

# --------------------------------------------------------
# LOGGING
# --------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

USER_AGENT = "TimeOutLawncareCRM"

NOMINATIM = Nominatim(
    user_agent=USER_AGENT,
    timeout=10,
)

HTTP = requests.Session()

MAX_RETRIES = 3

RETRY_DELAY = 1.5

# --------------------------------------------------------
# CACHE TABLE
# --------------------------------------------------------

execute(
    """
    CREATE TABLE IF NOT EXISTS geocode_cache
    (
        address TEXT PRIMARY KEY,

        lat REAL,

        lng REAL,

        formatted_address TEXT,

        provider TEXT,

        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
)

# --------------------------------------------------------
# ADDRESS NORMALIZATION
# --------------------------------------------------------

def normalize_address(address: str) -> str:

    if address is None:
        return ""

    address = address.upper().strip()

    replacements = {

        ".": "",

        ",": "",

        " ROAD": " RD",

        " STREET": " ST",

        " AVENUE": " AVE",

        " DRIVE": " DR",

        " BOULEVARD": " BLVD",

        " LANE": " LN",

        " HIGHWAY": " HWY",

        " CIRCLE": " CIR",

        " COURT": " CT",

        " PLACE": " PL",

        " PARKWAY": " PKWY",

    }

    for old, new in replacements.items():

        address = address.replace(old, new)

    return " ".join(address.split())

# --------------------------------------------------------
# CACHE
# --------------------------------------------------------

def cache_lookup(address: str) -> Optional[Dict]:

    df = dataframe(
        """
        SELECT *

        FROM geocode_cache

        WHERE address=?
        """,
        (normalize_address(address),),
    )

    if df.empty:
        return None

    row = df.iloc[0]

    return {

        "lat": row["lat"],

        "lng": row["lng"],

        "address": row["formatted_address"],

        "provider": row["provider"],

    }


def cache_save(
    address: str,
    lat: float,
    lng: float,
    formatted_address: str,
    provider: str,
):

    execute(
        """
        INSERT INTO geocode_cache
        (
            address,
            lat,
            lng,
            formatted_address,
            provider
        )

        VALUES
        (
            ?,?,?,?,?
        )

        ON CONFLICT(address)

        DO UPDATE

        SET

            lat=excluded.lat,

            lng=excluded.lng,

            formatted_address=excluded.formatted_address,

            provider=excluded.provider
        """,
        (
            normalize_address(address),
            lat,
            lng,
            formatted_address,
            provider,
        ),
    )

# --------------------------------------------------------
# VALIDATION
# --------------------------------------------------------

def valid_coordinates(
    lat: float | None,
    lng: float | None,
) -> bool:

    if lat is None:
        return False

    if lng is None:
        return False

    return (
        -90 <= lat <= 90
        and
        -180 <= lng <= 180
    )

# --------------------------------------------------------
# GOOGLE GEOCODING
# --------------------------------------------------------

def google_geocode(
    address: str,
) -> Optional[Dict]:

    if not GOOGLE_API_KEY:
        return None

    params = {

        "address": address,

        "key": GOOGLE_API_KEY,

    }

    for attempt in range(MAX_RETRIES):

        try:

            response = HTTP.get(
                GOOGLE_URL,
                params=params,
                timeout=10,
            )

            response.raise_for_status()

            payload = response.json()

            if payload["status"] != "OK":

                logger.warning(
                    "Google returned %s",
                    payload["status"],
                )

                return None

            result = payload["results"][0]

            location = result["geometry"]["location"]

            return {

                "lat": location["lat"],

                "lng": location["lng"],

                "address": result["formatted_address"],

                "provider": "Google",

            }

        except Exception as ex:

            logger.warning(ex)

            if attempt == MAX_RETRIES - 1:
                return None

            time.sleep(RETRY_DELAY)

    return None

# --------------------------------------------------------
# NOMINATIM FALLBACK
# --------------------------------------------------------

def nominatim_geocode(
    address: str,
) -> Optional[Dict]:

    for attempt in range(MAX_RETRIES):

        try:

            location = NOMINATIM.geocode(address)

            if location is None:

                return None

            return {

                "lat": location.latitude,

                "lng": location.longitude,

                "address": location.address,

                "provider": "Nominatim",

            }

        except (
            GeocoderTimedOut,
            GeocoderUnavailable,
            GeocoderServiceError,
        ):

            if attempt == MAX_RETRIES - 1:
                return None

            time.sleep(RETRY_DELAY)

        except Exception:

            return None

    return None

# --------------------------------------------------------
# MASTER GEOCODER
# --------------------------------------------------------

def geocode_address(
    address: str,
    force_refresh: bool = False,
) -> Optional[Dict]:

    if not address:
        return None

    if not force_refresh:

        cached = cache_lookup(address)

        if cached:

            return cached

    result = google_geocode(address)

    if result is None:

        logger.info("Google failed, using Nominatim...")

        result = nominatim_geocode(address)

    if result is None:

        return None

    cache_save(
        address,
        result["lat"],
        result["lng"],
        result["address"],
        result["provider"],
    )

    return result
    
# --------------------------------------------------------
# BATCH GEOCODING
# --------------------------------------------------------

def geocode_customers(
    update_existing: bool = False,
) -> pd.DataFrame:
    """
    Geocodes every customer.

    Parameters
    ----------
    update_existing
        False = only customers missing coordinates.
        True = re-geocode every customer.
    """

    customers = get_customers()

    if customers.empty:
        return customers

    total = len(customers)

    updated = 0

    for _, customer in customers.iterrows():

        lat = customer.get("lat")
        lng = customer.get("lng")

        if (
            not update_existing
            and valid_coordinates(lat, lng)
        ):
            continue

        result = geocode_address(customer["address"])

        if result is None:
            continue

        update_customer_coordinates(
            customer["id"],
            result["lat"],
            result["lng"],
        )

        updated += 1

        #
        # Be nice to Nominatim if we fall back.
        #
        if result["provider"] == "Nominatim":
            time.sleep(1)

    logger.info(
        "Updated %s of %s customers",
        updated,
        total,
    )

    return get_customers()


# --------------------------------------------------------
# MISSING COORDINATES
# --------------------------------------------------------

def customers_missing_coordinates() -> pd.DataFrame:

    customers = get_customers()

    if customers.empty:
        return customers

    return customers[
        customers["lat"].isna()
        |
        customers["lng"].isna()
    ].copy()


# --------------------------------------------------------
# DISTANCE (HAVERSINE)
# --------------------------------------------------------

def distance_between(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
) -> float:
    """
    Great-circle distance in miles.
    Accepts numeric values or numeric strings.
    """
    lat1 = float(lat1)
    lng1 = float(lng1)
    lat2 = float(lat2)
    lng2 = float(lng2)

    earth_radius = 3958.756

    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlng / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )

    return earth_radius * c


# --------------------------------------------------------
# NEAREST CUSTOMER
# --------------------------------------------------------

def nearest_customer(
    latitude: float,
    longitude: float,
) -> Optional[Dict]:

    customers = get_customers()

    if customers.empty:
        return None

    winner = None

    winner_distance = None

    for _, customer in customers.iterrows():

        lat = customer["lat"]
        lng = customer["lng"]

        if not valid_coordinates(lat, lng):
            continue

        miles = distance_between(
            latitude,
            longitude,
            lat,
            lng,
        )

        if (
            winner_distance is None
            or
            miles < winner_distance
        ):
            winner_distance = miles
            winner = customer.to_dict()

    if winner is None:
        return None

    winner["distance"] = round(
        winner_distance,
        2,
    )

    return winner


# --------------------------------------------------------
# CACHE UTILITIES
# --------------------------------------------------------

def cache_size() -> int:

    df = dataframe(
        """
        SELECT COUNT(*) AS total

        FROM geocode_cache
        """
    )

    return int(df.iloc[0]["total"])


def cache_contents() -> pd.DataFrame:

    return dataframe(
        """
        SELECT *

        FROM geocode_cache

        ORDER BY created DESC
        """
    )


def clear_cache():

    execute(
        """
        DELETE

        FROM geocode_cache
        """
    )


def remove_cached_address(
    address: str,
):

    execute(
        """
        DELETE

        FROM geocode_cache

        WHERE address=?
        """,
        (
            normalize_address(address),
        ),
    )


# --------------------------------------------------------
# CACHE REBUILD
# --------------------------------------------------------

def rebuild_cache():
    """
    Clears cache then rebuilds it from Google.
    """

    clear_cache()

    geocode_customers(
        update_existing=True,
    )


# --------------------------------------------------------
# PROVIDER TEST
# --------------------------------------------------------

def provider_available() -> Dict[str, bool]:

    return {

        "google": bool(GOOGLE_API_KEY),

        "nominatim": True,

    }


# --------------------------------------------------------
# HEALTH
# --------------------------------------------------------

def geocoder_health() -> Dict:

    customers = get_customers()

    if customers.empty:

        total = 0

        geocoded = 0

    else:

        total = len(customers)

        geocoded = len(
            customers.dropna(
                subset=[
                    "lat",
                    "lng",
                ]
            )
        )

    providers = dataframe(
        """
        SELECT
            provider,
            COUNT(*) total

        FROM geocode_cache

        GROUP BY provider
        """
    )

    provider_counts = {}

    if not providers.empty:

        for _, row in providers.iterrows():

            provider_counts[
                row["provider"]
            ] = int(row["total"])

    return {

        "customers": total,

        "geocoded": geocoded,

        "missing": total - geocoded,

        "cache_entries": cache_size(),

        "providers": provider_counts,

        "google_enabled": bool(GOOGLE_API_KEY),

    }


# --------------------------------------------------------
# PUBLIC STATUS
# --------------------------------------------------------

def geocoder_status() -> str:

    if GOOGLE_API_KEY:
        return "Google Geocoding + Nominatim Fallback"

    return "Nominatim Only"


# --------------------------------------------------------
# SELF TEST
# --------------------------------------------------------

if __name__ == "__main__":

    print()

    print("Geocoder Status")

    print("----------------")

    print(geocoder_status())

    print()

    print(provider_available())

    print()

    print(geocoder_health())