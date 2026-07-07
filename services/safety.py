"""
services/safety.py

Common validation and defensive programming utilities used
throughout the Time Out Lawncare CRM.

This module exists to ensure that bad data is caught immediately
instead of causing silent Streamlit failures later.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

import pandas as pd


class SafetyError(Exception):
    """Base exception for safety validation."""


class DataValidationError(SafetyError):
    """Raised when invalid data is encountered."""


def ensure_dataframe(
    obj: Any,
    source: str = "Unknown"
) -> pd.DataFrame:
    """
    Ensure an object is a real pandas DataFrame.

    Parameters
    ----------
    obj
        Object returned by another function.

    source
        Name of calling function.

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    TypeError
        If the object is not a DataFrame.
    """

    if obj is None:
        raise DataValidationError(
            f"{source} returned None instead of DataFrame."
        )

    if obj is pd.DataFrame:
        raise DataValidationError(
            f"{source} returned the DataFrame CLASS instead of a DataFrame instance."
        )

    if not isinstance(obj, pd.DataFrame):
        raise DataValidationError(
            f"{source} returned {type(obj).__name__} instead of DataFrame."
        )

    return obj


def ensure_columns(
    df: pd.DataFrame,
    required_columns: Iterable[str],
    source: str = "Unknown"
) -> pd.DataFrame:
    """
    Verify required columns exist.
    """

    ensure_dataframe(df, source)

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise DataValidationError(
            f"{source} missing required columns: {missing}"
        )

    return df


def ensure_not_empty(
    df: pd.DataFrame,
    source: str = "Unknown"
) -> pd.DataFrame:
    """
    Raise if dataframe is empty.
    """

    ensure_dataframe(df, source)

    if df.empty:
        raise DataValidationError(
            f"{source} returned an empty DataFrame."
        )

    return df


def safe_string(value: Any) -> str:
    """
    Convert anything to a clean string.
    """

    if value is None:
        return ""

    return str(value).strip()


def safe_float(
    value: Any,
    default: Optional[float] = None
) -> Optional[float]:
    """
    Convert value to float.
    """

    if value in ("", None):
        return default

    try:
        return float(value)
    except Exception:
        return default


def safe_int(
    value: Any,
    default: Optional[int] = None
) -> Optional[int]:
    """
    Convert value to integer.
    """

    if value in ("", None):
        return default

    try:
        return int(value)
    except Exception:
        return default


def normalize_address(address: str) -> str:
    """
    Normalize an address for matching.
    """

    if address is None:
        return ""

    address = address.upper()

    replacements = {
        " ROAD": " RD",
        " STREET": " ST",
        " AVENUE": " AVE",
        " DRIVE": " DR",
        " LANE": " LN",
        " BOULEVARD": " BLVD",
        " HIGHWAY": " HWY",
        ".": "",
        ",": "",
    }

    for old, new in replacements.items():
        address = address.replace(old, new)

    return " ".join(address.split())


def safe_bool(value: Any) -> bool:
    """
    Convert many common values into bool.
    """

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    value = str(value).strip().lower()

    return value in (
        "1",
        "true",
        "yes",
        "y",
        "on"
    )


def safe_date(value: Any) -> Optional[pd.Timestamp]:
    """
    Convert value into pandas Timestamp.
    """

    if value in ("", None):
        return None

    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def dataframe_summary(df: pd.DataFrame) -> dict:
    """
    Return basic dataframe statistics for debugging.
    """

    ensure_dataframe(df, "dataframe_summary")

    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
        "empty": df.empty,
    }


def validate_lat_lon(
    latitude: Any,
    longitude: Any
) -> bool:
    """
    Validate geographic coordinates.
    """

    lat = safe_float(latitude)
    lon = safe_float(longitude)

    if lat is None or lon is None:
        return False

    if not (-90 <= lat <= 90):
        return False

    if not (-180 <= lon <= 180):
        return False

    return True


def require(condition: bool, message: str):
    """
    Simple assertion helper.
    """

    if not condition:
        raise DataValidationError(message)