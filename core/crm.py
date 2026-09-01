"""
core/crm.py

Time Out Lawncare CRM Core Controller

This module is the central service layer between:
- Streamlit UI / app.py
- data/database.py
- services/geocoding.py
- services/routing.py
- services/import_excel.py

Responsibilities:
- System initialization
- Customer CRUD
- Customer Type / commercial-account filtering
- Import wrappers
- Dispatch wrappers
- Service logging
- Depot settings
- Dashboard helpers
- Table-layout preference wrappers

Important business rules:
- Customer Type is organizational metadata only.
- Residential, Small Commercial, and Commercial customers can be routed
  together normally.
- Queued dispatch jobs are eligible regardless of scheduled_date.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from data.database import (
    CUSTOMER_TYPES,
    add_customer,
    add_dispatch_job,
    add_service_record,
    customer_exists as db_customer_exists,
    delete_customer,
    get_customer,
    get_customers,
    get_customers_by_type,
    get_dispatch_jobs,
    get_queued_dispatch_jobs,
    get_setting,
    get_table_preferences,
    init_db,
    save_table_preferences,
    set_customer_type,
    set_setting,
    update_customer,
    update_dispatch_status,
)

from services.geocoding import (
    build_full_address,
    geocode_address,
)

from services.import_excel import import_excel

from services.routing import (
    build_dispatch_route,
    build_route,
)

from services.safety import ensure_dataframe


DEFAULT_DEPOT = {
    "name": "Time Out Lawncare",
    "address": "303 East Brandon Court, Brandon, MS 39042",
    "lat": 32.273,
    "lng": -89.985,
}


# ==========================================================
# INITIALIZATION
# ==========================================================

def initialize_system() -> None:
    """
    Ensure required database objects exist before the app renders.
    """
    init_db()


# ==========================================================
# CUSTOMER NORMALIZATION
# ==========================================================

def normalize_customer_type(
    customer_type: Optional[str],
) -> str:
    """
    Normalize Customer Type while enforcing the supported categories.
    """
    value = str(
        customer_type
        or "Residential"
    ).strip()

    if value not in CUSTOMER_TYPES:
        raise ValueError(
            "Customer Type must be one of: "
            + ", ".join(
                CUSTOMER_TYPES
            )
        )

    return value


def _clean_optional_text(
    value: Any,
) -> Optional[str]:
    if value is None:
        return None

    text = str(
        value
    ).strip()

    return (
        text
        if text
        else None
    )


def _build_customer_address(
    *,
    address: Optional[str] = None,
    street_address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> str:
    """
    Prefer an explicit full address; otherwise build one from components.
    """
    explicit = _clean_optional_text(
        address
    )

    if explicit:
        return explicit

    return build_full_address(
        street_address,
        city,
        state,
        zip_code,
    )


# ==========================================================
# CUSTOMER OPS
# ==========================================================

def create_customer(
    name: str,
    address: Optional[str] = None,
    service: Optional[str] = None,
    *,
    customer_number: Optional[str] = None,
    customer_type: str = "Residential",
    account_name: Optional[str] = None,
    street_address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip: Optional[str] = None,
    county: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    text_phone: Optional[str] = None,
    square_feet: Optional[float] = None,
    turf_type: Optional[str] = None,
    irrigation: Optional[str] = None,
    payment_method: Optional[str] = None,
    quote: Optional[float] = None,
    active: int = 1,
    special_instructions: Optional[str] = None,
    neighborhood: Optional[str] = None,
    cluster_id: int = 0,
    distance_from_cluster: float = 0,
    last_service: Optional[str] = None,
    standard_schedule: bool = True,
    geocode: bool = True,
) -> Any:
    """
    Create a customer using either a full address or separate address fields.

    Customer Type is stored on the customer and does not alter routing.
    Standard Schedule enrollment defaults ON for new customers.
    """
    clean_name = str(
        name
        or ""
    ).strip()

    if not clean_name:
        raise ValueError(
            "Customer name is required."
        )

    normalized_type = (
        normalize_customer_type(
            customer_type
        )
    )

    full_address = (
        _build_customer_address(
            address=address,
            street_address=street_address,
            city=city,
            state=state,
            zip_code=zip,
        )
    )

    if not full_address:
        raise ValueError(
            "Customer address is required."
        )

    lat = None
    lng = None

    if geocode:
        try:
            geo = geocode_address(
                full_address
            )
        except Exception:
            geo = None

        if geo:
            lat = geo.get(
                "lat"
            )
            lng = geo.get(
                "lng"
            )

    return add_customer(
        customer_number=customer_number,
        name=clean_name,
        account_name=(
            _clean_optional_text(
                account_name
            )
        ),
        customer_type=normalized_type,
        address=full_address,
        street_address=(
            _clean_optional_text(
                street_address
            )
        ),
        city=(
            _clean_optional_text(
                city
            )
        ),
        state=(
            _clean_optional_text(
                state
            )
        ),
        zip=(
            _clean_optional_text(
                zip
            )
        ),
        county=(
            _clean_optional_text(
                county
            )
        ),
        phone=(
            _clean_optional_text(
                phone
            )
        ),
        email=(
            _clean_optional_text(
                email
            )
        ),
        text_phone=(
            _clean_optional_text(
                text_phone
            )
        ),
        square_feet=(
            square_feet
        ),
        turf_type=(
            _clean_optional_text(
                turf_type
            )
        ),
        irrigation=(
            _clean_optional_text(
                irrigation
            )
        ),
        payment_method=(
            _clean_optional_text(
                payment_method
            )
        ),
        quote=quote,
        active=active,
        special_instructions=(
            _clean_optional_text(
                special_instructions
            )
        ),
        lat=lat,
        lng=lng,
        neighborhood=(
            _clean_optional_text(
                neighborhood
            )
        ),
        cluster_id=cluster_id,
        distance_from_cluster=(
            distance_from_cluster
        ),
        service=(
            _clean_optional_text(
                service
            )
        ),
        last_service=last_service,
        standard_schedule=int(
            bool(
                standard_schedule
            )
        ),
    )


def list_customers(
    customer_type: Optional[str] = None,
    *,
    active_only: bool = False,
) -> pd.DataFrame:
    """
    Return customers as a DataFrame.

    When customer_type is omitted or "All", all customer categories are
    returned. This keeps routing and scheduling independent of classification.
    """
    if (
        customer_type
        not in (
            None,
            "",
            "All",
        )
    ):
        df = get_customers_by_type(
            customer_type=(
                normalize_customer_type(
                    customer_type
                )
            ),
            active_only=active_only,
        )
    else:
        df = get_customers(
            active_only=active_only
        )

    return ensure_dataframe(
        df,
        "list_customers",
    )


def list_residential_customers(
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    return list_customers(
        "Residential",
        active_only=active_only,
    )


def list_small_commercial_customers(
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    return list_customers(
        "Small Commercial",
        active_only=active_only,
    )


def list_commercial_customers(
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    return list_customers(
        "Commercial",
        active_only=active_only,
    )


def list_all_commercial_customers(
    *,
    active_only: bool = True,
) -> pd.DataFrame:
    """
    Return Small Commercial + Commercial customers.
    """
    small = list_small_commercial_customers(
        active_only=active_only
    )

    commercial = list_commercial_customers(
        active_only=active_only
    )

    if small.empty:
        return commercial.reset_index(
            drop=True
        )

    if commercial.empty:
        return small.reset_index(
            drop=True
        )

    return pd.concat(
        [
            small,
            commercial,
        ],
        ignore_index=True,
    ).sort_values(
        by="name",
        kind="stable",
    ).reset_index(
        drop=True
    )


def get_customer_record(
    customer_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Return one customer record as a dictionary.
    """
    result = get_customer(
        int(
            customer_id
        )
    )

    if not result:
        return None

    return dict(
        result
    )


