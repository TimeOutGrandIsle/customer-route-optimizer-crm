"""
Time Out Lawncare CRM Core Controller

This module acts as the central service layer between:
- Streamlit UI (app.py)
- Database layer (database.py)
- Routing engine (routing.py)
- Geocoding (geocoding.py)
- Import/export tools (import_excel.py)
"""

# from typing import List, Dict, Any, Optional
# from datetime import datetime

import pandas as pd

from data.database import (
    init_db,
    add_customer,
    get_customers,
    update_customer,
    delete_customer,
    add_dispatch_job,
    get_dispatch_jobs,
    update_dispatch_status,
    add_service_record,
    set_setting,
    get_setting,
)

from services.geocoding import geocode_address, geocode_customers
from services.routing import build_route, build_dispatch_route
from services.import_excel import import_excel
from services.safety import ensure_dataframe


# =========================
# INITIALIZATION
# =========================
def initialize_system():
    """
    Ensures DB tables exist before app runs.
    """
    init_db()


# =========================
# CUSTOMER OPS
# =========================
def create_customer(
    name: str,
    address: str,
    service: str | None = None,
):
    if not name.strip():
        raise ValueError("Customer name is required.")

    if not address.strip():
        raise ValueError("Customer address is required.")

    lat = None
    lng = None

    try:
        geo = geocode_address(address)

        if geo:
            lat = geo.get("lat")
            lng = geo.get("lng")

    except Exception:
        pass

    add_customer(
        name=name.strip(),
        address=address.strip(),
        lat=lat,
        lng=lng,
        service=service,
        last_service=None,
    )


# def list_customers() -> pd.DataFrame:
    # return get_customers()
def list_customers():
    df = get_customers()
    return ensure_dataframe(df, "list_customers")


def edit_customer(customer_id: int, **kwargs):
    if "address" in kwargs:
        # geo = geocode_address(kwargs["address"])
        # if geo:
            # kwargs["lat"] = geo["lat"]
            # kwargs["lng"] = geo["lng"]
        try:
            geo = geocode_address(address)
        except Exception:
            geo = None

    update_customer(customer_id, **kwargs)


def remove_customer(customer_id: int):
    delete_customer(customer_id)


# =========================
# IMPORT OPS
# =========================
def import_customers_from_excel(filepath: str) -> List[Dict]:
    """
    Imports customers and writes them to DB.
    """
    customers = import_excel(filepath)

    for c in customers:
        add_customer(
            name=c.get("name"),
            address=c.get("address"),
            lat=c.get("lat"),
            lng=c.get("lng"),
            service=c.get("service"),
            last_service=c.get("last_service"),
        )

    return customers


# =========================
# DISPATCH OPS
# =========================
def create_dispatch_job(customer_id: int, scheduled_date: str = None, notes: str = ""):
    add_dispatch_job(customer_id, scheduled_date, notes)


# def list_dispatch_jobs(status: str = None) -> pd.DataFrame:
    # return get_dispatch_jobs(status=status)
def list_dispatch_jobs(status: str = None):
    df = get_dispatch_jobs(status=status)
    return ensure_dataframe(df, "list_dispatch_jobs")
    


def optimize_dispatch_route() -> List[Dict[str, Any]]:
    """
    Builds optimized route from queued dispatch jobs.
    """
    jobs_df = list_dispatch_jobs(status="queued")
# def optimize_dispatch_route():
    # df = list_dispatch_jobs()
    # return ensure_dataframe(df, "optimize_dispatch_route")(status="queued")

    if jobs_df.empty:
        return []

    depot = {
        "name": get_setting("depot_name") or "Depot",
        "address": get_setting("depot_address") or "Time Out Depot",
        "lat": float(get_setting("depot_lat") or 32.273),
        "lng": float(get_setting("depot_lng") or -89.985),
    }

    jobs = jobs_df.to_dict("records")

    return build_dispatch_route(depot, jobs)


def complete_dispatch_job(job_id: int):
    update_dispatch_status(job_id, "completed")


def cancel_dispatch_job(job_id: int):
    update_dispatch_status(job_id, "cancelled")


# =========================
# SERVICE LOGGING
# =========================
def log_service(customer_id: int, service_type: str, notes: str = ""):
    add_service_record(customer_id, service_type, notes)


# =========================
# SETTINGS
# =========================
def update_depot(name: str, address: str, lat: float, lng: float):
    set_setting("depot_name", name)
    set_setting("depot_address", address)
    set_setting("depot_lat", str(lat))
    set_setting("depot_lng", str(lng))


def get_depot() -> Dict[str, Any]:
    return {
        "name": get_setting("depot_name"),
        "address": get_setting("depot_address"),
        "lat": get_setting("depot_lat"),
        "lng": get_setting("depot_lng"),
    }


# =========================
# ROUTE WRAPPERS
# =========================
def build_manual_route(customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return build_route(customers)


# =========================
# DASHBOARD HELPERS
# =========================
def get_dashboard_stats() -> Dict[str, Any]:
    customers = get_customers()
    jobs = get_dispatch_jobs()

    queued = len(jobs[jobs["status"] == "queued"]) if not jobs.empty else 0
    completed = len(jobs[jobs["status"] == "completed"]) if not jobs.empty else 0

    return {
        "total_customers": len(customers),
        "queued_jobs": queued,
        "completed_jobs": completed,
    }
    
def customer_exists(customer_id: int) -> bool:
    df = list_customers()
    return customer_id in df["id"].values
    
def customer_count() -> int:
    return len(list_customers())
    
def dispatch_count(status=None) -> int:
    return len(list_dispatch_jobs(status=status))
