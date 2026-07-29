# Time Out Lawncare CRM
# Dispatch Engine
# Version 2.0
#


from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

import streamlit as st

from core.crm import (
    list_customers,
)


from core.crm import (
    list_dispatch_jobs,
    get_depot,
)

from data.database import (
    execute,
    get_dispatch_jobs,
    update_dispatch_status,
)

from services.routing import (
    build_dispatch_route,
    build_multi_crew_routes,
    driver_manifest,
    route_summary,
    route_dataframe,
)

# ==========================================================
# DISPATCH SUMMARY
# ==========================================================

def dispatch_summary():

    customers = list_customers()

    if customers is None or customers.empty:

        return {

            "customers": 0,

            "jobs_today": 0,

            "completed": 0,

            "remaining": 0,

            "estimated_revenue": 0.0,

        }

    jobs_today = len(customers)

    completed = 0

    remaining = jobs_today

    estimated_revenue = 0.0

    if "price" in customers.columns:

        estimated_revenue = (

            pd.to_numeric(

                customers["price"],

                errors="coerce",

            )

            .fillna(0)

            .sum()

        )

    return {

        "customers": len(customers),

        "jobs_today": jobs_today,

        "completed": completed,

        "remaining": remaining,

        "estimated_revenue": estimated_revenue,

    }
# =========================
# SESSION STATE HELPERS (Streamlit-friendly)
# =========================
# ==========================================================
# DATABASE HELPERS
# ==========================================================

def get_dispatch_queue(
    scheduled_date=None,
) -> List[Dict[str, Any]]:
    """
    Return active stops for one scheduled date.
    """
    selected_date = (
        pd.to_datetime(
            scheduled_date or date.today()
        )
        .date()
        .isoformat()
    )

    df = list_dispatch_jobs()

    if df.empty:
        return []

    active = df[
        df["status"].isin(
            ["queued", "in_progress"]
        )
    ].copy()

    active["scheduled_date"] = pd.to_datetime(
        active["scheduled_date"],
        errors="coerce",
    ).dt.date.astype(str)

    active = active[
        active["scheduled_date"]
        == selected_date
    ]

    if active.empty:
        return []

    return active.to_dict("records")


def get_all_dispatch_jobs() -> List[Dict[str, Any]]:
    """
    Returns every dispatch job.
    """

    df = list_dispatch_jobs()

    if df.empty:
        return []

    return df.to_dict("records")