def edit_customer(
    customer_id: int,
    *,
    geocode: bool = True,
    **kwargs: Any,
) -> None:
    """
    Update customer fields.

    If address components change, the full address is rebuilt and re-geocoded.
    This fixes the prior bug where edit_customer() referred to an undefined
    `address` variable.
    """
    if not kwargs:
        return

    if (
        "customer_type"
        in kwargs
    ):
        kwargs[
            "customer_type"
        ] = normalize_customer_type(
            kwargs.get(
                "customer_type"
            )
        )

    address_fields = {
        "address",
        "street_address",
        "city",
        "state",
        "zip",
    }

    address_changed = any(
        field in kwargs
        for field
        in address_fields
    )

    if address_changed:
        current = (
            get_customer_record(
                customer_id
            )
            or {}
        )

        merged = {
            **current,
            **kwargs,
        }

        full_address = (
            _build_customer_address(
                address=merged.get(
                    "address"
                ),
                street_address=merged.get(
                    "street_address"
                ),
                city=merged.get(
                    "city"
                ),
                state=merged.get(
                    "state"
                ),
                zip_code=merged.get(
                    "zip"
                ),
            )
        )

        if full_address:
            kwargs[
                "address"
            ] = full_address

            if geocode:
                try:
                    geo = (
                        geocode_address(
                            full_address
                        )
                    )
                except Exception:
                    geo = None

                if geo:
                    kwargs[
                        "lat"
                    ] = geo.get(
                        "lat"
                    )
                    kwargs[
                        "lng"
                    ] = geo.get(
                        "lng"
                    )

    update_customer(
        int(
            customer_id
        ),
        **kwargs,
    )


