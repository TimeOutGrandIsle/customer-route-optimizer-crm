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

from data.database import add_service_record


def import_applications(session):

    df = normalize_columns(
        application_dataframe(session)
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

            customer = _safe(
                row.get(
                    "customer",
                    row.get(
                        "name"
                    ),
                )
            )

            service = _safe(
                row.get(
                    "service"
                )
            )

            notes = _safe(
                row.get(
                    "notes"
                )
            )

            if customer and service:

                add_service_record(

                    customer_name=customer,

                    service_type=service,

                    notes=notes,

                )

                imported += 1

        except Exception as ex:

            session.errors.append(
                f"Application: {ex}"
            )

            errors += 1

    return {

        "imported": imported,

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

