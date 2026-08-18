
"""
services/import_excel.py

Excel import service for Time Out Lawncare CRM.

This module consolidates the older import helpers into one production-ready
service while preserving the existing workbook structure.

Supported primary worksheets:
- Customer_Data
- Applications
- Herbicide_Data
- Services & Prices
- Treatment Plans
- Chemical costs

Optional worksheets are tolerated and ignored unless explicitly handled.

Compatibility:
- import_excel(filepath) -> list[dict] for legacy core.crm callers
- import_workbook(filepath, progress_callback=None) -> full import report
- preview_workbook(filepath) -> workbook summary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import pandas as pd

from data.database import (
    add_chemical_cost,
    add_customer,
    add_product,
    add_service_definition,
    add_service_record,
    add_treatment_plan,
    get_customers,
)
from services.geocoding import build_full_address, geocode_address


REQUIRED_SHEETS = {
    "Customer_Data",
    "Applications",
    "Herbicide_Data",
    "Treatment Plans",
}

OPTIONAL_SHEETS = {
    "Invoice",
    "Quote",
    "Billing",
    "Services & Prices",
    "Chemical costs",
    "Application Report",
    "Reference",
    "Data",
    "PPE",
}

KNOWN_SHEETS = REQUIRED_SHEETS | OPTIONAL_SHEETS


@dataclass
class WorkbookSession:
    workbook: Path
    excel: Optional[pd.ExcelFile] = None
    sheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    loaded: bool = False


def normalize_column(name: Any) -> str:
    text = str(name).strip().lower()
    for char in (" ", "-", "/", "\\", ".", "(", ")", "#"):
        text = text.replace(char, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [normalize_column(col) for col in result.columns]
    return result


def _safe(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text or None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = pd.to_datetime(text, errors="raise")
        return parsed.date().isoformat()
    except Exception:
        return text


def open_workbook(workbook: str | Path) -> WorkbookSession:
    path = Path(workbook)
    if not path.exists():
        raise FileNotFoundError(path)

    session = WorkbookSession(workbook=path)
    session.excel = pd.ExcelFile(path)
    session.loaded = True
    return session


def workbook_sheet_names(session: WorkbookSession) -> List[str]:
    if session.excel is None:
        return []
    return list(session.excel.sheet_names)


def validate_workbook(session: WorkbookSession) -> bool:
    if session.excel is None:
        session.errors.append("Workbook is not open.")
        return False

    names = set(session.excel.sheet_names)
    missing = REQUIRED_SHEETS - names
    extra = names - KNOWN_SHEETS

    for sheet in sorted(missing):
        session.errors.append(f"Missing worksheet: {sheet}")

    for sheet in sorted(extra):
        session.warnings.append(f"Unknown worksheet: {sheet}")

    return len(session.errors) == 0


def load_all_sheets(session: WorkbookSession) -> Dict[str, pd.DataFrame]:
    if session.excel is None:
        raise RuntimeError("Workbook is not open.")

    for sheet in session.excel.sheet_names:
        session.sheets[sheet] = pd.read_excel(
            session.workbook,
            sheet_name=sheet,
        )

    return session.sheets


def workbook_summary(session: WorkbookSession) -> pd.DataFrame:
    rows = []
    for sheet_name in workbook_sheet_names(session):
        df = session.sheets.get(sheet_name)
        rows.append(
            {
                "Worksheet": sheet_name,
                "Rows": 0 if df is None else len(df),
                "Columns": 0 if df is None else len(df.columns),
                "Required": sheet_name in REQUIRED_SHEETS,
            }
        )
    return pd.DataFrame(rows)


def preview_sheet(
    session: WorkbookSession,
    sheet_name: str,
    rows: int = 25,
) -> pd.DataFrame:
    df = session.sheets.get(sheet_name)
    if df is None:
        return pd.DataFrame()
    return df.head(rows).copy()


def customer_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Customer_Data", pd.DataFrame())


def application_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Applications", pd.DataFrame())


def herbicide_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Herbicide_Data", pd.DataFrame())


def services_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Services & Prices", pd.DataFrame())


def treatment_plan_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Treatment Plans", pd.DataFrame())


def chemical_cost_dataframe(session: WorkbookSession) -> pd.DataFrame:
    return session.sheets.get("Chemical costs", pd.DataFrame())


def _existing_customer_keys() -> set[tuple[str, str]]:
    df = get_customers()
    if df is None or df.empty:
        return set()

    keys: set[tuple[str, str]] = set()

    for _, row in df.iterrows():
        name = _safe(row.get("name")) or ""
        address = _safe(row.get("address")) or ""
        keys.add((name.casefold(), address.casefold()))

    return keys


def validate_customer_sheet(session: WorkbookSession) -> bool:
    df = normalize_columns(customer_dataframe(session))

    if df.empty:
        session.errors.append("Customer_Data worksheet is empty.")
        return False

    aliases = {
        "customer_name": {"customer_name", "name"},
        "street_address": {"street_address", "address", "street"},
        "city": {"city"},
        "state": {"state"},
        "zip": {"zip", "zipcode", "zip_code"},
    }

    actual = set(df.columns)

    missing: list[str] = []
    for canonical, choices in aliases.items():
        if not actual.intersection(choices):
            missing.append(canonical)

    for column in missing:
        session.errors.append(f"Missing customer column: {column}")

    return not missing


def _first_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            value = row.get(name)
            if value is not None:
                try:
                    if pd.isna(value):
                        continue
                except Exception:
                    pass
                return value
    return None


def _customer_record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    customer_number = _safe(
        _first_value(row, "customer_number", "customer_no", "customer_id")
    )
    name = _safe(
        _first_value(row, "customer_name", "name")
    )
    street_address = _safe(
        _first_value(row, "street_address", "address", "street")
    )
    city = _safe(_first_value(row, "city"))
    state = _safe(_first_value(row, "state"))
    zip_code = _safe(
        _first_value(row, "zip", "zipcode", "zip_code")
    )
    county = _safe(_first_value(row, "county"))
    phone = _safe(_first_value(row, "phone"))
    email = _safe(_first_value(row, "email"))
    text_phone = _safe(
        _first_value(row, "text_phone", "text_address", "mobile")
    )

    square_feet = _safe_float(
        _first_value(
            row,
            "square_feet",
            "sq_ft",
            "sqft",
            "lawn_sqft",
        )
    )

    turf_type = _safe(_first_value(row, "turf_type"))
    irrigation = _safe(_first_value(row, "irrigation"))
    payment_method = _safe(_first_value(row, "payment_method"))
    quote = _safe_float(_first_value(row, "quote", "price"))
    active_value = _first_value(row, "active")
    active = 1 if active_value in (None, "", True, 1, "1", "Y", "Yes", "yes") else 0

    special_instructions = _safe(
        _first_value(
            row,
            "special_instructions",
            "description",
            "notes",
        )
    )

    service = _safe(
        _first_value(row, "service", "service_type")
    )
    last_service = _safe_date(
        _first_value(row, "last_service", "last_service_date")
    )

    customer_type = _safe(
        _first_value(row, "customer_type", "type")
    ) or "Residential"

    account_name = _safe(
        _first_value(row, "account_name", "commercial_account")
    )

    address = build_full_address(
        street_address,
        city,
        state,
        zip_code,
    )

    return {
        "customer_number": customer_number,
        "name": name,
        "address": address,
        "street_address": street_address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "county": county,
        "phone": phone,
        "email": email,
        "text_phone": text_phone,
        "square_feet": square_feet,
        "turf_type": turf_type,
        "irrigation": irrigation,
        "payment_method": payment_method,
        "quote": quote,
        "active": active,
        "special_instructions": special_instructions,
        "service": service,
        "last_service": last_service,
        "customer_type": customer_type,
        "account_name": account_name,
    }


def import_customers(
    session: WorkbookSession,
    *,
    geocode: bool = True,
) -> dict[str, Any]:
    if not validate_customer_sheet(session):
        return {
            "imported": 0,
            "duplicates": 0,
            "errors": 0,
            "rows": [],
        }

    df = normalize_columns(customer_dataframe(session))
    existing = _existing_customer_keys()

    imported = 0
    duplicates = 0
    errors = 0
    imported_rows: list[dict[str, Any]] = []

    for index, row in df.iterrows():
        record = _customer_record_from_row(row)

        name = record.get("name")
        address = record.get("address") or ""

        if not name:
            session.errors.append(
                f"Customer_Data row {index + 2}: missing customer name."
            )
            errors += 1
            continue

        key = (str(name).casefold(), str(address).casefold())

        if key in existing:
            duplicates += 1
            continue

        lat = None
        lng = None

        if geocode and address:
            try:
                geo = geocode_address(address)
            except Exception as ex:
                geo = None
                session.warnings.append(
                    f"{name}: geocoding failed: {ex}"
                )

            if geo:
                lat = geo.get("lat")
                lng = geo.get("lng")

        kwargs = dict(record)
        kwargs["lat"] = lat
        kwargs["lng"] = lng

        # The current database layer may or may not yet expose the new
        # customer_type/account_name parameters. Try the full new schema first,
        # then fall back to the legacy signature while retaining import support.
        try:
            add_customer(**kwargs)
        except TypeError:
            legacy = {
                key: value
                for key, value in kwargs.items()
                if key not in {"customer_type", "account_name"}
            }
            add_customer(**legacy)

        existing.add(key)
        imported += 1

        imported_rows.append(
            {
                **record,
                "lat": lat,
                "lng": lng,
            }
        )

    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "rows": imported_rows,
    }


def import_products(session: WorkbookSession) -> dict[str, int]:
    df = normalize_columns(herbicide_dataframe(session))
    if df.empty:
        return {"imported": 0, "errors": 0}

    imported = 0
    errors = 0

    for index, row in df.iterrows():
        name = _safe(
            _first_value(row, "product_name", "product", "name")
        )
        if not name:
            session.warnings.append(
                f"Herbicide_Data row {index + 2}: blank product name."
            )
            continue

        try:
            add_product(
                product_name=name,
                product_type=_safe(
                    _first_value(row, "product_type", "type")
                ),
                manufacturer=_safe(
                    _first_value(row, "manufacturer")
                ),
                epa_number=_safe(
                    _first_value(row, "epa_number", "epa")
                ),
                active_ingredient=_safe(
                    _first_value(row, "active_ingredient")
                ),
                default_rate=_safe_float(
                    _first_value(row, "default_rate", "rate")
                ),
                rate_unit=_safe(
                    _first_value(row, "rate_unit", "unit")
                ),
                notes=_safe(_first_value(row, "notes")),
            )
            imported += 1
        except Exception as ex:
            session.errors.append(
                f"Herbicide_Data row {index + 2}: {ex}"
            )
            errors += 1

    return {"imported": imported, "errors": errors}


def import_services(session: WorkbookSession) -> dict[str, int]:
    df = normalize_columns(services_dataframe(session))
    if df.empty:
        return {"imported": 0, "errors": 0}

    imported = 0
    errors = 0

    for index, row in df.iterrows():
        name = _safe(
            _first_value(row, "service_name", "service", "name")
        )
        if not name:
            continue

        try:
            add_service_definition(
                service_name=name,
                category=_safe(_first_value(row, "category")),
                price=_safe_float(_first_value(row, "price")),
                description=_safe(
                    _first_value(row, "description", "notes")
                ),
            )
            imported += 1
        except Exception as ex:
            session.errors.append(
                f"Services & Prices row {index + 2}: {ex}"
            )
            errors += 1

    return {"imported": imported, "errors": errors}


def import_treatment_plans(
    session: WorkbookSession,
) -> dict[str, int]:
    df = normalize_columns(treatment_plan_dataframe(session))
    if df.empty:
        return {"imported": 0, "errors": 0}

    imported = 0
    errors = 0

    for index, row in df.iterrows():
        plan_name = _safe(
            _first_value(row, "plan_name", "plan", "name")
        )
        if not plan_name:
            continue

        kwargs = {
            "plan_name": plan_name,
            "description": _safe(
                _first_value(row, "description")
            ),
            "frequency": _safe(
                _first_value(row, "frequency")
            ),
            "notes": _safe(_first_value(row, "notes")),
        }

        # Newer schemas may support additional fields. We do not require them
        # to preserve compatibility with the current database layer.
        try:
            add_treatment_plan(**kwargs)
            imported += 1
        except Exception as ex:
            session.errors.append(
                f"Treatment Plans row {index + 2}: {ex}"
            )
            errors += 1

    return {"imported": imported, "errors": errors}


def import_chemical_costs(
    session: WorkbookSession,
) -> dict[str, int]:
    df = normalize_columns(chemical_cost_dataframe(session))
    if df.empty:
        return {"imported": 0, "errors": 0}

    imported = 0
    errors = 0

    for index, row in df.iterrows():
        product_name = _safe(
            _first_value(row, "product_name", "product", "name")
        )
        if not product_name:
            continue

        try:
            add_chemical_cost(
                product_name=product_name,
                container_size=_safe(
                    _first_value(row, "container_size")
                ),
                unit_cost=_safe_float(
                    _first_value(row, "unit_cost", "cost")
                ),
                cost_per_unit=_safe_float(
                    _first_value(row, "cost_per_unit")
                ),
                vendor=_safe(_first_value(row, "vendor")),
                notes=_safe(_first_value(row, "notes")),
            )
            imported += 1
        except Exception as ex:
            session.errors.append(
                f"Chemical costs row {index + 2}: {ex}"
            )
            errors += 1

    return {"imported": imported, "errors": errors}


def _customer_lookup() -> dict[str, int]:
    df = get_customers()
    if df is None or df.empty:
        return {}

    lookup: dict[str, int] = {}

    for _, row in df.iterrows():
        customer_id = row.get("id")
        name = _safe(row.get("name"))
        number = _safe(row.get("customer_number"))

        if customer_id is None:
            continue

        if name:
            lookup[f"name:{name.casefold()}"] = int(customer_id)
        if number:
            lookup[f"number:{number.casefold()}"] = int(customer_id)

    return lookup


def import_applications(
    session: WorkbookSession,
) -> dict[str, int]:
    """
    Import historical Applications as service history.

    The current live database architecture stores completed historical work in
    service_history, so this function preserves that behavior.
    """
    df = normalize_columns(application_dataframe(session))
    if df.empty:
        return {"imported": 0, "errors": 0, "unmatched": 0}

    lookup = _customer_lookup()

    imported = 0
    errors = 0
    unmatched = 0

    for index, row in df.iterrows():
        customer_number = _safe(
            _first_value(row, "customer_number", "customer_no")
        )
        customer_name = _safe(
            _first_value(row, "customer_name", "name", "customer")
        )

        customer_id = None

        if customer_number:
            customer_id = lookup.get(
                f"number:{customer_number.casefold()}"
            )

        if customer_id is None and customer_name:
            customer_id = lookup.get(
                f"name:{customer_name.casefold()}"
            )

        if customer_id is None:
            unmatched += 1
            session.warnings.append(
                f"Applications row {index + 2}: customer not found "
                f"({customer_name or customer_number or 'unknown'})."
            )
            continue

        service_type = _safe(
            _first_value(
                row,
                "treatment_type",
                "service_type",
                "service",
                "treatment",
            )
        ) or "Imported Application"

        notes_parts: list[str] = []

        application_date = _safe_date(
            _first_value(
                row,
                "service_date",
                "application_date",
                "date",
            )
        )
        applicator = _safe(
            _first_value(row, "applicator", "technician")
        )
        product = _safe(
            _first_value(row, "product_name", "product")
        )
        rate = _safe(
            _first_value(row, "application_rate", "rate")
        )
        quantity = _safe(
            _first_value(row, "quantity_used", "quantity")
        )
        raw_notes = _safe(_first_value(row, "notes"))

        if application_date:
            notes_parts.append(f"Imported service date: {application_date}")
        if applicator:
            notes_parts.append(f"Applicator: {applicator}")
        if product:
            notes_parts.append(f"Product: {product}")
        if rate:
            notes_parts.append(f"Rate: {rate}")
        if quantity:
            notes_parts.append(f"Quantity: {quantity}")
        if raw_notes:
            notes_parts.append(raw_notes)

        notes = " | ".join(notes_parts)

        try:
            add_service_record(
                customer_id=customer_id,
                service_type=service_type,
                notes=notes,
            )
            imported += 1
        except Exception as ex:
            session.errors.append(
                f"Applications row {index + 2}: {ex}"
            )
            errors += 1

    return {
        "imported": imported,
        "errors": errors,
        "unmatched": unmatched,
    }


def import_master_data(
    session: WorkbookSession,
    *,
    geocode_customers: bool = True,
) -> dict[str, dict[str, Any]]:
    return {
        "customers": import_customers(
            session,
            geocode=geocode_customers,
        ),
        "products": import_products(session),
        "services": import_services(session),
        "treatment_plans": import_treatment_plans(session),
        "chemical_costs": import_chemical_costs(session),
    }


def _notify(
    progress_callback: Optional[Callable[[int, str], Any]],
    percent: int,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(percent, message)


def import_workbook(
    workbook: str | Path,
    *,
    progress_callback: Optional[Callable[[int, str], Any]] = None,
    geocode_customers: bool = True,
    import_application_history: bool = True,
) -> dict[str, Any]:
    """
    Import the supported Time Out Lawncare workbook into the live database.

    Returns a structured report that the Streamlit Import tab can display.
    """
    _notify(progress_callback, 5, "Opening workbook")

    session = open_workbook(workbook)
    valid = validate_workbook(session)

    _notify(progress_callback, 10, "Loading worksheets")
    load_all_sheets(session)

    if not valid:
        return {
            "success": False,
            "errors": list(session.errors),
            "warnings": list(session.warnings),
            "results": {},
            "summary": workbook_summary(session),
        }

    _notify(progress_callback, 20, "Importing customers")
    customer_result = import_customers(
        session,
        geocode=geocode_customers,
    )

    _notify(progress_callback, 40, "Importing products")
    product_result = import_products(session)

    _notify(progress_callback, 55, "Importing services")
    service_result = import_services(session)

    _notify(progress_callback, 65, "Importing treatment plans")
    plan_result = import_treatment_plans(session)

    _notify(progress_callback, 75, "Importing chemical costs")
    chemical_result = import_chemical_costs(session)

    if import_application_history:
        _notify(progress_callback, 85, "Importing application history")
        application_result = import_applications(session)
    else:
        application_result = {
            "imported": 0,
            "errors": 0,
            "unmatched": 0,
        }

    results = {
        "customers": customer_result,
        "products": product_result,
        "services": service_result,
        "treatment_plans": plan_result,
        "chemical_costs": chemical_result,
        "applications": application_result,
    }

    total_errors = sum(
        int(result.get("errors", 0))
        for result in results.values()
    )

    _notify(progress_callback, 100, "Import complete")

    return {
        "success": total_errors == 0,
        "errors": list(session.errors),
        "warnings": list(session.warnings),
        "results": results,
        "summary": workbook_summary(session),
    }


def import_complete_workbook(
    workbook: str | Path,
    *,
    progress_callback: Optional[Callable[[int, str], Any]] = None,
) -> dict[str, Any]:
    """Backward-compatible alias for the full workbook importer."""
    return import_workbook(
        workbook,
        progress_callback=progress_callback,
    )


def run_workbook_import(
    workbook: str | Path,
    *,
    progress_callback: Optional[Callable[[int, str], Any]] = None,
) -> dict[str, Any]:
    """Backward-compatible alias used by the older Import tab."""
    return import_workbook(
        workbook,
        progress_callback=progress_callback,
    )


def preview_workbook(
    workbook: str | Path,
) -> dict[str, Any]:
    session = open_workbook(workbook)
    validate_workbook(session)
    load_all_sheets(session)

    return {
        "valid": len(session.errors) == 0,
        "errors": list(session.errors),
        "warnings": list(session.warnings),
        "summary": workbook_summary(session),
        "session": session,
    }


def import_excel(
    filepath: str | Path,
    *,
    geocode: bool = True,
) -> List[Dict[str, Any]]:
    """
    Legacy customer-only import function.

    Existing core.crm code expects import_excel(filepath) to return customer
    dictionaries, then writes those records to the database itself. Therefore
    this compatibility function parses Customer_Data without performing DB
    inserts.
    """
    session = open_workbook(filepath)
    load_all_sheets(session)

    df = normalize_columns(customer_dataframe(session))
    if df.empty:
        return []

    customers: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        record = _customer_record_from_row(row)

        if not record.get("name"):
            continue

        lat = None
        lng = None

        if geocode and record.get("address"):
            try:
                geo = geocode_address(record["address"])
            except Exception:
                geo = None

            if geo:
                lat = geo.get("lat")
                lng = geo.get("lng")

        customers.append(
            {
                **record,
                "lat": lat,
                "lng": lng,
            }
        )

    return customers


__all__ = [
    "KNOWN_SHEETS",
    "OPTIONAL_SHEETS",
    "REQUIRED_SHEETS",
    "WorkbookSession",
    "application_dataframe",
    "chemical_cost_dataframe",
    "customer_dataframe",
    "herbicide_dataframe",
    "import_applications",
    "import_chemical_costs",
    "import_complete_workbook",
    "import_customers",
    "import_excel",
    "import_master_data",
    "import_products",
    "import_services",
    "import_treatment_plans",
    "import_workbook",
    "load_all_sheets",
    "normalize_column",
    "normalize_columns",
    "open_workbook",
    "preview_sheet",
    "preview_workbook",
    "run_workbook_import",
    "services_dataframe",
    "treatment_plan_dataframe",
    "validate_customer_sheet",
    "validate_workbook",
    "workbook_sheet_names",
    "workbook_summary",
]
