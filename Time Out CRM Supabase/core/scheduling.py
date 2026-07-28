"""
Scheduling Module (Time Out Lawncare CRM)

This module handles:
- Recurring service scheduling
- Due/overdue detection
- Weekly route planning
- Simple job generation from service intervals
- Integration layer for dispatch creation
"""

from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta

import pandas as pd

from data.database import (
    add_dispatch_job,
    dataframe,
    get_connection,
    get_customers,
    get_dispatch_jobs,
)

from core.treatment_manager import (
    get_treatment_events,
)


# =========================
# CONFIG DEFAULTS
# =========================
DEFAULT_SERVICE_INTERVAL_DAYS = {
    "Mowing": 14,
    "Full Service": 21,
    "Treatment": 30,
    None: 21
}


# =========================
# DATE HELPERS
# =========================
def parse_date(date_str: str) -> Optional[datetime]:
    if date_str is None or pd.isna(date_str):
        return None

    try:
        return pd.to_datetime(date_str).to_pydatetime()
    except Exception:
        return None


def days_since(date_str: str) -> int:
    dt = parse_date(date_str)
    if not dt:
        return 9999
    return (datetime.now() - dt).days


# =========================
# SERVICE DUE LOGIC
# =========================
def get_interval(service_type: str) -> int:
    return DEFAULT_SERVICE_INTERVAL_DAYS.get(service_type, 21)


def is_due(customer: Dict[str, Any]) -> bool:
    last = customer.get("last_service")
    interval = get_interval(customer.get("service"))

    if not last:
        return True

    return days_since(last) >= interval


def days_until_due(customer: Dict[str, Any]) -> int:
    last = customer.get("last_service")
    interval = get_interval(customer.get("service"))

    if not last:
        return 0

    return max(0, interval - days_since(last))


# =========================
# SCHEDULING ENGINE
# =========================
def get_due_customers() -> List[Dict[str, Any]]:
    df = get_customers()

    if df is None or df.empty:
        return []

    due = []
    for _, row in df.iterrows():
        c = row.to_dict()
        if is_due(c):
            due.append(c)

    return due
    
def due_date(customer: Dict[str, Any]) -> date:
    """Return the customer's next service date."""
    last = parse_date(customer.get("last_service"))

    if last is None:
        return datetime.now().date()

    interval = get_interval(customer.get("service"))
    return (last + timedelta(days=interval)).date()


def build_schedule_candidates(
    through_date: date | str | None = None,
) -> List[Dict[str, Any]]:
    """Build active customers due by the selected date."""
    target = pd.to_datetime(
        through_date or datetime.now().date()
    ).date()

    df = get_customers(active_only=True)

    if df is None or df.empty:
        return []

    queued = get_dispatch_jobs(status="queued")

    if queued is not None and not queued.empty:
        queued_ids = set(queued["customer_id"].tolist())
    else:
        queued_ids = set()

    candidates = []

    for customer in df.to_dict("records"):
        next_due = due_date(customer)

        if next_due > target:
            continue

        days_overdue = max(
            0,
            (target - next_due).days,
        )

        candidates.append(
            {
                **customer,
                "next_due": next_due.isoformat(),
                "days_overdue": days_overdue,
                "already_queued": (
                    customer.get("id") in queued_ids
                ),
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            item["already_queued"],
            -item["days_overdue"],
            item.get("name") or "",
        ),
    )


def queue_customers_for_date(
    customer_ids: List[int],
    scheduled_date: date | str,
) -> Dict[str, int]:
    """Queue selected customers while preventing duplicate active jobs."""
    scheduled = pd.to_datetime(
        scheduled_date
    ).date().isoformat()

    jobs = get_dispatch_jobs()
    active_ids = set()

    if jobs is not None and not jobs.empty:
        active_jobs = jobs[
            jobs["status"].isin(
                ["queued", "in_progress"]
            )
        ]

        active_ids = set(
            active_jobs["customer_id"].tolist()
        )

    created = 0
    skipped = 0

    unique_ids = dict.fromkeys(
        int(value) for value in customer_ids
    )

    for customer_id in unique_ids:
        if customer_id in active_ids:
            skipped += 1
            continue

        add_dispatch_job(
            customer_id=customer_id,
            scheduled_date=scheduled,
            notes="Scheduled from the due-customer queue",
        )

        active_ids.add(customer_id)
        created += 1

    return {
        "created": created,
        "skipped": skipped,
    }

