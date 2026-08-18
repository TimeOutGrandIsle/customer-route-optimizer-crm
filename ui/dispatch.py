"""
ui/dispatch.py

Time Out Lawncare CRM
Dispatch Engine / Dispatch UI Service
Version 3.0

This module sits between Scheduling, the database layer, the route optimizer,
and the crew-facing field view.

Key business rules:
- Any job with status "queued" is eligible for Dispatch regardless of its
  scheduled_date.
- scheduled_date remains visible as planning information only.
- Customer Type never affects route optimization unless the caller explicitly
  asks to filter the queue by Customer Type.
- Multiple crews are supported.
- Each crew receives its own persistent dispatch manifest.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from core.crm import get_depot, list_customers, list_dispatch_jobs

from data.database import (
    assign_job_to_dispatch,
    clear_dispatch_manifest,
    create_dispatch,
    execute,
    get_crews,
    get_dispatch,
    get_dispatch_jobs_for_manifest,
    get_dispatches,
    get_queued_dispatch_jobs,
    mark_dispatch_sent,
    mark_job_arrived,
    mark_job_completed,
    queue_dispatch_job,
    update_dispatch_status,
)

from services.routing import (
    assign_routes_to_crews,
    build_dispatch_route,
    build_google_maps_route_url,
    build_navigation_url,
    next_stop as routing_next_stop,
    remaining_stops as routing_remaining_stops,
    route_dataframe,
    summarize_route,
)


DEFAULT_DEPOT = {
    "name": "Time Out Lawncare",
    "address": "303 East Brandon Court, Brandon, MS 39042",
    "lat": 32.2737,
    "lng": -89.9865,
}

ACTIVE_JOB_STATUSES = {
    "queued",
    "dispatched",
    "in_progress",
}

CLOSED_JOB_STATUSES = {
    "completed",
    "cancelled",
    "canceled",
}


# ==========================================================
# INTERNAL HELPERS
# ==========================================================

def _normalize_status(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_date(
    value: date | datetime | str | None,
) -> str:
    """
    Normalize a date-like value to YYYY-MM-DD.

    Dispatch eligibility does not depend on this value; it is used for
    manifest creation, reporting, and display only.
    """
    if value is None:
        return date.today().isoformat()

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _depot() -> Dict[str, Any]:
    """
    Load the configured depot and fall back safely if settings are incomplete.
    """
    try:
        depot = get_depot() or {}
    except Exception:
        depot = {}

    result = dict(DEFAULT_DEPOT)

    for key in (
        "name",
        "address",
        "lat",
        "lng",
    ):
        value = depot.get(key)
        if value not in (
            None,
            "",
        ):
            result[key] = value

    try:
        result["lat"] = float(
            result["lat"]
        )
    except Exception:
        result["lat"] = float(
            DEFAULT_DEPOT["lat"]
        )

    try:
        result["lng"] = float(
            result["lng"]
        )
    except Exception:
        result["lng"] = float(
            DEFAULT_DEPOT["lng"]
        )

    return result


def _records(
    value: Any,
) -> List[Dict[str, Any]]:
    if value is None:
        return []

    if isinstance(
        value,
        pd.DataFrame,
    ):
        return value.to_dict(
            "records"
        )

    if isinstance(
        value,
        Mapping,
    ):
        return [
            dict(value)
        ]

    result: List[
        Dict[str, Any]
    ] = []

    for item in value:
        if isinstance(
            item,
            pd.Series,
        ):
            result.append(
                item.to_dict()
            )
        elif isinstance(
            item,
            Mapping,
        ):
            result.append(
                dict(item)
            )
        else:
            result.append(
                dict(
                    vars(item)
                )
            )

    return result


def _customer_type(
    job: Mapping[str, Any],
) -> str:
    value = job.get(
        "customer_type"
    )
    return str(
        value or "Residential"
    )


def _routeable(
    job: Mapping[str, Any],
) -> bool:
    try:
        lat = float(
            job.get("lat")
        )
        lng = float(
            job.get("lng")
            if job.get("lng")
            is not None
            else job.get("lon")
        )
    except Exception:
        return False

    return (
        -90.0
        <= lat
        <= 90.0
        and
        -180.0
        <= lng
        <= 180.0
    )


def _crew_records(
    crews: int
    | Sequence[Mapping[str, Any]]
    | Sequence[Any]
    | None,
) -> List[Dict[str, Any]]:
    """
    Resolve the crew selection into route-ready dictionaries.

    If an integer is provided, use that many active crews when available.
    Missing crews become temporary Unassigned Crew records so routing can
    still proceed without forcing database setup first.
    """
    if crews is None:
        crew_count = 1
        explicit: List[
            Dict[str, Any]
        ] = []
    elif isinstance(
        crews,
        int,
    ):
        crew_count = max(
            1,
            int(crews),
        )
        explicit = []
    else:
        explicit = [
            dict(item)
            if isinstance(
                item,
                Mapping,
            )
            else {
                "id": getattr(
                    item,
                    "id",
                    None,
                ),
                "crew_name": getattr(
                    item,
                    "crew_name",
                    str(item),
                ),
            }
            for item in crews
        ]
        crew_count = max(
            1,
            len(explicit),
        )

    if explicit:
        return explicit

    try:
        crew_df = get_crews(
            active_only=True
        )
    except Exception:
        crew_df = pd.DataFrame()

    active_crews = (
        crew_df.to_dict(
            "records"
        )
        if crew_df is not None
        and not crew_df.empty
        else []
    )

    selected = active_crews[
        :crew_count
    ]

    while len(
        selected
    ) < crew_count:
        number = len(
            selected
        ) + 1

        selected.append(
            {
                "id": None,
                "crew_name": (
                    f"Crew {number}"
                ),
                "email": None,
                "phone": None,
            }
        )

    return selected


# ==========================================================
# DISPATCH SUMMARY
# ==========================================================

def dispatch_summary() -> Dict[str, Any]:
    """
    High-level CRM/Dispatch dashboard counts.
    """
    customers = list_customers()

    if (
        customers is None
        or customers.empty
    ):
        customer_count = 0
        estimated_revenue = 0.0
    else:
        customer_count = len(
            customers
        )

        price_column = None

        for candidate in (
            "quote",
            "price",
        ):
            if candidate in customers.columns:
                price_column = candidate
                break

        if price_column:
            estimated_revenue = float(
                pd.to_numeric(
                    customers[
                        price_column
                    ],
                    errors="coerce",
                )
                .fillna(0)
                .sum()
            )
        else:
            estimated_revenue = 0.0

    jobs = get_all_dispatch_jobs()

    completed = sum(
        1
        for job in jobs
        if _normalize_status(
            job.get("status")
        )
        == "completed"
    )

    remaining = sum(
        1
        for job in jobs
        if _normalize_status(
            job.get("status")
        )
        in ACTIVE_JOB_STATUSES
    )

    return {
        "customers": customer_count,
        "jobs_today": remaining,
        "completed": completed,
        "remaining": remaining,
        "estimated_revenue": (
            estimated_revenue
        ),
    }


# ==========================================================
# DATABASE / QUEUE HELPERS
# ==========================================================

def get_dispatch_queue(
    scheduled_date: date | datetime | str | None = None,
    customer_type: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Return every queued job eligible for Dispatch.

    IMPORTANT:
    scheduled_date is accepted for backward compatibility with existing
    app.py callers but is deliberately NOT used as an eligibility filter.

    A queued job scheduled for next week will still appear in today's
    Dispatch pool.

    customer_type is an optional view/filter only. When omitted or "All",
    residential and commercial customers route together normally.
    """
    try:
        df = get_queued_dispatch_jobs(
            customer_type=customer_type
        )
    except TypeError:
        # Compatibility with older database.py while transitioning files.
        df = list_dispatch_jobs(
            status="queued"
        )

    if (
        df is None
        or df.empty
    ):
        return []

    result = df.copy()

    if "status" in result.columns:
        statuses = (
            result[
                "status"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        result = result[
            statuses.eq(
                "queued"
            )
        ].copy()

    if (
        customer_type
        not in (
            None,
            "",
            "All",
        )
        and
        "customer_type"
        in result.columns
    ):
        result = result[
            result[
                "customer_type"
            ]
            == customer_type
        ].copy()

    return result.reset_index(
        drop=True
    ).to_dict(
        "records"
    )


def get_all_dispatch_jobs() -> List[Dict[str, Any]]:
    """
    Return every dispatch job, regardless of date/status.
    """
    df = list_dispatch_jobs()

    if (
        df is None
        or df.empty
    ):
        return []

    return df.to_dict(
        "records"
    )


def get_dispatch_pool_dataframe(
    customer_type: str | None = None,
) -> pd.DataFrame:
    """
    DataFrame form of the full queue for UI tables.
    """
    return pd.DataFrame(
        get_dispatch_queue(
            customer_type=(
                customer_type
            )
        )
    )


# ==========================================================
# QUEUE MANAGEMENT
# ==========================================================

def add_to_queue(
    job: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add local metadata around a queue record for UI usage.
    """
    result = dict(job)

    result[
        "added_at"
    ] = datetime.now().isoformat()

    result[
        "status_local"
    ] = "queued_ui"

    return result


def build_queue_from_customers(
    customers: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert customer records to in-memory dispatch jobs.
    """
    queue: List[
        Dict[str, Any]
    ] = []

    for customer in customers:

        queue.append(
            {
                "customer_id": (
                    customer.get(
                        "id"
                    )
                ),
                "name": (
                    customer.get(
                        "name"
                    )
                ),
                "account_name": (
                    customer.get(
                        "account_name"
                    )
                ),
                "customer_type": (
                    customer.get(
                        "customer_type",
                        "Residential",
                    )
                ),
                "address": (
                    customer.get(
                        "address"
                    )
                ),
                "lat": (
                    customer.get(
                        "lat"
                    )
                ),
                "lng": (
                    customer.get(
                        "lng"
                    )
                ),
                "service": (
                    customer.get(
                        "service"
                    )
                ),
                "status": "queued",
            }
        )

    return queue


def clear_queue() -> None:
    """
    Cancel every queued/in-progress dispatch job and release planned treatments.
    """
    for job in get_all_dispatch_jobs():

        if _normalize_status(
            job.get("status")
        ) not in {
            "queued",
            "in_progress",
        }:
            continue

        mark_job_cancelled(
            int(
                job[
                    "id"
                ]
            )
        )


# ==========================================================
# ROUTE BUILDING
# ==========================================================

def build_daily_route(
    scheduled_date: date | datetime | str | None = None,
    customer_type: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Build one optimized route from the full queued pool.

    scheduled_date is retained only for backward-compatible call signatures.
    """
    return build_route_from_queue(
        get_dispatch_queue(
            scheduled_date=(
                scheduled_date
            ),
            customer_type=(
                customer_type
            ),
        )
    )


def build_route_from_queue(
    queue: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build one optimized route from an in-memory queue.
    """
    if not queue:
        return []

    dispatch = build_dispatch_route(
        queue,
        _depot(),
        max_stops_per_route=max(
            1,
            len(queue),
        ),
    )

    return list(
        dispatch.get(
            "route",
            [],
        )
    )


def build_driver_manifest(
    route: Optional[
        List[Dict[str, Any]]
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Create a driver-friendly manifest.

    The manifest includes a Google Maps navigation link for every stop.
    When opened on the crew phone, the link uses the current phone location.
    """
    route = (
        route
        if route is not None
        else build_daily_route()
    )

    manifest: List[
        Dict[str, Any]
    ] = []

    for index, stop in enumerate(
        route,
        start=1,
    ):

        manifest.append(
            {
                "stop_number": (
                    stop.get(
                        "stop_number",
                        index,
                    )
                ),
                "job_id": (
                    stop.get(
                        "id"
                    )
                ),
                "customer_id": (
                    stop.get(
                        "customer_id"
                    )
                ),
                "name": (
                    stop.get(
                        "name"
                    )
                    or stop.get(
                        "customer_name"
                    )
                    or ""
                ),
                "account_name": (
                    stop.get(
                        "account_name"
                    )
                ),
                "customer_type": (
                    stop.get(
                        "customer_type",
                        "Residential",
                    )
                ),
                "address": (
                    stop.get(
                        "address"
                    )
                    or ""
                ),
                "service": (
                    stop.get(
                        "service"
                    )
                    or stop.get(
                        "treatment_name"
                    )
                    or ""
                ),
                "scheduled_date": (
                    stop.get(
                        "scheduled_date"
                    )
                ),
                "notes": (
                    stop.get(
                        "notes"
                    )
                    or ""
                ),
                "special_instructions": (
                    stop.get(
                        "special_instructions"
                    )
                    or ""
                ),
                "navigation_url": (
                    build_navigation_url(
                        stop
                    )
                ),
                "status": (
                    stop.get(
                        "status",
                        "queued",
                    )
                ),
            }
        )

    return manifest


def build_dispatch_summary(
    route: Optional[
        List[Dict[str, Any]]
    ] = None,
) -> Dict[str, Any]:
    """
    Route statistics for one route.
    """
    route = (
        route
        if route is not None
        else build_daily_route()
    )

    return summarize_route(
        route,
        depot=_depot(),
    )


def build_dispatch_dataframe(
    route: Optional[
        List[Dict[str, Any]]
    ] = None,
) -> pd.DataFrame:
    """
    Driver-friendly DataFrame.
    """
    route = (
        route
        if route is not None
        else build_daily_route()
    )

    return route_dataframe(
        route
    )


def build_multi_driver_routes(
    crews: int
    | Sequence[Mapping[str, Any]]
    | Sequence[Any] = 2,
    scheduled_date: date | datetime | str | None = None,
    customer_type: str | None = None,
    max_stops_per_route: int = 10,
) -> List[Dict[str, Any]]:
    """
    Split and optimize the full queued pool among multiple crews.

    IMPORTANT:
    scheduled_date is accepted for compatibility but does not filter queued
    jobs. A queued job from any scheduled date is eligible.

    Customer Type does not affect route optimization. customer_type is only an
    optional filter if the dispatcher explicitly asks for one category.
    """
    jobs = get_dispatch_queue(
        scheduled_date=(
            scheduled_date
        ),
        customer_type=(
            customer_type
        ),
    )

    if not jobs:
        return []

    crew_records = _crew_records(
        crews
    )

    dispatch = build_dispatch_route(
        jobs,
        _depot(),
        crews=crew_records,
        max_stops_per_route=(
            max_stops_per_route
        ),
    )

    results: List[
        Dict[str, Any]
    ] = []

    for route in dispatch.get(
        "routes",
        [],
    ):

        crew = route.get(
            "crew"
        ) or {}

        if isinstance(
            crew,
            Mapping,
        ):
            crew_id = crew.get(
                "id"
            )
            crew_name = (
                crew.get(
                    "crew_name"
                )
                or crew.get(
                    "name"
                )
                or f"Crew {route.get('route_number', '')}"
            )
        else:
            crew_id = None
            crew_name = str(
                crew
            )

        manifest = (
            build_driver_manifest(
                route.get(
                    "stops",
                    [],
                )
            )
        )

        results.append(
            {
                # Existing app.py expects crew['crew'].
                "crew": (
                    crew_name
                ),
                "crew_id": (
                    crew_id
                ),
                "route_number": (
                    route.get(
                        "route_number"
                    )
                ),
                "route": (
                    route.get(
                        "stops",
                        [],
                    )
                ),
                "manifest": (
                    manifest
                ),
                "summary": (
                    route.get(
                        "summary",
                        {},
                    )
                ),
                "google_maps": (
                    route.get(
                        "google_maps",
                        ""
                    )
                ),
            }
        )

    return results


# ==========================================================
# PERSISTENT MULTI-CREW DISPATCH CREATION
# ==========================================================

def create_multi_crew_dispatch(
    crews: int
    | Sequence[Mapping[str, Any]]
    | Sequence[Any],
    *,
    dispatch_date: date | datetime | str | None = None,
    customer_type: str | None = None,
    max_stops_per_route: int = 10,
) -> List[Dict[str, Any]]:
    """
    Optimize the queued pool, create one persistent dispatch manifest per crew,
    and assign each job to its manifest.

    This is the database-backed form of build_multi_driver_routes().
    """
    target_date = _normalize_date(
        dispatch_date
    )

    route_plans = (
        build_multi_driver_routes(
            crews=crews,
            scheduled_date=target_date,
            customer_type=customer_type,
            max_stops_per_route=(
                max_stops_per_route
            ),
        )
    )

    created: List[
        Dict[str, Any]
    ] = []

    for plan in route_plans:

        route_number = int(
            plan.get(
                "route_number"
            )
            or len(
                created
            )
            + 1
        )

        crew_id = plan.get(
            "crew_id"
        )

        dispatch_id = (
            create_dispatch(
                dispatch_date=(
                    target_date
                ),
                crew_id=(
                    crew_id
                ),
                route_number=(
                    route_number
                ),
                status="ready",
                notes=(
                    "Generated from queued "
                    "Dispatch pool"
                ),
            )
        )

        for stop_index, stop in enumerate(
            plan.get(
                "route",
                [],
            ),
            start=1,
        ):

            job_id = (
                stop.get(
                    "id"
                )
                or stop.get(
                    "job_id"
                )
            )

            if job_id is None:
                continue

            assign_job_to_dispatch(
                job_id=int(
                    job_id
                ),
                dispatch_id=int(
                    dispatch_id
                ),
                crew_id=(
                    int(
                        crew_id
                    )
                    if crew_id
                    is not None
                    else None
                ),
                route_number=(
                    route_number
                ),
                stop_number=(
                    stop_index
                ),
            )

        persisted = get_dispatch(
            int(
                dispatch_id
            )
        ) or {
            "id": dispatch_id
        }

        persisted[
            "manifest"
        ] = get_dispatch_jobs_for_manifest(
            int(
                dispatch_id
            )
        ).to_dict(
            "records"
        )

        persisted[
            "summary"
        ] = plan.get(
            "summary",
            {},
        )

        persisted[
            "google_maps"
        ] = plan.get(
            "google_maps",
            "",
        )

        created.append(
            persisted
        )

    return created


def get_saved_dispatches(
    dispatch_date: date | datetime | str | None = None,
) -> List[Dict[str, Any]]:
    """
    Return persisted dispatch manifests.
    """
    normalized = (
        _normalize_date(
            dispatch_date
        )
        if dispatch_date
        is not None
        else None
    )

    df = get_dispatches(
        dispatch_date=(
            normalized
        )
    )

    if (
        df is None
        or df.empty
    ):
        return []

    return df.to_dict(
        "records"
    )


def get_saved_dispatch_manifest(
    dispatch_id: int,
) -> List[Dict[str, Any]]:
    df = get_dispatch_jobs_for_manifest(
        int(
            dispatch_id
        )
    )

    if (
        df is None
        or df.empty
    ):
        return []

    manifest = df.to_dict(
        "records"
    )

    for stop in manifest:
        stop[
            "navigation_url"
        ] = build_navigation_url(
            stop
        )

    return manifest


def crew_dispatch_link(
    dispatch_id: int,
    base_url: str,
) -> str:
    """
    Build the private crew link used by email/text delivery.

    field_view.py will consume the `dispatch` query parameter.
    """
    dispatch = get_dispatch(
        int(
            dispatch_id
        )
    )

    if not dispatch:
        return ""

    token = dispatch.get(
        "dispatch_token"
    )

    if not token:
        return ""

    root = str(
        base_url
    ).rstrip(
        "/"
    )

    return (
        f"{root}/?dispatch={token}"
    )


def mark_dispatch_as_sent(
    dispatch_id: int,
) -> None:
    mark_dispatch_sent(
        int(
            dispatch_id
        )
    )


# ==========================================================
# DISPATCH STATUS
# ==========================================================

def mark_job_complete(
    job_id: int,
) -> None:
    """
    Complete one dispatch job.

    Prefer the richer database helper when available because it records the
    completion timestamp as well as the status.
    """
    try:
        mark_job_completed(
            int(
                job_id
            )
        )
    except Exception:
        update_dispatch_status(
            int(
                job_id
            ),
            "completed",
        )


def mark_job_in_progress(
    job_id: int,
) -> None:
    """
    Mark one stop as arrived / in progress.
    """
    try:
        mark_job_arrived(
            int(
                job_id
            )
        )
    except Exception:
        update_dispatch_status(
            int(
                job_id
            ),
            "in_progress",
        )


def release_linked_treatments(
    job_id: int,
) -> None:
    """
    Return unfinished planned treatments to Scheduling when a job is canceled.
    """
    execute(
        """
        UPDATE treatment_events
        SET dispatch_job_id=NULL
        WHERE dispatch_job_id=?
          AND status='planned'
        """,
        (
            int(
                job_id
            ),
        ),
    )


def mark_job_cancelled(
    job_id: int,
) -> None:
    release_linked_treatments(
        job_id
    )

    update_dispatch_status(
        int(
            job_id
        ),
        "cancelled",
    )


def requeue_job(
    job_id: int,
) -> None:
    """
    Return a dispatched job to the general Queue.
    """
    queue_dispatch_job(
        int(
            job_id
        )
    )


def cancel_entire_queue() -> None:
    """
    Cancel every queued/in-progress job across all scheduled dates.
    """
    for job in get_all_dispatch_jobs():

        if _normalize_status(
            job.get(
                "status"
            )
        ) not in {
            "queued",
            "in_progress",
        }:
            continue

        mark_job_cancelled(
            int(
                job[
                    "id"
                ]
            )
        )


def cancel_queue_for_date(
    scheduled_date: date | datetime | str | None = None,
) -> None:
    """
    Backward-compatible helper.

    Because queued jobs are no longer date-gated, this method intentionally
    cancels only jobs whose stored planning date matches the requested date.
    It is for administrative cleanup, not Dispatch eligibility.
    """
    selected_date = (
        _normalize_date(
            scheduled_date
        )
    )

    for job in get_all_dispatch_jobs():

        if _normalize_status(
            job.get(
                "status"
            )
        ) not in {
            "queued",
            "in_progress",
        }:
            continue

        job_date = job.get(
            "scheduled_date"
        )

        try:
            normalized_job_date = (
                pd.to_datetime(
                    job_date
                )
                .date()
                .isoformat()
            )
        except Exception:
            normalized_job_date = ""

        if normalized_job_date != selected_date:
            continue

        mark_job_cancelled(
            int(
                job[
                    "id"
                ]
            )
        )


def complete_entire_queue() -> None:
    """
    Complete every currently queued job.
    """
    for job in get_dispatch_queue():

        mark_job_complete(
            int(
                job[
                    "id"
                ]
            )
        )


def clear_saved_dispatch(
    dispatch_id: int,
    *,
    requeue_unfinished: bool = True,
) -> None:
    """
    Remove one persistent crew dispatch.

    Unfinished jobs return to the Queue by default.
    """
    clear_dispatch_manifest(
        int(
            dispatch_id
        ),
        requeue_unfinished=(
            requeue_unfinished
        ),
    )


# ==========================================================
# DRIVER VIEW
# ==========================================================

def get_driver_route_view(
    dispatch_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Driver-friendly route view.

    If dispatch_id is provided, return the saved crew manifest. Otherwise
    return the live optimized general Queue.
    """
    if dispatch_id is not None:
        route = get_saved_dispatch_manifest(
            int(
                dispatch_id
            )
        )
    else:
        route = build_daily_route()

    if not route:
        return []

    driver_view: List[
        Dict[str, Any]
    ] = []

    for index, stop in enumerate(
        route,
        start=1,
    ):

        driver_view.append(
            {
                "job_id": (
                    stop.get(
                        "id"
                    )
                    or stop.get(
                        "job_id"
                    )
                ),
                "stop": (
                    stop.get(
                        "stop_number",
                        index,
                    )
                ),
                "customer": (
                    stop.get(
                        "name"
                    )
                    or stop.get(
                        "customer_name"
                    )
                    or ""
                ),
                "account_name": (
                    stop.get(
                        "account_name"
                    )
                ),
                "customer_type": (
                    stop.get(
                        "customer_type",
                        "Residential",
                    )
                ),
                "address": (
                    stop.get(
                        "address",
                        "",
                    )
                ),
                "service": (
                    stop.get(
                        "service"
                    )
                    or stop.get(
                        "treatment_name"
                    )
                    or ""
                ),
                "scheduled_date": (
                    stop.get(
                        "scheduled_date"
                    )
                ),
                "notes": (
                    stop.get(
                        "notes",
                        "",
                    )
                ),
                "special_instructions": (
                    stop.get(
                        "special_instructions",
                        "",
                    )
                ),
                "status": (
                    stop.get(
                        "status",
                        "",
                    )
                ),
                "arrived_time": (
                    stop.get(
                        "arrived_time"
                    )
                ),
                "completed_time": (
                    stop.get(
                        "completed_time"
                    )
                ),
                "navigation_url": (
                    build_navigation_url(
                        stop
                    )
                ),
            }
        )

    return driver_view


def next_stop(
    route: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Return the next unfinished customer stop.
    """
    result = routing_next_stop(
        route
    )

    return (
        dict(result)
        if result
        else None
    )


def remaining_stops(
    route: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return unfinished customer stops.
    """
    return routing_remaining_stops(
        route
    )


# ==========================================================
# ANALYTICS
# ==========================================================

def dispatch_statistics() -> Dict[str, Any]:
    """
    Dashboard statistics across the whole dispatch system.
    """
    jobs = get_all_dispatch_jobs()

    queued = 0
    progress = 0
    dispatched = 0
    complete = 0
    cancelled = 0

    for job in jobs:

        status = _normalize_status(
            job.get(
                "status"
            )
        )

        if status == "queued":
            queued += 1
        elif status == "in_progress":
            progress += 1
        elif status == "dispatched":
            dispatched += 1
        elif status == "completed":
            complete += 1
        elif status in {
            "cancelled",
            "canceled",
        }:
            cancelled += 1

    summary = build_dispatch_summary()

    return {
        "queued": queued,
        "dispatched": dispatched,
        "in_progress": progress,
        "completed": complete,
        "cancelled": cancelled,
        "route": summary,
    }


def dispatch_dashboard(
    scheduled_date: date | datetime | str | None = None,
    customer_type: str | None = None,
) -> Dict[str, Any]:
    """
    Build the live Dispatch dashboard.

    scheduled_date is retained for compatibility and display only.
    The queue itself contains EVERY queued job regardless of scheduled date.
    """
    display_date = _normalize_date(
        scheduled_date
    )

    queued_jobs = get_dispatch_queue(
        scheduled_date=display_date,
        customer_type=customer_type,
    )

    all_jobs = get_all_dispatch_jobs()

    route = build_route_from_queue(
        queued_jobs
    )

    if route:
        summary = summarize_route(
            route,
            depot=_depot(),
        )
        manifest = build_driver_manifest(
            route
        )
        dataframe = route_dataframe(
            route
        )
    else:
        summary = {
            "stops": 0,
            "distance_miles": 0.0,
            "drive_minutes": 0.0,
            "service_minutes": 0.0,
            "total_minutes": 0.0,
            "google_maps": "",
        }
        manifest = []
        dataframe = pd.DataFrame()

    status_counts = {
        "queued": 0,
        "dispatched": 0,
        "in_progress": 0,
        "completed": 0,
        "cancelled": 0,
    }

    future_queued = 0

    for job in all_jobs:

        status = _normalize_status(
            job.get(
                "status"
            )
        )

        if status in status_counts:
            status_counts[
                status
            ] += 1

        if status != "queued":
            continue

        job_date = pd.to_datetime(
            job.get(
                "scheduled_date"
            ),
            errors="coerce",
        )

        if (
            not pd.isna(
                job_date
            )
            and job_date.date()
            > date.today()
        ):
            future_queued += 1

    statistics = {
        **status_counts,
        "selected_date": (
            display_date
        ),
        # Name retained so current app.py does not break. It now means the
        # total Dispatch-ready pool, not only jobs matching the selected date.
        "selected_date_active": len(
            queued_jobs
        ),
        "dispatch_ready": len(
            queued_jobs
        ),
        "future_active": (
            future_queued
        ),
        "future_queued_included": (
            future_queued
        ),
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
    "add_to_queue",
    "build_daily_route",
    "build_dispatch_dataframe",
    "build_dispatch_summary",
    "build_driver_manifest",
    "build_multi_driver_routes",
    "build_queue_from_customers",
    "build_route_from_queue",
    "cancel_entire_queue",
    "cancel_queue_for_date",
    "clear_queue",
    "clear_saved_dispatch",
    "complete_entire_queue",
    "create_multi_crew_dispatch",
    "crew_dispatch_link",
    "dispatch_dashboard",
    "dispatch_statistics",
    "dispatch_summary",
    "get_all_dispatch_jobs",
    "get_dispatch_pool_dataframe",
    "get_dispatch_queue",
    "get_driver_route_view",
    "get_saved_dispatch_manifest",
    "get_saved_dispatches",
    "mark_dispatch_as_sent",
    "mark_job_cancelled",
    "mark_job_complete",
    "mark_job_in_progress",
    "next_stop",
    "release_linked_treatments",
    "remaining_stops",
    "requeue_job",
]