def change_customer_type(
    customer_id: int,
    customer_type: str,
) -> None:
    """
    Change only Customer Type.
    """
    set_customer_type(
        int(
            customer_id
        ),
        normalize_customer_type(
            customer_type
        ),
    )


def remove_customer(
    customer_id: int,
) -> None:
    """
    Permanently delete a customer.

    Existing UI behavior is preserved. A future CRM screen may choose to use
    the database's deactivate_customer helper for safer archival.
    """
    delete_customer(
        int(
            customer_id
        )
    )


# ==========================================================
# CUSTOMER FILTER / SEARCH HELPERS
# ==========================================================

def customer_type_counts(
    *,
    active_only: bool = True,
) -> Dict[str, int]:
    """
    Counts used by the Customers tab category selector.
    """
    result: Dict[
        str,
        int,
    ] = {}

    total = 0

    for customer_type in CUSTOMER_TYPES:
        count = len(
            list_customers(
                customer_type,
                active_only=active_only,
            )
        )

        result[
            customer_type
        ] = count

        total += count

    result[
        "All"
    ] = total

    return result


def filter_customers(
    df: pd.DataFrame,
    *,
    customer_type: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = False,
) -> pd.DataFrame:
    """
    UI-level filtering without altering routing/scheduling rules.
    """
    result = ensure_dataframe(
        df,
        "filter_customers",
    ).copy()

    if result.empty:
        return result

    if (
        active_only
        and "active"
        in result.columns
    ):
        active_values = (
            pd.to_numeric(
                result[
                    "active"
                ],
                errors="coerce",
            )
            .fillna(0)
        )

        result = result[
            active_values.eq(
                1
            )
        ].copy()

    if (
        customer_type
        not in (
            None,
            "",
            "All",
        )
        and "customer_type"
        in result.columns
    ):
        result = result[
            result[
                "customer_type"
            ].fillna(
                "Residential"
            )
            == normalize_customer_type(
                customer_type
            )
        ].copy()

    clean_search = str(
        search
        or ""
    ).strip()

    if clean_search:
        searchable_columns = [
            column
            for column
            in (
                "name",
                "account_name",
                "address",
                "street_address",
                "city",
                "phone",
                "email",
                "service",
            )
            if column
            in result.columns
        ]

        if searchable_columns:
            mask = pd.Series(
                False,
                index=result.index,
            )

            for column in searchable_columns:
                mask = (
                    mask
                    | result[
                        column
                    ]
                    .fillna("")
                    .astype(str)
                    .str.contains(
                        clean_search,
                        case=False,
                        regex=False,
                    )
                )

            result = result[
                mask
            ].copy()

    if (
        "name"
        in result.columns
    ):
        result = result.sort_values(
            by="name",
            kind="stable",
        )

    return result.reset_index(
        drop=True
    )


# ==========================================================
# IMPORT OPS
# ==========================================================