def build_treatment_schedule_candidates(
    through_date: date | str | None = None,
) -> List[Dict[str, Any]]:
    """
    Return planned treatment visits due by the selected date.
    """
    target = pd.to_datetime(
        through_date or datetime.now().date()
    ).date()

    events = get_treatment_events()

    if events is None or events.empty:
        return []

    candidates = []

    for event in events.to_dict("records"):

        event_due = pd.to_datetime(
            event["due_date"]
        ).date()

        if event_due > target:
            continue

        dispatch_status = str(
            event.get("dispatch_status") or ""
        )

        already_queued = (
            event.get("dispatch_job_id") is not None
            and not pd.isna(
                event.get("dispatch_job_id")
            )
            and dispatch_status
            in {"queued", "in_progress"}
        )

        candidates.append(
            {
                "event_id": int(event["id"]),
                "customer_id": int(
                    event["customer_id"]
                ),
                "name": event["customer"],
                "address": event["address"],
                "square_feet": event["square_feet"],
                "treatment": event["treatment"],
                "event_type": event["event_type"],
                "due_date": event_due.isoformat(),
                "days_overdue": max(
                    0,
                    (target - event_due).days,
                ),
                "override_reason": (
                    event["override_reason"] or ""
                ),
                "already_queued": already_queued,
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            item["already_queued"],
            -item["days_overdue"],
            item["name"],
            item["treatment"],
        ),
    )


def queue_treatment_events_for_date(
    event_ids: List[int],
    scheduled_date: date | str,
) -> Dict[str, int]:
    """
    Group selected treatments by customer and create one
    dispatch stop per customer.
    """
    if not event_ids:
        return {
            "jobs_created": 0,
            "events_linked": 0,
            "skipped": 0,
        }

    scheduled = pd.to_datetime(
        scheduled_date
    ).date().isoformat()

    unique_ids = list(
        dict.fromkeys(
            int(value)
            for value in event_ids
        )
    )

    placeholders = ",".join(
        "?"
        for _ in unique_ids
    )

    events = dataframe(
        f"""
        SELECT
            te.id,
            te.customer_id,
            te.dispatch_job_id,
            dj.status AS dispatch_status,
            td.name AS treatment
        FROM treatment_events te
        INNER JOIN treatment_definitions td
            ON td.id = te.treatment_id
        LEFT JOIN dispatch_jobs dj
            ON dj.id = te.dispatch_job_id
        WHERE te.id IN ({placeholders})
          AND te.status='planned'
        ORDER BY
            te.customer_id,
            td.name
        """,
        tuple(unique_ids),
    )

    if events.empty:
        return {
            "jobs_created": 0,
            "events_linked": 0,
            "skipped": len(unique_ids),
        }

    jobs_created = 0
    events_linked = 0
    skipped = 0

    conn = get_connection()

    try:
        cursor = conn.cursor()

        for customer_id, customer_events in events.groupby(
            "customer_id"
        ):

            ready_events = customer_events[
                ~customer_events[
                    "dispatch_status"
                ].fillna("").isin(
                    ["queued", "in_progress"]
                )
            ]

            skipped += (
                len(customer_events)
                - len(ready_events)
            )

            if ready_events.empty:
                continue

            cursor.execute(
                """
                SELECT id
                FROM dispatch_jobs
                WHERE customer_id=?
                  AND scheduled_date=?
                  AND status IN (
                      'queued',
                      'in_progress'
                  )
                ORDER BY id
                LIMIT 1
                """,
                (
                    int(customer_id),
                    scheduled,
                ),
            )

            existing_job = cursor.fetchone()

            if existing_job is None:

                cursor.execute(
                    """
                    INSERT INTO dispatch_jobs (
                        customer_id,
                        treatment_name,
                        scheduled_date,
                        notes,
                        status
                    )
                    VALUES (?, '', ?, '', 'queued')
                    """,
                    (
                        int(customer_id),
                        scheduled,
                    ),
                )

                dispatch_job_id = (
                    cursor.lastrowid
                )

                jobs_created += 1

            else:

                dispatch_job_id = int(
                    existing_job["id"]
                )

            for event_id in ready_events["id"]:

                cursor.execute(
                    """
                    UPDATE treatment_events
                    SET dispatch_job_id=?
                    WHERE id=?
                    """,
                    (
                        dispatch_job_id,
                        int(event_id),
                    ),
                )

                events_linked += 1

            cursor.execute(
                """
                SELECT GROUP_CONCAT(
                    td.name,
                    ', '
                )
                FROM treatment_events te
                INNER JOIN treatment_definitions td
                    ON td.id=te.treatment_id
                WHERE te.dispatch_job_id=?
                  AND te.status='planned'
                """,
                (dispatch_job_id,),
            )

            treatment_names = (
                cursor.fetchone()[0] or ""
            )

            cursor.execute(
                """
                UPDATE dispatch_jobs
                SET
                    treatment_name=?,
                    notes=?
                WHERE id=?
                """,
                (
                    treatment_names,
                    (
                        "Treatment visit: "
                        f"{treatment_names}"
                    ),
                    dispatch_job_id,
                ),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "jobs_created": jobs_created,
        "events_linked": events_linked,
        "skipped": skipped,
    }