# =========================
# QUEUE MANAGEMENT
# =========================
def add_to_queue(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adds metadata wrapper around a job for UI usage.
    """
    job["added_at"] = datetime.now().isoformat()
    job["status_local"] = "queued_ui"
    return job


def build_queue_from_customers(customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts customer list into dispatch queue format.
    """
    queue = []
    for c in customers:
        queue.append({
            "customer_id": c.get("id"),
            "name": c.get("name"),
            "address": c.get("address"),
            "lat": c.get("lat"),
            "lng": c.get("lng"),
            "service": c.get("service"),
            "status": "queued"
        })
    return queue


def clear_queue() -> None:
    """
    Cancel every active queue across all scheduled dates
    and release linked planned treatments.
    """
    jobs = [
        job
        for job in get_all_dispatch_jobs()
        if str(job.get("status", "")).lower()
        in {"queued", "in_progress"}
    ]

    for job in jobs:

        mark_job_cancelled(
            int(job["id"])
        )


# ==========================================================
# ROUTE BUILDING
# ==========================================================

def build_daily_route(
    scheduled_date=None,
) -> List[Dict[str, Any]]:
    """
    Returns an optimized route from the same active,
    date-filtered queue displayed on the Dispatch tab.
    """

    return build_route_from_queue(
        get_dispatch_queue(
            scheduled_date=scheduled_date
        )
    )


def build_route_from_queue(
    queue: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Builds an optimized route from an in-memory queue.
    """

    if not queue:
        return []

    depot = get_depot()

    if not depot.get("lat"):
        depot = {
            "name": "Time Out Lawncare",
            "address": "Brandon, MS",
            "lat": 32.2737,
            "lng": -89.9865,
        }

    return build_dispatch_route(
        depot,
        queue,
    )


def build_driver_manifest() -> List[Dict[str, Any]]:
    """
    Creates a printable driver manifest for today's route.
    """

    route = build_daily_route()

    if not route:
        return []

    return driver_manifest(route)


def build_dispatch_summary() -> Dict[str, Any]:
    """
    Returns route statistics for today's work.
    """

    route = build_daily_route()

    if not route:
        return {
            "stops": 0,
            "distance_miles": 0,
            "drive_minutes": 0,
            "service_minutes": 0,
            "total_minutes": 0,
            "google_maps": "",
        }

    return route_summary(route)


def build_dispatch_dataframe() -> pd.DataFrame:
    """
    Driver-friendly DataFrame.
    """

    route = build_daily_route()

    if not route:
        return pd.DataFrame()

    return route_dataframe(route)


def build_multi_driver_routes(
    crews: int = 2,
    scheduled_date=None,
):
    """
    Splits queued work between multiple crews.
    """

    jobs = get_dispatch_queue(
        scheduled_date=scheduled_date
    )

    if not jobs:
        return []

    depot = get_depot()

    if not depot.get("lat"):
        depot = {
            "name": "Time Out Lawncare",
            "address": "Brandon, MS",
            "lat": 32.2737,
            "lng": -89.9865,
        }

    return build_multi_crew_routes(
        depot,
        jobs,
        crews,
    )


# ==========================================================
# DISPATCH STATUS
# ==========================================================

def mark_job_complete(
    job_id: int,
):
    update_dispatch_status(
        job_id,
        "completed",
    )


def mark_job_in_progress(
    job_id: int,
):
    update_dispatch_status(
        job_id,
        "in_progress",
    )

def release_linked_treatments(
    job_id: int,
):
    execute(
        """
        UPDATE treatment_events
        SET dispatch_job_id=NULL
        WHERE dispatch_job_id=?
          AND status='planned'
        """,
        (int(job_id),),
    )


def mark_job_cancelled(
    job_id: int,
):
    release_linked_treatments(
        job_id
    )

    update_dispatch_status(
        job_id,
        "cancelled",
    )


def cancel_entire_queue():
    """
    Cancel every active queue across all scheduled dates
    and return planned treatments to Scheduling.
    """
    jobs = [
        job
        for job in get_all_dispatch_jobs()
        if str(job.get("status", "")).lower()
        in {"queued", "in_progress"}
    ]

    for job in jobs:

        mark_job_cancelled(
            int(job["id"])
        )


def cancel_queue_for_date(
    scheduled_date=None,
):
    """
    Cancel the active queue for one scheduled date and
    return linked planned treatments to Scheduling.
    """
    jobs = get_dispatch_queue(
        scheduled_date=scheduled_date
    )

    for job in jobs:

        mark_job_cancelled(
            int(job["id"])
        )


def complete_entire_queue():
    """
    Marks today's queue complete.
    """

    jobs = get_dispatch_queue()

    for job in jobs:

        update_dispatch_status(
            job["id"],
            "completed",
        )


# ==========================================================
# DRIVER VIEW
# ==========================================================

def get_driver_route_view() -> List[Dict[str, Any]]:
    """
    Driver-friendly view of today's route.
    """

    route = build_daily_route()

    if not route:
        return []

    driver_view = []

    for stop in route:

        driver_view.append({

            "stop":

                stop.get(
                    "stop_number",
                    0,
                ),

            "customer":

                stop.get(
                    "name",
                    "",
                ),

            "address":

                stop.get(
                    "address",
                    "",
                ),

            "service":

                stop.get(
                    "service",
                    "",
                ),

            "arrival_minutes":

                stop.get(
                    "arrival_minutes",
                    0,
                ),

            "drive_minutes":

                stop.get(
                    "drive_minutes",
                    0,
                ),

            "distance_miles":

                stop.get(
                    "distance_miles",
                    0,
                ),

            "notes":

                stop.get(
                    "notes",
                    "",
                ),

        })

    return driver_view


def next_stop(
    route: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Returns the next customer stop.
    """

    if not route:
        return None

    for stop in route:

        if stop.get("stop_number", 0) == 0:
            continue

        if stop.get("completed", False):
            continue

        return stop

    return None


def remaining_stops(
    route: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    return [

        stop

        for stop in route

        if (
            stop.get("stop_number", 0) > 0
            and
            not stop.get("completed", False)
        )

    ]


# ==========================================================
# ANALYTICS
# ==========================================================

def dispatch_statistics() -> Dict[str, Any]:
    """
    Dashboard statistics.
    """

    jobs = get_all_dispatch_jobs()

    queued = 0
    progress = 0
    complete = 0
    cancelled = 0

    for job in jobs:

        status = job.get(
            "status",
            "",
        )

        if status == "queued":
            queued += 1

        elif status == "in_progress":
            progress += 1

        elif status == "completed":
            complete += 1

        elif status == "cancelled":
            cancelled += 1

    summary = build_dispatch_summary()

    return {

        "queued":

            queued,

        "in_progress":

            progress,

        "completed":

            complete,

        "cancelled":

            cancelled,

        "route":

            summary,

    }


def dispatch_dashboard(
    scheduled_date=None,
) -> Dict[str, Any]:
    """
    Build one selected-date queue and reuse it for every
    dashboard view.
    """
    selected_date = (
        pd.to_datetime(
            scheduled_date or date.today()
        )
        .date()
        .isoformat()
    )

    queued_jobs = get_dispatch_queue(
        scheduled_date=selected_date
    )
    all_jobs = get_all_dispatch_jobs()
    route = build_route_from_queue(
        queued_jobs
    )

    if route:
        summary = route_summary(route)
        manifest = driver_manifest(route)
        dataframe = route_dataframe(route)
    else:
        summary = {
            "stops": 0,
            "distance_miles": 0,
            "drive_minutes": 0,
            "service_minutes": 0,
            "total_minutes": 0,
            "google_maps": "",
        }
        manifest = []
        dataframe = pd.DataFrame()

    status_counts = {
        "queued": 0,
        "in_progress": 0,
        "completed": 0,
        "cancelled": 0,
    }

    for job in all_jobs:
        status = job.get("status", "")

        if status in status_counts:
            status_counts[status] += 1

    future_active = 0

    for job in all_jobs:

        status = str(
            job.get("status", "")
        ).lower()

        if status not in {
            "queued",
            "in_progress",
        }:
            continue

        job_date = pd.to_datetime(
            job.get("scheduled_date"),
            errors="coerce",
        )

        if (
            not pd.isna(job_date)
            and job_date.date() > date.today()
        ):
            future_active += 1

    statistics = {
        **status_counts,
        "selected_date": selected_date,
        "selected_date_active": len(
            queued_jobs
        ),
        "future_active": future_active,
        "route": summary,
    }

    return {
        "jobs": queued_jobs,
        "route": route,
        "manifest": manifest,
        "summary": summary,
        "statistics": statistics,
        "dataframe": dataframe,
    }


# ==========================================================
# EXPORTS
# ==========================================================

__all__ = [

    "get_dispatch_queue",

    "get_all_dispatch_jobs",

    "build_daily_route",

    "build_route_from_queue",

    "build_driver_manifest",

    "build_dispatch_summary",

    "build_dispatch_dataframe",

    "build_multi_driver_routes",

    "mark_job_complete",

    "mark_job_in_progress",

    "mark_job_cancelled",

    "cancel_entire_queue",

    "cancel_queue_for_date",

    "complete_entire_queue",

    "get_driver_route_view",

    "next_stop",

    "remaining_stops",

    "dispatch_statistics",

    "dispatch_dashboard",

]
