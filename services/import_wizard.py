#
#Time Out Lawncare CRM
#Workbook Import Wizard
#

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

# ==========================================================
# REQUIRED WORKSHEETS
# ==========================================================

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
    
    "Chemical costs",

}

# ==========================================================
# IMPORT SESSION
# ==========================================================

class WorkbookImportSession:

    def __init__(self, workbook):

        self.workbook = Path(workbook)

        self.excel = None

        self.sheets = {}

        self.errors = []

        self.warnings = []

        self.loaded = False
        
# ==========================================================
# OPEN WORKBOOK
# ==========================================================

def open_workbook(workbook):

    session = WorkbookImportSession(workbook)

    if not session.workbook.exists():

        raise FileNotFoundError(session.workbook)

    session.excel = pd.ExcelFile(session.workbook)

    session.loaded = True

    return session
    
# ==========================================================
# SHEET LIST
# ==========================================================

def workbook_sheet_names(session):

    return session.excel.sheet_names



# ==========================================================
# VERIFY WORKBOOK
# ==========================================================

def validate_workbook(session):

    names = set(session.excel.sheet_names)

    missing = REQUIRED_SHEETS - names

    extra = names - REQUIRED_SHEETS - OPTIONAL_SHEETS

    if missing:

        for sheet in sorted(missing):

            session.errors.append(

                f"Missing worksheet: {sheet}"

            )

    if extra:

        for sheet in sorted(extra):

            session.warnings.append(

                f"Unknown worksheet: {sheet}"

            )

    return len(session.errors) == 0


# ==========================================================
# LOAD ALL SHEETS
# ==========================================================

def load_all_sheets(session):

    for sheet in session.excel.sheet_names:

        session.sheets[sheet] = pd.read_excel(

            session.workbook,

            sheet_name=sheet,

        )

    return session.sheets


# ==========================================================
# PREVIEW
# ==========================================================

def preview_sheet(

    session,

    sheet_name,

    rows=10,

):

    if sheet_name not in session.sheets:

        return pd.DataFrame()

    return session.sheets[sheet_name].head(rows)


# ==========================================================
# SHEET INFORMATION
# ==========================================================

def workbook_summary(session):

    summary = []

    for sheet in session.excel.sheet_names:

        df = session.sheets.get(sheet)

        if df is None:

            continue

        summary.append({

            "Worksheet": sheet,

            "Rows": len(df),

            "Columns": len(df.columns),

        })

    return pd.DataFrame(summary)


# ==========================================================
# CUSTOMER DATA
# ==========================================================

def customer_dataframe(session):

    return session.sheets.get(

        "Customer_Data",

        pd.DataFrame(),

    )


# ==========================================================
# APPLICATIONS
# ==========================================================

def application_dataframe(session):

    return session.sheets.get(

        "Applications",

        pd.DataFrame(),

    )


# ==========================================================
# PRODUCTS
# ==========================================================

def herbicide_dataframe(session):

    return session.sheets.get(

        "Herbicide_Data",

        pd.DataFrame(),

    )


# ==========================================================
# SERVICES
# ==========================================================

def services_dataframe(session):

    return session.sheets.get(

        "Services & Prices",

        pd.DataFrame(),

    )


# ==========================================================
# TREATMENT PLANS
# ==========================================================

def treatment_plan_dataframe(session):

    return session.sheets.get(

        "Treatment Plans",

        pd.DataFrame(),

    )


# ==========================================================
# CHEMICAL COSTS
# ==========================================================

def chemical_cost_dataframe(session):

    return session.sheets.get(

        "Chemical costs",

        pd.DataFrame(),

    )

# ==========================================================
# CUSTOMER IMPORTS
# ==========================================================

from services.geocoding import geocode_address

from data.database import (
    add_customer,
    get_customers,
)

# ==========================================================
# COLUMN HELPERS
# ==========================================================