def import_customers_from_excel(
    filepath: str,
) -> List[Dict[str, Any]]:
    """
    Parse customers from Excel and write them to the database.

    The import service returns the new Customer Type/account fields when they
    exist and remains compatible with older workbooks.
    """
    customers = import_excel(
        filepath
    )

    imported: List[
        Dict[str, Any]
    ] = []

    for customer in customers:
        customer_type = (
            customer.get(
                "customer_type"
            )
            or "Residential"
        )

        add_customer(
            customer_number=(
                customer.get(
                    "customer_number"
                )
            ),
            name=(
                customer.get(
                    "name"
                )
            ),
            account_name=(
                customer.get(
                    "account_name"
                )
            ),
            customer_type=(
                normalize_customer_type(
                    customer_type
                )
            ),
            address=(
                customer.get(
                    "address"
                )
            ),
            street_address=(
                customer.get(
                    "street_address"
                )
            ),
            city=(
                customer.get(
                    "city"
                )
            ),
            state=(
                customer.get(
                    "state"
                )
            ),
            zip=(
                customer.get(
                    "zip"
                )
            ),
            county=(
                customer.get(
                    "county"
                )
            ),
            phone=(
                customer.get(
                    "phone"
                )
            ),
            email=(
                customer.get(
                    "email"
                )
            ),
            text_phone=(
                customer.get(
                    "text_phone"
                )
            ),
            square_feet=(
                customer.get(
                    "square_feet"
                )
            ),
            turf_type=(
                customer.get(
                    "turf_type"
                )
            ),
            irrigation=(
                customer.get(
                    "irrigation"
                )
            ),
            payment_method=(
                customer.get(
                    "payment_method"
                )
            ),
            quote=(
                customer.get(
                    "quote"
                )
            ),
            active=(
                customer.get(
                    "active",
                    1,
                )
            ),
            special_instructions=(
                customer.get(
                    "special_instructions"
                )
            ),
            lat=(
                customer.get(
                    "lat"
                )
            ),
            lng=(
                customer.get(
                    "lng"
                )
            ),
            neighborhood=(
                customer.get(
                    "neighborhood"
                )
            ),
            cluster_id=(
                customer.get(
                    "cluster_id",
                    0,
                )
            ),
            distance_from_cluster=(
                customer.get(
                    "distance_from_cluster",
                    0,
                )
            ),
            service=(
                customer.get(
                    "service"
                )
            ),
            last_service=(
                customer.get(
                    "last_service"
                )
            ),
        )

        imported.append(
            customer
        )

    return imported


# ==========================================================
# DISPATCH OPS
# ==========================================================

def create_dispatch_job(
    customer_id: int,
    scheduled_date: Optional[str] = None,
    notes: str = "",
    treatment_name: Optional[str] = None,
) -> Any:
    """
    Queue a customer for Dispatch.

    scheduled_date is planning information only. Because the job is queued,
    it is immediately eligible for Dispatch regardless of that date.
    """
    return add_dispatch_job(
        customer_id=int(
            customer_id
        ),
        scheduled_date=scheduled_date,
        notes=notes,
        treatment_name=treatment_name,
    )


def list_dispatch_jobs(
    status: Optional[str] = None,
) -> pd.DataFrame:
    """
    Return dispatch jobs without recursion.

    This replaces an earlier broken implementation that accidentally called
    list_dispatch_jobs() from inside itself.
    """
    df = get_dispatch_jobs(
        status=status
    )

    return ensure_dataframe(
        df,
        "list_dispatch_jobs",
    )