def get_overdue_customers() -> List[Dict[str, Any]]:
    df = get_customers()

    if df is None or df.empty:
        return []

    overdue = []
    for _, row in df.iterrows():
        c = row.to_dict()
        last = c.get("last_service")

        if not last:
            continue

        interval = get_interval(c.get("service"))
        if days_since(last) > interval:
            overdue.append(c)

    return overdue


# =========================
# DISPATCH GENERATION
# =========================
def generate_dispatch_for_due(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Creates dispatch jobs for due customers.
    """
    due = get_due_customers()[:limit]

    created = []

    for c in due:
        job_id = add_dispatch_job(
            customer_id=c["id"],
            scheduled_date=datetime.now().date().isoformat(),
            notes="Auto-generated from scheduling engine"
        )

        created.append({
            "customer_id": c["id"],
            "name": c.get("name"),
            "address": c.get("address"),
            "service": c.get("service"),
        })

    return created


def generate_weekly_schedule(days_ahead: int = 7) -> Dict[str, List[Dict[str, Any]]]:
    """
    Splits due jobs into a 7-day plan.
    """
    due = get_due_customers()

    schedule = {}


    for i in range(days_ahead):
        date = (datetime.now() + timedelta(days=i)).date().isoformat()
        schedule[date] = []

    idx = 0
    dates = list(schedule.keys())

    for c in due:
        date = dates[idx % len(dates)]
        schedule[date].append(c)
        idx += 1

    return schedule


# =========================
# PRIORITY SCORING
# =========================
def priority_score(customer: Dict[str, Any]) -> float:
    """
    Higher score = more urgent.
    """
    last = customer.get("last_service")
    interval = get_interval(customer.get("service"))

    if not last:
        return 100.0

    overdue_days = days_since(last) - interval

    if overdue_days <= 0:
        return 0.0

    base = overdue_days * 2

    # boost for full service customers
    if customer.get("service") == "Full Service":
        base *= 1.2

    return round(base, 2)


def sort_by_priority(customers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(customers, key=priority_score, reverse=True)


# =========================
# ROUTE PRE-SCHEDULING
# =========================
def build_priority_route_candidates(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Pre-sorted list for dispatch optimization.
    """
    due = get_due_customers()
    sorted_due = sort_by_priority(due)

    return sorted_due[:limit]


# =========================
# UTILITIES
# =========================
def summarize_schedule(schedule: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    total = sum(len(v) for v in schedule.values())

    busiest_day = None
    max_jobs = 0

    for day, jobs in schedule.items():
        if len(jobs) > max_jobs:
            busiest_day = day
            max_jobs = len(jobs)

    return {
        "total_jobs": total,
        "busiest_day": busiest_day,
        "max_jobs": max_jobs
    }