def normalize_column(name):

    return (
        str(name)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def normalize_columns(df):

    df = df.copy()

    df.columns = [
        normalize_column(c)
        for c in df.columns
    ]

    return df


# ==========================================================
# CUSTOMER VALIDATION
# ==========================================================

def validate_customer_sheet(session):

    df = customer_dataframe(session)

    if df.empty:

        session.errors.append(
            "Customer_Data worksheet is empty."
        )

        return False

    df = normalize_columns(df)

    required = {

    "customer_name",

    "street_address",

    "city",

    "state",

    "zip",

    }

    missing = required - set(df.columns)

    if missing:

        for column in sorted(missing):

            session.errors.append(
                f"Missing customer column: {column}"
            )

        return False

    return True


# ==========================================================
# DUPLICATE LOOKUP
# ==========================================================

def existing_customer_keys():

    df = get_customers()

    if df.empty:

        return set()

    keys = set()

    for _, row in df.iterrows():

        name = str(
            row.get(
                "name",
                "",
            )
        ).strip().lower()

        address = str(
            row.get(
                "address",
                "",
            )
        ).strip().lower()

        keys.add(
            (
                name,
                address,
            )
        )

    return keys


# ==========================================================
# ADDRESS CLEANUP
# ==========================================================

def clean_address(address):

    if pd.isna(address):

        return ""

    address = str(address).strip()

    address = address.replace(
        "\n",
        " ",
    )

    while "  " in address:

        address = address.replace(
            "  ",
            " ",
        )

    return address


# ==========================================================
# CUSTOMER IMPORT
# ==========================================================

def import_customers(session):

    if not validate_customer_sheet(session):

        return {

            "imported": 0,

            "duplicates": 0,

            "errors": 0,

        }

    df = normalize_columns(

        customer_dataframe(session)

    )

    existing = existing_customer_keys()

    imported = 0

    duplicates = 0

    errors = 0

    for _, row in df.iterrows():

        try:

            customer_number = _safe(
                row.get("customer_number")
            )

            name = _safe(
                row.get("customer_name")
            )

            street_address = clean_address(
                row.get("street_address")
            )

            city = _safe(
                row.get("city")
            )

            state = _safe(
                row.get("state")
            )

            zipcode = _safe(
                row.get("zip")
            )

            county = _safe(
                row.get("county")
            )

            phone = _safe(
                row.get("phone")
            )

            email = _safe(
                row.get("email")
            )

            text_phone = _safe(
                row.get("text_address")
            )

            square_feet = row.get(
                "square_feet"
            )

            if pd.isna(square_feet):

                square_feet = None

            turf_type = _safe(
                row.get("turf_type")
            )

            irrigation = _safe(
                row.get("irrigation")
            )

            payment_method = _safe(
                row.get("payment_method")
            )

            special_instructions = _safe(
                row.get("description")
            )

            service = _safe(
                row.get("service")
            )

            last_service = row.get(
                "last_service"
            )

            address = ", ".join(

                x for x in [

                    street_address,

                    city,

                    state,

                    zipcode,

                ]

                if x

            )

            key = (

                (name or "").lower(),

                address.lower(),

            )

            if key in existing:

                duplicates += 1

                continue

            geo = geocode_address(address)

            lat = None

            lng = None

            if geo:

                lat = geo.get("lat")

                lng = geo.get("lng")

            add_customer(

                customer_number=customer_number,

                name=name,

                address=address,

                street_address=street_address,

                city=city,

                state=state,

                zip=zipcode,

                county=county,

                phone=phone,

                email=email,

                text_phone=text_phone,

                square_feet=square_feet,

                turf_type=turf_type,

                irrigation=irrigation,

                payment_method=payment_method,

                special_instructions=special_instructions,

                lat=lat,

                lng=lng,

                service=service,

                last_service=last_service,

            )

            existing.add(key)

            imported += 1

        except Exception as ex:

            session.errors.append(

                f"{name}: {ex}"

            )

            errors += 1

    return {

        "imported": imported,

        "duplicates": duplicates,

        "errors": errors,

    }


# ==========================================================
# CUSTOMER PREVIEW
# ==========================================================

def customer_preview(session):

    df = normalize_columns(

        customer_dataframe(session)

    )

    keep = [

        c

        for c in [

            "name",

            "address",

            "service",

            "last_service",

        ]

        if c in df.columns

    ]

    return df[keep].head(25)


# ==========================================================
# CUSTOMER STATISTICS
# ==========================================================

def customer_statistics(session):

    df = normalize_columns(

        customer_dataframe(session)

    )

    return {

        "rows":

            len(df),

        "columns":

            len(df.columns),

        "blank_names":

            int(

                df["name"]

                .isna()

                .sum()

            )

            if "name" in df.columns

            else 0,

        "blank_addresses":

            int(

                df["address"]

                .isna()

                .sum()

            )

            if "address" in df.columns

            else 0,

    }
    
# ==========================================================
# PRODUCT IMPORTS
# ==========================================================

from data.database import (
    add_product,
    add_service_definition,
    add_treatment_plan,
    add_chemical_cost,
)


def _safe(value):

    if pd.isna(value):
        return None

    text = str(value).strip()

    if text == "":
        return None

    return text


# ==========================================================
# HERBICIDES
# ==========================================================

def import_products(session):

    df = normalize_columns(
        herbicide_dataframe(session)
    )

    if df.empty:

        return {
            "imported": 0,
            "errors": 0,
        }

    imported = 0
    errors = 0

    for _, row in df.iterrows():

        try:

            add_product(

                product_name=_safe(
                    row.get(
                        "product_name",
                        row.get(
                            "product",
                            row.get(
                                "name"
                            )
                        ),
                    )
                ),

                product_type=_safe(
                    row.get(
                        "product_type",
                        row.get(
                            "type"
                        ),
                    )
                ),

                manufacturer=_safe(
                    row.get(
                        "manufacturer"
                    )
                ),

                epa_number=_safe(
                    row.get(
                        "epa_number"
                    )
                ),

                active_ingredient=_safe(
                    row.get(
                        "active_ingredient"
                    )
                ),

                default_rate=row.get(
                    "rate",
                    row.get(
                        "default_rate"
                    ),
                ),

                rate_unit=_safe(
                    row.get(
                        "rate_unit"
                    )
                ),

                notes=_safe(
                    row.get(
                        "notes"
                    )
                ),

            )

            imported += 1

        except Exception as ex:

            session.errors.append(
                f"Product: {ex}"
            )

            errors += 1

    return {

        "imported": imported,

        "errors": errors,

    }


# ==========================================================
# SERVICES
# ==========================================================

def import_services(session):

    df = normalize_columns(
        services_dataframe(session)
    )

    if df.empty:

        return {

            "imported": 0,

            "errors": 0,

        }

    imported = 0
    errors = 0

    for _, row in df.iterrows():

        try:

            add_service_definition(

                service_name=_safe(
                    row.get(
                        "service_name",
                        row.get(
                            "service"
                        ),
                    )
                ),

                category=_safe(
                    row.get(
                        "category"
                    )
                ),

                price=row.get(
                    "price"
                ),

                description=_safe(
                    row.get(
                        "description"
                    )
                ),

            )

            imported += 1

        except Exception as ex:

            session.errors.append(
                f"Service: {ex}"
            )

            errors += 1

    return {

        "imported": imported,

        "errors": errors,

    }


# ==========================================================
# TREATMENT PLANS
# ==========================================================

def import_treatment_plans(session):

    df = normalize_columns(
        treatment_plan_dataframe(session)
    )

    if df.empty:

        return {

            "imported": 0,

            "errors": 0,

        }

    imported = 0
    errors = 0

    for _, row in df.iterrows():

        try:

            add_treatment_plan(

                plan_name=_safe(
                    row.get(
                        "plan_name",
                        row.get(
                            "plan"
                        ),
                    )
                ),

                description=_safe(
                    row.get(
                        "description"
                    )
                ),

                frequency=_safe(
                    row.get(
                        "frequency"
                    )
                ),

                notes=_safe(
                    row.get(
                        "notes"
                    )
                ),

            )

            imported += 1

        except Exception as ex:

            session.errors.append(
                f"Treatment Plan: {ex}"
            )

            errors += 1

        return {
            "imported": imported,
            "errors": errors,
        }


# ==========================================================
# CHEMICAL COSTS
# ==========================================================

def import_chemical_costs(session):

    df = normalize_columns(
        chemical_cost_dataframe(session)
    )

    if df.empty:

        return {

            "imported": 0,

            "errors": 0,

        }

    imported = 0
    errors = 0

    for _, row in df.iterrows():

        try:

            add_chemical_cost(

                product_name=_safe(
                    row.get(
                        "product_name",
                        row.get(
                            "product"
                        ),
                    )
                ),

                container_size=_safe(
                    row.get(
                        "container_size"
                    )
                ),

                unit_cost=row.get(
                    "unit_cost"
                ),

                cost_per_unit=row.get(
                    "cost_per_unit"
                ),

                vendor=_safe(
                    row.get(
                        "vendor"
                    )
                ),

                notes=_safe(
                    row.get(
                        "notes"
                    )
                ),

            )

            imported += 1

        except Exception as ex:

            session.errors.append(
                f"Chemical Cost: {ex}"
            )

            errors += 1

    return {

        "imported": imported,

        "errors": errors,

    }


# ==========================================================
# IMPORT EVERYTHING EXCEPT APPLICATIONS
# ==========================================================

def import_master_data(session):

    results = {}

    results["customers"] = import_customers(session)

    results["products"] = import_products(session)

    results["services"] = import_services(session)

    results["treatment_plans"] = import_treatment_plans(session)

    results["chemical_costs"] = import_chemical_costs(session)

    return results
    
# ==========================================================
# APPLICATION IMPORT
# ==========================================================


def import_applications(session):
    """
    Import the Applications worksheet without discarding fields.
    Each worksheet row becomes one application with unlimited
    linked chemical rows.
    """
    import hashlib
    import json
    import re
    from datetime import datetime, time

    from core.treatment_manager import (
        initialize_treatment_system,
    )
    from data.database import (
        get_connection,
        get_customers,
        get_products,
    )

    initialize_treatment_system()

    df = normalize_columns(
        application_dataframe(session)
    )

    if df.empty:
        return {
            "imported": 0,
            "duplicates": 0,
            "errors": 0,
        }

    customers = get_customers()
    products = get_products()

    customer_lookup = {}

    if not customers.empty:
        customer_lookup = {
            str(row["name"]).strip().casefold():
            int(row["id"])
            for _, row in customers.iterrows()
        }

    product_lookup = {}

    if not products.empty:
        product_lookup = {
            str(row["product_name"]).strip().casefold():
            {
                "id": int(row["id"]),
                "epa_number": str(
                    row["epa_number"] or ""
                ),
            }
            for _, row in products.iterrows()
            if row.get("product_name") is not None
        }

    def clean_value(value):
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        if isinstance(value, pd.Timestamp):
            return value.isoformat()

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, time):
            return value.strftime("%H:%M:%S")

        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass

        text = str(value).strip()

        return text if text else None

    def date_value(value):
        cleaned = clean_value(value)

        if cleaned is None:
            return None

        try:
            if isinstance(value, (int, float)):
                parsed = pd.to_datetime(
                    value,
                    unit="D",
                    origin="1899-12-30",
                )
            else:
                parsed = pd.to_datetime(value)

            return parsed.date().isoformat()

        except Exception:
            return str(cleaned)

    def time_value(value):
        cleaned = clean_value(value)

        if cleaned is None:
            return None

        if isinstance(value, time):
            return value.strftime("%H:%M:%S")

        if isinstance(value, datetime):
            return value.strftime("%H:%M:%S")

        if isinstance(value, pd.Timestamp):
            return value.strftime("%H:%M:%S")

        if isinstance(value, (int, float)):
            total_seconds = round(
                float(value) * 86400
            )

            hours = (
                total_seconds // 3600
            ) % 24

            minutes = (
                total_seconds % 3600
            ) // 60

            seconds = total_seconds % 60

            return (
                f"{hours:02d}:"
                f"{minutes:02d}:"
                f"{seconds:02d}"
            )

        return str(cleaned)

    def numeric_value(value):
        cleaned = clean_value(value)

        if cleaned is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            str(cleaned).replace(",", ""),
        )

        if not match:
            return None

        return float(match.group())

    imported = 0
    duplicates = 0
    errors = 0

    conn = get_connection()

    try:
        cursor = conn.cursor()

        for dataframe_index, row in df.iterrows():
            excel_row_number = int(
                dataframe_index
            ) + 2

            try:
                raw_record = {
                    str(column): clean_value(
                        row.get(column)
                    )
                    for column in df.columns
                }

                raw_json = json.dumps(
                    raw_record,
                    sort_keys=True,
                    default=str,
                )

                source_hash = hashlib.sha256(
                    json.dumps(
                        {
                            "sheet": "Applications",
                            "row": excel_row_number,
                            "data": raw_record,
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()

                cursor.execute(
                    """
                    SELECT id
                    FROM imported_applications
                    WHERE source_hash=?
                    """,
                    (source_hash,),
                )

                if cursor.fetchone() is not None:
                    duplicates += 1
                    continue

                customer_name = clean_value(
                    row.get("customer_name")
                )

                if not customer_name:
                    raise ValueError(
                        f"Row {excel_row_number}: "
                        "Customer Name is missing."
                    )

                customer_id = customer_lookup.get(
                    str(customer_name)
                    .strip()
                    .casefold()
                )

                if customer_id is None:
                    session.warnings.append(
                        f"Application row "
                        f"{excel_row_number}: customer "
                        f"not matched: {customer_name}"
                    )

                applicator = clean_value(
                    row.get("applicator")
                )

                applicator_id = clean_value(
                    row.get("id_number")
                )

                if applicator:
                    name_parts = str(
                        applicator
                    ).strip().split(
                        maxsplit=1
                    )

                    first_name = name_parts[0]

                    last_name = (
                        name_parts[1]
                        if len(name_parts) > 1
                        else ""
                    )

                    employee = None

                    if applicator_id:
                        employee = cursor.execute(
                            """
                            SELECT id
                            FROM employees
                            WHERE id_number=?
                            LIMIT 1
                            """,
                            (str(applicator_id),),
                        ).fetchone()

                    if employee is None:
                        employee = cursor.execute(
                            """
                            SELECT id
                            FROM employees
                            WHERE LOWER(first_name)=LOWER(?)
                              AND LOWER(last_name)=LOWER(?)
                            LIMIT 1
                            """,
                            (
                                first_name,
                                last_name,
                            ),
                        ).fetchone()

                    if employee is None:
                        cursor.execute(
                            """
                            INSERT INTO employees (
                                first_name,
                                last_name,
                                id_number,
                                active
                            )
                            VALUES (?, ?, ?, 1)
                            """,
                            (
                                first_name,
                                last_name,
                                applicator_id,
                            ),
                        )

                    elif applicator_id:
                        cursor.execute(
                            """
                            UPDATE employees
                            SET id_number=COALESCE(
                                NULLIF(id_number, ''),
                                ?
                            )
                            WHERE id=?
                            """,
                            (
                                str(applicator_id),
                                int(employee["id"]),
                            ),
                        )

                cursor.execute(
                    """
                    INSERT INTO imported_applications (
                        source_hash,
                        source_row_number,
                        customer_id,
                        customer_name,
                        application_date,
                        application_start_time,
                        application_end_time,
                        applicator,
                        applicator_id_number,
                        treatment_type,
                        size_of_area_treated,
                        raw_data
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        source_hash,
                        excel_row_number,
                        customer_id,
                        str(customer_name),
                        date_value(
                            row.get(
                                "application_date"
                            )
                        ),
                        time_value(
                            row.get(
                                "application_start_time"
                            )
                        ),
                        time_value(
                            row.get(
                                "application_end_time"
                            )
                        ),
                        applicator,
                        applicator_id,
                        clean_value(
                            row.get(
                                "treatment_type"
                            )
                        ),
                        clean_value(
                            row.get(
                                "size_of_area_treated"
                            )
                        ),
                        raw_json,
                    ),
                )

                application_id = (
                    cursor.lastrowid
                )

                chemical_positions = sorted(
                    {
                        int(match.group(1))
                        for column in df.columns
                        for match in [
                            re.fullmatch(
                                r"brand_name_(\d+)",
                                str(column),
                            )
                        ]
                        if match
                    }
                )

                for position in chemical_positions:
                    brand_name = clean_value(
                        row.get(
                            f"brand_name_{position}"
                        )
                    )

                    if not brand_name:
                        continue

                    matched_product = (
                        product_lookup.get(
                            str(brand_name)
                            .strip()
                            .casefold()
                        )
                    )

                    product_id = (
                        matched_product["id"]
                        if matched_product
                        else None
                    )

                    epa_number = (
                        matched_product[
                            "epa_number"
                        ]
                        if matched_product
                        else ""
                    )

                    cursor.execute(
                        """
                        INSERT INTO imported_application_chemicals (
                            application_id,
                            chemical_position,
                            product_id,
                            brand_name,
                            active_ingredients,
                            rate_per_acre,
                            total_amount_oz,
                            epa_number
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            application_id,
                            position,
                            product_id,
                            str(brand_name),
                            clean_value(
                                row.get(
                                    "active_ingredients_"
                                    f"{position}"
                                )
                            ),
                            clean_value(
                                row.get(
                                    "rate_per_acre_"
                                    f"{position}"
                                )
                            ),
                            numeric_value(
                                row.get(
                                    "total_amount_"
                                    "applied_(oz)_"
                                    f"{position}"
                                )
                            ),
                            epa_number,
                        ),
                    )

                imported += 1

            except Exception as ex:
                errors += 1

                session.errors.append(
                    f"Application row "
                    f"{excel_row_number}: {ex}"
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
    }


# ==========================================================
# COMPLETE IMPORT
# ==========================================================

def import_workbook(session):

    results = import_master_data(session)

    results["applications"] = import_applications(session)

    return results


# ==========================================================
# IMPORT SUMMARY
# ==========================================================

def import_summary(session, results):

    rows = []

    total_imported = 0

    total_errors = 0

    for section, data in results.items():

        imported = data.get(
            "imported",
            0,
        )

        errors = data.get(
            "errors",
            0,
        )

        total_imported += imported

        total_errors += errors

        rows.append({

            "Section": section,

            "Imported": imported,

            "Errors": errors,

        })

    summary = pd.DataFrame(rows)

    return {

        "summary": summary,

        "total_imported": total_imported,

        "total_errors": total_errors,

        "warnings": session.warnings,

        "errors": session.errors,

    }


# ==========================================================
# ONE-CALL IMPORT
# ==========================================================

def run_import(workbook):

    session = open_workbook(workbook)

    if not validate_workbook(session):

        return {

            "success": False,

            "errors": session.errors,

        }

    load_all_sheets(session)

    results = import_workbook(session)

    report = import_summary(

        session,

        results,

    )

    report["success"] = True

    return report
    
# ==========================================================
# PROGRESS CALLBACK
# ==========================================================

def run_import_with_progress(

    workbook,

    progress_callback=None,

):

    session = open_workbook(workbook)

    if not validate_workbook(session):

        return {

            "success": False,

            "errors": session.errors,

        }

    load_all_sheets(session)

    steps = [

        ("Customers", import_customers),

        ("Products", import_products),

        ("Services", import_services),

        ("Treatment Plans", import_treatment_plans),

        ("Chemical Costs", import_chemical_costs),

        ("Applications", import_applications),

    ]

    results = {}

    total = len(steps)

    for index, (name, func) in enumerate(steps):

        if progress_callback:

            progress_callback(
                index / total,
                f"Importing {name}...",
            )

        result = func(session)

        if result is None:

            raise Exception(f"{name} importer returned None")

        if not isinstance(result, dict):

            raise Exception(
                f"{name} importer returned {type(result).__name__}"
            )

        results[name] = result

    report = build_import_report(

        session,

        results,

    )

    report["success"] = True

    return report

# ==========================================================
# BACKWARD-COMPATIBILITY WRAPPER
# ==========================================================

def import_complete_workbook(
    workbook,
    progress_callback=None,
):
    """
    Compatibility wrapper for older UI code.

    Delegates to the current progress-aware importer.
    """

    return run_import_with_progress(
        workbook,
        progress_callback=progress_callback,
    )


# ==========================================================
# IMPORT REPORT
# ==========================================================

def build_import_report(

    session,

    results,

):

    for name, result in results.items():

        if result is None:

            raise Exception(f"{name} result is None")

        if not isinstance(result, dict):

            raise Exception(
                f"{name} result is {type(result).__name__}"
            )

    rows = []

    total_imported = 0

    total_duplicates = 0

    total_errors = 0

    for section, result in results.items():

        imported = result.get(

            "imported",

            0,

        )

        duplicates = result.get(

            "duplicates",

            0,

        )

        errors = result.get(

            "errors",

            0,

        )

        total_imported += imported

        total_duplicates += duplicates

        total_errors += errors

        rows.append(

            {

                "Section": section,

                "Imported": imported,

                "Duplicates": duplicates,

                "Errors": errors,

            }

        )

    return {

        "summary": pd.DataFrame(rows),

        "total_imported": total_imported,

        "total_duplicates": total_duplicates,

        "total_errors": total_errors,

        "warnings": session.warnings,

        "errors": session.errors,

    }


# # ==========================================================
# # ONE-CALL IMPORT
# # ==========================================================

# report = import_complete_workbook(

    # temp_path,

    # progress_callback=update_progress,

# )


# ==========================================================
# PUBLIC EXPORTS
# ==========================================================

# ==========================================================
# IMPORT ENTRY POINT
# ==========================================================

def run_workbook_import(
    workbook,
    progress_callback=None,
):
    """
    Main public entry point used by the UI.
    """

    return run_import_with_progress(
        workbook,
        progress_callback=progress_callback,
    )


__all__ = [

    "open_workbook",

    "validate_workbook",

    "load_all_sheets",

    "preview_sheet",

    "workbook_summary",

    "customer_dataframe",

    "application_dataframe",

    "herbicide_dataframe",

    "services_dataframe",

    "treatment_plan_dataframe",

    "chemical_cost_dataframe",

    "customer_preview",

    "customer_statistics",

    "import_customers",

    "import_products",

    "import_services",

    "import_treatment_plans",

    "import_chemical_costs",

    "import_applications",

    "import_master_data",

    "run_import_with_progress",

    "build_import_report",
    
    "run_workbook_import",

    "import_complete_workbook",

]