def list_queued_dispatch_jobs(
    customer_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    Return the complete Dispatch-ready queue regardless of scheduled_date.
    """
    df = (
        get_queued_dispatch_jobs(
            customer_type=(
                customer_type
            )
        )
    )

    return ensure_dataframe(
        df,
        "list_queued_dispatch_jobs",
    )


def optimize_dispatch_route(
    customer_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build an optimized route from all queued jobs.

    Customer Type is only an optional user-selected filter. If omitted, mixed
    Residential / Small Commercial / Commercial jobs route together.
    """
    jobs_df = (
        list_queued_dispatch_jobs(
            customer_type=(
                customer_type
            )
        )
    )

    if jobs_df.empty:
        return []

    dispatch = (
        build_dispatch_route(
            jobs_df,
            get_depot(),
            max_stops_per_route=max(
                1,
                len(
                    jobs_df
                ),
            ),
        )
    )

    return list(
        dispatch.get(
            "route",
            [],
        )
    )


def complete_dispatch_job(
    job_id: int,
) -> None:
    update_dispatch_status(
        int(
            job_id
        ),
        "completed",
    )


def cancel_dispatch_job(
    job_id: int,
) -> None:
    update_dispatch_status(
        int(
            job_id
        ),
        "cancelled",
    )


# ==========================================================
# SERVICE LOGGING
# ==========================================================

def log_service(
    customer_id: int,
    service_type: str,
    notes: str = "",
) -> None:
    add_service_record(
        int(
            customer_id
        ),
        service_type,
        notes,
    )


# ==========================================================
# SETTINGS / DEPOT
# ==========================================================

def update_depot(
    name: str,
    address: str,
    lat: float,
    lng: float,
) -> None:
    set_setting(
        "depot_name",
        str(
            name
        ),
    )

    set_setting(
        "depot_address",
        str(
            address
        ),
    )

    set_setting(
        "depot_lat",
        str(
            float(
                lat
            )
        ),
    )

    set_setting(
        "depot_lng",
        str(
            float(
                lng
            )
        ),
    )


def get_depot() -> Dict[str, Any]:
    """
    Return a routing-ready depot dictionary with numeric coordinates.
    """
    name = (
        get_setting(
            "depot_name"
        )
        or DEFAULT_DEPOT[
            "name"
        ]
    )

    address = (
        get_setting(
            "depot_address"
        )
        or DEFAULT_DEPOT[
            "address"
        ]
    )

    try:
        lat = float(
            get_setting(
                "depot_lat"
            )
            or DEFAULT_DEPOT[
                "lat"
            ]
        )
    except (
        TypeError,
        ValueError,
    ):
        lat = float(
            DEFAULT_DEPOT[
                "lat"
            ]
        )

    try:
        lng = float(
            get_setting(
                "depot_lng"
            )
            or DEFAULT_DEPOT[
                "lng"
            ]
        )
    except (
        TypeError,
        ValueError,
    ):
        lng = float(
            DEFAULT_DEPOT[
                "lng"
            ]
        )

    return {
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
    }


# ==========================================================
# ROUTE WRAPPERS
# ==========================================================

def build_manual_route(
    customers: List[
        Dict[str, Any]
    ],
) -> List[Dict[str, Any]]:
    """
    Build a manual route without separating by Customer Type.
    """
    return build_route(
        customers,
        depot=get_depot(),
    )


# ==========================================================
# TABLE LAYOUT PREFERENCES
# ==========================================================

def save_customer_table_layout(
    column_order: Sequence[str],
    *,
    hidden_columns: Optional[
        Sequence[str]
    ] = None,
    sort_state: Any = None,
) -> None:
    """
    Persist Customers-table layout.
    """
    save_table_preferences(
        table_name="customers",
        column_order=column_order,
        hidden_columns=(
            hidden_columns
            or []
        ),
        sort_state=sort_state,
    )


def get_customer_table_layout() -> Dict[str, Any]:
    """
    Load persisted Customers-table layout.
    """
    return get_table_preferences(
        "customers"
    )


# ==========================================================
# DASHBOARD HELPERS
# ==========================================================

def get_dashboard_stats() -> Dict[str, Any]:
    customers = list_customers()

    jobs = list_dispatch_jobs()

    if jobs.empty:
        queued = 0
        completed = 0
    else:
        statuses = (
            jobs[
                "status"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            if "status"
            in jobs.columns
            else pd.Series(
                [],
                dtype=str,
            )
        )

        queued = int(
            statuses.eq(
                "queued"
            ).sum()
        )

        completed = int(
            statuses.eq(
                "completed"
            ).sum()
        )

    type_counts = (
        customer_type_counts(
            active_only=False
        )
    )

    return {
        "total_customers": (
            len(
                customers
            )
        ),
        "residential_customers": (
            type_counts.get(
                "Residential",
                0,
            )
        ),
        "small_commercial_customers": (
            type_counts.get(
                "Small Commercial",
                0,
            )
        ),
        "commercial_customers": (
            type_counts.get(
                "Commercial",
                0,
            )
        ),
        "queued_jobs": queued,
        "completed_jobs": (
            completed
        ),
    }


def customer_exists(
    customer_id: int,
) -> bool:
    """
    Database-backed existence check.
    """
    return bool(
        db_customer_exists(
            int(
                customer_id
            )
        )
    )


def customer_count(
    customer_type: Optional[str] = None,
) -> int:
    return len(
        list_customers(
            customer_type=(
                customer_type
            )
        )
    )


def dispatch_count(
    status: Optional[str] = None,
) -> int:
    return len(
        list_dispatch_jobs(
            status=status
        )
    )


__all__ = [
    "CUSTOMER_TYPES",
    "build_manual_route",
    "cancel_dispatch_job",
    "change_customer_type",
    "complete_dispatch_job",
    "create_customer",
    "create_dispatch_job",
    "customer_count",
    "customer_exists",
    "customer_type_counts",
    "dispatch_count",
    "edit_customer",
    "filter_customers",
    "get_customer_record",
    "get_customer_table_layout",
    "get_dashboard_stats",
    "get_depot",
    "import_customers_from_excel",
    "initialize_system",
    "list_all_commercial_customers",
    "list_commercial_customers",
    "list_customers",
    "list_dispatch_jobs",
    "list_queued_dispatch_jobs",
    "list_residential_customers",
    "list_small_commercial_customers",
    "log_service",
    "normalize_customer_type",
    "optimize_dispatch_route",
    "remove_customer",
    "save_customer_table_layout",
    "update_depot",
]
