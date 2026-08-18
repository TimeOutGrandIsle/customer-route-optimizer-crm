"""
services/geocoding.py

Geocoding service for Time Out Lawncare CRM.

Compatibility goals:
- Preserve legacy clean_address() and geocode() callers.
- Support newer geocode_address() callers that expect a dictionary.
- Provide bulk geocoding through geocode_customers().
- Use Google Geocoding API.
- Cache successful geocodes when the database cache helpers are available.
- Return clean failure values instead of crashing the Streamlit application.

Coordinate conventions:
- Legacy geocode() returns: (lat, lng)
- geocode_address() returns: {"lat": float, "lng": float, ...}
- Database customer records may store longitude in a column named "lon".
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.parse import quote

import requests


GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0

_TRANSIENT_GOOGLE_STATUSES = {
    "UNKNOWN_ERROR",
    "OVER_QUERY_LIMIT",
}

_TRANSIENT_HTTP_STATUSES = {
    408,
    429,
    500,
    502,
    503,
    504,
}


def clean_address(address: Any) -> str:
    """
    Normalize an address for geocoding.

    The function intentionally performs conservative cleanup only. It does not
    rewrite street names or abbreviations because doing so can make valid
    addresses less accurate.
    """
    if address is None:
        return ""

    text = str(address).strip()
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r",\s*,+", ", ", text)
    text = text.strip(" ,")

    return text


def address_cache_key(address: Any) -> str:
    """Return a stable normalized cache key for an address."""
    return clean_address(address).casefold()


def build_full_address(
    street_address: Any = None,
    city: Any = None,
    state: Any = None,
    zip_code: Any = None,
) -> str:
    """
    Build a geocodable address from separate customer fields.

    Empty components are omitted.
    """
    street = clean_address(street_address)
    city_text = clean_address(city)
    state_text = clean_address(state)
    zip_text = clean_address(zip_code)

    locality_parts = [part for part in (city_text, state_text) if part]
    locality = ", ".join(locality_parts)

    if zip_text:
        locality = f"{locality} {zip_text}".strip()

    pieces = [part for part in (street, locality) if part]
    return ", ".join(pieces)


def _read_streamlit_secret(name: str) -> Optional[str]:
    """
    Read a Streamlit secret without making Streamlit a hard dependency.

    This keeps geocoding usable from scripts, tests, and import utilities.
    """
    try:
        import streamlit as st  # type: ignore

        try:
            value = st.secrets.get(name)
        except Exception:
            value = None

        if value is not None:
            value = str(value).strip()
            if value:
                return value
    except Exception:
        pass

    return None


def get_google_api_key(explicit_key: Optional[str] = None) -> Optional[str]:
    """
    Resolve the Google API key.

    Resolution order:
    1. Explicit argument
    2. Streamlit secret GOOGLE_API_KEY
    3. Environment variable GOOGLE_API_KEY
    4. Environment variable GOOGLE_MAPS_API_KEY
    """
    if explicit_key:
        key = str(explicit_key).strip()
        if key:
            return key

    key = _read_streamlit_secret("GOOGLE_API_KEY")
    if key:
        return key

    for env_name in ("GOOGLE_API_KEY", "GOOGLE_MAPS_API_KEY"):
        value = os.getenv(env_name)
        if value:
            value = value.strip()
            if value:
                return value

    return None


def _cache_lookup(
    address: str,
    database: Any = None,
) -> Optional[tuple[float, float]]:
    """
    Look up an address in the database geocode cache when supported.

    Multiple compatibility surfaces are supported so this module can coexist
    with both the current and refactored database layers.
    """
    if database is None:
        return None

    key = address_cache_key(address)

    # New Database-service style.
    method = getattr(database, "get_cached_geocode", None)
    if callable(method):
        try:
            cached = method(key)
            if cached:
                if isinstance(cached, Mapping):
                    lat = cached.get("lat")
                    lon = cached.get("lon", cached.get("lng"))
                else:
                    lat, lon = cached[0], cached[1]

                if lat is not None and lon is not None:
                    return float(lat), float(lon)
        except Exception:
            pass

    # Compatibility with module-level or alternate cache methods.
    for method_name in (
        "lookup_geocode_cache",
        "get_geocode_cache",
        "load_geocode_cache",
    ):
        method = getattr(database, method_name, None)
        if not callable(method):
            continue

        try:
            cached = method(key)
        except TypeError:
            try:
                cached = method(address)
            except Exception:
                continue
        except Exception:
            continue

        if not cached:
            continue

        try:
            if isinstance(cached, Mapping):
                lat = cached.get("lat")
                lon = cached.get("lon", cached.get("lng"))
            else:
                lat, lon = cached[0], cached[1]

            if lat is not None and lon is not None:
                return float(lat), float(lon)
        except (TypeError, ValueError, IndexError):
            continue

    return None


def _cache_save(
    address: str,
    lat: float,
    lng: float,
    database: Any = None,
    source: str = "google",
) -> None:
    """Save a successful geocode when the database supports caching."""
    if database is None:
        return

    key = address_cache_key(address)

    method = getattr(database, "save_geocode", None)
    if callable(method):
        try:
            method(
                address_key=key,
                original_address=address,
                lat=lat,
                lon=lng,
                source=source,
            )
            return
        except TypeError:
            try:
                method(key, address, lat, lng, source)
                return
            except Exception:
                pass
        except Exception:
            pass

    for method_name in (
        "save_geocode_cache",
        "set_geocode_cache",
        "upsert_geocode_cache",
    ):
        method = getattr(database, method_name, None)
        if not callable(method):
            continue

        attempts = (
            lambda: method(
                address_key=key,
                address=address,
                lat=lat,
                lon=lng,
                source=source,
            ),
            lambda: method(address, lat, lng),
            lambda: method(key, lat, lng),
        )

        for attempt in attempts:
            try:
                attempt()
                return
            except TypeError:
                continue
            except Exception:
                break


def _google_request(
    address: str,
    api_key: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> requests.Response:
    """
    Perform one Google Geocoding API request.

    Params are passed separately so requests handles URL encoding correctly.
    """
    return requests.get(
        GOOGLE_GEOCODING_URL,
        params={
            "address": address,
            "key": api_key,
        },
        timeout=timeout,
    )


def _parse_google_result(
    payload: Mapping[str, Any],
    requested_address: str,
) -> Optional[dict[str, Any]]:
    """Parse the first valid result from a Google Geocoding response."""
    if payload.get("status") != "OK":
        return None

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None

    first = results[0]
    if not isinstance(first, Mapping):
        return None

    geometry = first.get("geometry")
    if not isinstance(geometry, Mapping):
        return None

    location = geometry.get("location")
    if not isinstance(location, Mapping):
        return None

    lat = location.get("lat")
    lng = location.get("lng")

    if lat is None or lng is None:
        return None

    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        return None

    return {
        "lat": lat_value,
        "lng": lng_value,
        "lon": lng_value,
        "formatted_address": first.get(
            "formatted_address",
            requested_address,
        ),
        "place_id": first.get("place_id"),
        "location_type": geometry.get("location_type"),
        "partial_match": bool(first.get("partial_match", False)),
        "source": "google",
        "status": "OK",
        "requested_address": requested_address,
    }


def geocode_address(
    address: Any,
    google_api_key: Optional[str] = None,
    *,
    database: Any = None,
    use_cache: bool = True,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> Optional[dict[str, Any]]:
    """
    Geocode an address and return a structured result.

    Success:
        {
            "lat": 32.123,
            "lng": -89.456,
            "lon": -89.456,
            "formatted_address": "...",
            "source": "google" or "cache",
            ...
        }

    Failure:
        None

    The function does not raise for ordinary geocoding failures. That behavior
    is intentional so a bad customer address cannot blank a Streamlit tab.
    """
    cleaned = clean_address(address)
    if not cleaned:
        return None

    if use_cache:
        cached = _cache_lookup(cleaned, database)
        if cached:
            lat, lng = cached
            return {
                "lat": lat,
                "lng": lng,
                "lon": lng,
                "formatted_address": cleaned,
                "place_id": None,
                "location_type": None,
                "partial_match": False,
                "source": "cache",
                "status": "OK",
                "requested_address": cleaned,
            }

    api_key = get_google_api_key(google_api_key)
    if not api_key:
        return None

    attempts = max(1, int(max_retries))

    for attempt_number in range(1, attempts + 1):
        try:
            response = _google_request(
                cleaned,
                api_key,
                timeout=timeout,
            )

            if response.status_code in _TRANSIENT_HTTP_STATUSES:
                if attempt_number < attempts:
                    time.sleep(retry_delay * attempt_number)
                    continue
                return None

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, Mapping):
                return None

            status = str(payload.get("status", "")).upper()

            if status in _TRANSIENT_GOOGLE_STATUSES:
                if attempt_number < attempts:
                    time.sleep(retry_delay * attempt_number)
                    continue
                return None

            result = _parse_google_result(payload, cleaned)
            if result is None:
                return None

            if use_cache:
                _cache_save(
                    cleaned,
                    result["lat"],
                    result["lng"],
                    database,
                    source="google",
                )

            return result

        except (
            requests.Timeout,
            requests.ConnectionError,
        ):
            if attempt_number < attempts:
                time.sleep(retry_delay * attempt_number)
                continue
            return None

        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ):
            return None

    return None


def geocode(
    address: Any,
    google_api_key: Optional[str] = None,
    *,
    database: Any = None,
    use_cache: bool = True,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> tuple[Optional[float], Optional[float]]:
    """
    Legacy-compatible geocoder.

    Returns:
        (lat, lng)

    Failure:
        (None, None)

    The google_api_key argument is optional so both historical call patterns
    remain valid:

        geocode(address)
        geocode(address, GOOGLE_API_KEY)
    """
    result = geocode_address(
        address,
        google_api_key,
        database=database,
        use_cache=use_cache,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )

    if not result:
        return None, None

    return result["lat"], result["lng"]


def geocode_customer(
    customer: Mapping[str, Any],
    google_api_key: Optional[str] = None,
    *,
    database: Any = None,
    use_cache: bool = True,
) -> Optional[dict[str, Any]]:
    """
    Geocode one customer mapping.

    Recognized address fields:
    - address
    - street_address
    - city
    - state
    - zip
    - zip_code
    """
    street = customer.get("address") or customer.get("street_address")
    city = customer.get("city")
    state = customer.get("state")
    zip_code = customer.get("zip") or customer.get("zip_code")

    full_address = build_full_address(
        street,
        city,
        state,
        zip_code,
    )

    if not full_address:
        return None

    return geocode_address(
        full_address,
        google_api_key,
        database=database,
        use_cache=use_cache,
    )


def _customer_needs_geocode(customer: Mapping[str, Any]) -> bool:
    lat = customer.get("lat")
    lon = customer.get("lon", customer.get("lng"))

    if lat is None or lon is None:
        return True

    try:
        float(lat)
        float(lon)
        return False
    except (TypeError, ValueError):
        return True


def _update_customer_coordinates(
    customer: Mapping[str, Any],
    lat: float,
    lng: float,
    database: Any = None,
    update_callback: Optional[
        Callable[[Any, float, float], Any]
    ] = None,
) -> bool:
    """
    Persist coordinates using a callback or compatible database method.
    """
    customer_id = customer.get("id") or customer.get("customer_id")

    if customer_id is None:
        return False

    if update_callback is not None:
        try:
            update_callback(customer_id, lat, lng)
            return True
        except Exception:
            return False

    if database is None:
        return False

    method = getattr(database, "update_customer", None)
    if callable(method):
        attempts = (
            lambda: method(customer_id, lat=lat, lon=lng),
            lambda: method(customer_id, lat=lat, lng=lng),
            lambda: method(
                customer_id=customer_id,
                lat=lat,
                lon=lng,
            ),
        )

        for attempt in attempts:
            try:
                attempt()
                return True
            except TypeError:
                continue
            except Exception:
                return False

    for method_name in (
        "update_customer_coordinates",
        "save_customer_coordinates",
    ):
        method = getattr(database, method_name, None)
        if not callable(method):
            continue

        attempts = (
            lambda: method(customer_id, lat, lng),
            lambda: method(
                customer_id=customer_id,
                lat=lat,
                lon=lng,
            ),
            lambda: method(
                customer_id=customer_id,
                lat=lat,
                lng=lng,
            ),
        )

        for attempt in attempts:
            try:
                attempt()
                return True
            except TypeError:
                continue
            except Exception:
                return False

    return False


def geocode_customers(
    customers: Iterable[Mapping[str, Any]],
    google_api_key: Optional[str] = None,
    *,
    database: Any = None,
    only_missing: bool = True,
    use_cache: bool = True,
    update_callback: Optional[
        Callable[[Any, float, float], Any]
    ] = None,
    progress_callback: Optional[
        Callable[[int, int, Mapping[str, Any], str], Any]
    ] = None,
    delay_between_requests: float = 0.05,
) -> dict[str, Any]:
    """
    Bulk geocode customers.

    This function does not depend on Streamlit UI components. A tab can pass
    callbacks for persistence and progress reporting.

    Returns a summary dictionary containing counts and failed customers.
    """
    customer_list = list(customers)
    total = len(customer_list)

    summary: dict[str, Any] = {
        "total": total,
        "attempted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
    }

    for index, customer in enumerate(customer_list, start=1):
        customer_name = (
            customer.get("customer_name")
            or customer.get("name")
            or f"Customer {customer.get('id', index)}"
        )

        if only_missing and not _customer_needs_geocode(customer):
            summary["skipped"] += 1
            if progress_callback:
                progress_callback(
                    index,
                    total,
                    customer,
                    "skipped",
                )
            continue

        summary["attempted"] += 1

        result = geocode_customer(
            customer,
            google_api_key,
            database=database,
            use_cache=use_cache,
        )

        if not result:
            summary["failed"] += 1
            summary["failures"].append(
                {
                    "customer_id": customer.get("id")
                    or customer.get("customer_id"),
                    "customer_name": customer_name,
                    "reason": "Address could not be geocoded",
                }
            )

            if progress_callback:
                progress_callback(
                    index,
                    total,
                    customer,
                    "failed",
                )
            continue

        persisted = _update_customer_coordinates(
            customer,
            result["lat"],
            result["lng"],
            database=database,
            update_callback=update_callback,
        )

        if database is None and update_callback is None:
            # Geocoding succeeded even though the caller did not request DB
            # persistence. Count it as updated for bulk-operation reporting.
            persisted = True

        if persisted:
            summary["updated"] += 1
            status = "updated"
        else:
            summary["failed"] += 1
            status = "failed"
            summary["failures"].append(
                {
                    "customer_id": customer.get("id")
                    or customer.get("customer_id"),
                    "customer_name": customer_name,
                    "reason": (
                        "Geocoded successfully but coordinates "
                        "could not be persisted"
                    ),
                }
            )

        if progress_callback:
            progress_callback(
                index,
                total,
                customer,
                status,
            )

        if delay_between_requests > 0 and index < total:
            time.sleep(delay_between_requests)

    return summary


def geocode_customer_address(
    address: Any,
    city: Any = None,
    state: Any = None,
    zip_code: Any = None,
    google_api_key: Optional[str] = None,
    *,
    database: Any = None,
) -> tuple[Optional[float], Optional[float]]:
    """
    Convenience wrapper for callers with separate address fields.

    Returns a legacy-compatible (lat, lng) tuple.
    """
    full_address = build_full_address(
        address,
        city,
        state,
        zip_code,
    )

    return geocode(
        full_address,
        google_api_key,
        database=database,
    )


def is_valid_coordinate(
    lat: Any,
    lng: Any,
) -> bool:
    """Return True when values form a valid latitude/longitude pair."""
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        return False

    return (
        -90.0 <= lat_value <= 90.0
        and -180.0 <= lng_value <= 180.0
    )


__all__ = [
    "GOOGLE_GEOCODING_URL",
    "address_cache_key",
    "build_full_address",
    "clean_address",
    "geocode",
    "geocode_address",
    "geocode_customer",
    "geocode_customer_address",
    "geocode_customers",
    "get_google_api_key",
    "is_valid_coordinate",
]
