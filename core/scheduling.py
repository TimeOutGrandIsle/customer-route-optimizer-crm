"""
core/scheduling.py

Scheduling Module for Time Out Lawncare CRM.

Responsibilities:
- Recurring service scheduling
- Due / overdue detection
- Weekly planning
- Treatment-event scheduling
- Queue creation for Dispatch
- Dispatch-eligibility helpers

Important business rule:
A dispatch job whose status is "queued" is eligible for Dispatch regardless of
its scheduled_date. scheduled_date is planning information; it is not a gate
that hides an already-queued job from today's Dispatch pool.

Customer Type is descriptive/filtering information only. It does not affect
scheduling eligibility or route optimization.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from data.database import (
    add_dispatch_job,
    dataframe,
    get_connection,
    get_customers,
    get_dispatch_jobs,
)

from core.treatment_manager import get_treatment_events


# =========================================================
# CONFIG DEFAULTS
# =========================================================

DEFAULT_SERVICE_INTERVAL_DAYS: Dict[Optional[str], int] = {
    "Mowing": 14,
    "Full Service": 21,
    "Treatment": 30,
    None: 21,
}

DEFAULT_SERVICE_INTERVAL = 21

ACTIVE_DISPATCH_STATUSES = {
    "queued",
    "in_progress",
    "dispatched",
}

DISPATCH_READY_STATUSES = {
    "queued",
}

CLOSED_DISPATCH_STATUSES = {
    "completed",
    "cancelled",
    "canceled",
}


# =========================================================
# NORMALIZATION HELPERS
# =========================================================

def normalize_status(value: Any) -> str:
    """
    Normalize a status value for consistent comparisons.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip().lower()


def normalize_date(
    value: date | datetime | str | None,
) -> Optional[date]:
    """
    Convert a date-like value to datetime.date.

    Invalid or empty values return None rather than raising.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def iso_date(
    value: date | datetime | str | None,
    default: Optional[date] = None,
) -> Optional[str]:
    """
    Normalize a date-like value to ISO YYYY-MM-DD.
    """
    normalized = normalize_date(value)

    if normalized is None:
        normalized = default

    if normalized is None:
        return None

    return normalized.isoformat()


# =========================================================
# DATE HELPERS
# =========================================================

def parse_date(date_str: Any) -> Optional[datetime]:
    """
    Parse a date-like value into a datetime.
    """
    if date_str is None:
        return None

    try:
        if pd.isna(date_str):
            return None
    except Exception:
        pass

    if isinstance(date_str, datetime):
        return date_str

    if isinstance(date_str, date):
        return datetime.combine(
            date_str,
            datetime.min.time(),
        )

    try:
        return pd.to_datetime(date_str).to_pydatetime()
    except Exception:
        return None


def days_since(
    date_str: Any,
    *,
    as_of: date | datetime | None = None,
) -> int:
    """
    Return whole days since date_str.

    Missing/invalid dates return 9999 so legacy "never serviced" customers
    remain strongly due.
    """
    dt = parse_date(date_str)

    if not dt:
        return 9999

    if as_of is None:
        reference = datetime.now()
    elif isinstance(as_of, datetime):
        reference = as_of
    else:
        reference = datetime.combine(
            as_of,
            datetime.min.time(),
        )

    return (reference - dt).days


# =========================================================
# SERVICE DUE LOGIC
# =========================================================

def get_interval(service_type: Optional[str]) -> int:
    """
    Return the recurrence interval for a service type.
    """
    return int(
        DEFAULT_SERVICE_INTERVAL_DAYS.get(
            service_type,
            DEFAULT_SERVICE_INTERVAL,
        )
    )


def is_due(
    customer: Dict[str, Any],
    *,
    as_of: date | datetime | None = None,
) -> bool:
    """
    Return True if a customer is due as of the selected date.
    """
    last = customer.get("last_service")
    interval = get_interval(
        customer.get("service")
    )

    if not last:
        return True

    return days_since(
        last,
        as_of=as_of,
    ) >= interval


def days_until_due(
    customer: Dict[str, Any],
    *,
    as_of: date | datetime | None = None,
) -> int:
    """
    Number of days until service is due.

    Overdue customers return zero.
    """
    last = customer.get("last_service")
    interval = get_interval(
        customer.get("service")
    )

    if not last:
        return 0

    return max(
        0,
        interval - days_since(
            last,
            as_of=as_of,
        ),
    )


def due_date(
    customer: Dict[str, Any],
) -> date:
    """
    Return the customer's next service due date.
    """
    last = parse_date(
        customer.get("last_service")
    )

    if last is None:
        return datetime.now().date()

    interval = get_interval(
        customer.get("service")
    )

    return (
        last
        + timedelta(days=interval)
    ).date()


# =========================================================
# DISPATCH QUEUE RULES
# =========================================================

def is_dispatch_ready_job(
    job: Dict[str, Any],
) -> bool:
    """
    Return True if a dispatch job belongs in the Dispatch-ready pool.

    scheduled_date is deliberately ignored.

    This is the central rule requested for Time Out Lawncare:
    once a job is queued, it remains eligible for Dispatch until its status
    changes out of "queued".
    """
    return (
        normalize_status(
            job.get("status")
        )
        in DISPATCH_READY_STATUSES
    )


def get_dispatch_ready_jobs() -> pd.DataFrame:
    """
    Return every queued dispatch job, regardless of scheduled date.

    The Dispatch UI should use this function (or equivalent database logic)
    instead of filtering queued jobs to CURRENT_DATE.
    """
    jobs = get_dispatch_jobs(
        status="queued"
    )

    if jobs is None:
        return pd.DataFrame()

    if jobs.empty:
        return jobs.copy()

    result = jobs.copy()

    if "status" in result.columns:
        result = result[
            result["status"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .eq("queued")
        ].copy()

    return result.reset_index(drop=True)


def get_active_dispatch_jobs() -> pd.DataFrame:
    """
    Return all jobs that are still operationally active.

    This is used primarily for duplicate prevention.
    """
    jobs = get_dispatch_jobs()

    if jobs is None or jobs.empty:
        return pd.DataFrame(
            columns=[] if jobs is None else jobs.columns
        )

    if "status" not in jobs.columns:
        return jobs.copy()

    statuses = (
        jobs["status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return jobs[
        statuses.isin(
            ACTIVE_DISPATCH_STATUSES
        )
    ].copy()


def queued_customer_ids() -> set[int]:
    """
    Customer IDs with currently queued jobs, regardless of scheduled date.
    """
    queued = get_dispatch_ready_jobs()

    if (
        queued is None
        or queued.empty
        or "customer_id" not in queued.columns
    ):
        return set()

    return {
        int(value)
        for value in queued[
            "customer_id"
        ].dropna().tolist()
    }


# =========================================================
# SCHEDULING ENGINE
# =========================================================

def get_due_customers() -> List[Dict[str, Any]]:
    """
    Return active and inactive customers currently due.

    This preserves the older behavior of get_customers() with no active-only
    filter. UI candidate builders below use active_only=True.
    """
    df = get_customers()

    if df is None or df.empty:
        return []

    due: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        customer = row.to_dict()

        if is_due(customer):
            due.append(customer)

    return due


def build_schedule_candidates(
    through_date: date | str | None = None,
) -> List[Dict[str, Any]]:
    """
    Build active customers due by the selected planning date.

    A customer already queued is still included and flagged already_queued.
    The queued flag does not depend on the queued job's scheduled_date.
    """
    target = normalize_date(
        through_date
        or datetime.now().date()
    )

    if target is None:
        target = datetime.now().date()

    df = get_customers(
        active_only=True
    )

    if df is None or df.empty:
        return []

    queued_ids = queued_customer_ids()

    candidates: List[Dict[str, Any]] = []

    for customer in df.to_dict(
        "records"
    ):
        next_due = due_date(
            customer
        )

        if next_due > target:
            continue

        days_overdue = max(
            0,
            (target - next_due).days,
        )

        customer_id = customer.get(
            "id"
        )

        candidates.append(
            {
                **customer,
                "next_due": (
                    next_due.isoformat()
                ),
                "days_overdue": (
                    days_overdue
                ),
                "already_queued": (
                    customer_id
                    in queued_ids
                ),
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            item[
                "already_queued"
            ],
            -item[
                "days_overdue"
            ],
            item.get(
                "name"
            )
            or "",
        ),
    )


def queue_customers_for_date(
    customer_ids: List[int],
    scheduled_date: date | str,
) -> Dict[str, int]:
    """
    Queue selected customers while preventing duplicate active jobs.

    scheduled_date is stored for planning/reporting, but once created the job
    is Dispatch-ready immediately because its status defaults to "queued".
    """
    scheduled = iso_date(
        scheduled_date
    )

    if scheduled is None:
        raise ValueError(
            "scheduled_date is required."
        )

    active_jobs = (
        get_active_dispatch_jobs()
    )

    active_ids: set[int] = set()

    if (
        active_jobs is not None
        and not active_jobs.empty
        and "customer_id"
        in active_jobs.columns
    ):
        active_ids = {
            int(value)
            for value in active_jobs[
                "customer_id"
            ].dropna().tolist()
        }

    created = 0
    skipped = 0

    unique_ids = list(
        dict.fromkeys(
            int(value)
            for value
            in customer_ids
        )
    )

    for customer_id in unique_ids:

        if customer_id in active_ids:
            skipped += 1
            continue

        add_dispatch_job(
            customer_id=customer_id,
            scheduled_date=scheduled,
            notes=(
                "Scheduled from the "
                "due-customer queue"
            ),
        )

        active_ids.add(
            customer_id
        )

        created += 1

    return {
        "created": created,
        "skipped": skipped,
    }


# =========================================================
# TREATMENT SCHEDULING
# =========================================================

def build_treatment_schedule_candidates(
    through_date: date | str | None = None,
) -> List[Dict[str, Any]]:
    """
    Return planned treatment visits due by the selected date.

    already_queued is status-based and therefore independent of the queued
    job's scheduled_date.
    """
    target = normalize_date(
        through_date
        or datetime.now().date()
    )

    if target is None:
        target = datetime.now().date()

    events = get_treatment_events()

    if (
        events is None
        or events.empty
    ):
        return []

    candidates: List[
        Dict[str, Any]
    ] = []

    for event in events.to_dict(
        "records"
    ):

        event_due = normalize_date(
            event.get(
                "due_date"
            )
        )

        if event_due is None:
            continue

        if event_due > target:
            continue

        dispatch_status = (
            normalize_status(
                event.get(
                    "dispatch_status"
                )
            )
        )

        dispatch_job_id = (
            event.get(
                "dispatch_job_id"
            )
        )

        has_dispatch_job = (
            dispatch_job_id
            is not None
        )

        if has_dispatch_job:
            try:
                has_dispatch_job = not pd.isna(
                    dispatch_job_id
                )
            except Exception:
                pass

        already_queued = (
            has_dispatch_job
            and dispatch_status
            in ACTIVE_DISPATCH_STATUSES
        )

        candidates.append(
            {
                "event_id": int(
                    event[
                        "id"
                    ]
                ),
                "customer_id": int(
                    event[
                        "customer_id"
                    ]
                ),
                "name": event.get(
                    "customer"
                )
                or event.get(
                    "name"
                )
                or "",
                "address": event.get(
                    "address"
                )
                or "",
                "square_feet": (
                    event.get(
                        "square_feet"
                    )
                ),
                "treatment": (
                    event.get(
                        "treatment"
                    )
                    or ""
                ),
                "event_type": (
                    event.get(
                        "event_type"
                    )
                    or ""
                ),
                "due_date": (
                    event_due.isoformat()
                ),
                "days_overdue": max(
                    0,
                    (
                        target
                        - event_due
                    ).days,
                ),
                "override_reason": (
                    event.get(
                        "override_reason"
                    )
                    or ""
                ),
                "already_queued": (
                    already_queued
                ),
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            item[
                "already_queued"
            ],
            -item[
                "days_overdue"
            ],
            item[
                "name"
            ],
            item[
                "treatment"
            ],
        ),
    )


def queue_treatment_events_for_date(
    event_ids: List[int],
    scheduled_date: date | str,
) -> Dict[str, int]:
    """
    Group selected treatment events by customer and create one dispatch stop
    per customer.

    Duplicate prevention is intentionally broader than scheduled_date:
    if the customer already has an active queued/in-progress/dispatched job,
    the selected treatment events are linked to that active job rather than
    creating a second dispatch stop.

    This keeps one physical customer visit represented by one Dispatch stop.
    """
    if not event_ids:
        return {
            "jobs_created": 0,
            "events_linked": 0,
            "skipped": 0,
        }

    scheduled = iso_date(
        scheduled_date
    )

    if scheduled is None:
        raise ValueError(
            "scheduled_date is required."
        )

    unique_ids = list(
        dict.fromkeys(
            int(value)
            for value
            in event_ids
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
            dj.status
                AS dispatch_status,
            td.name
                AS treatment
        FROM treatment_events te
        INNER JOIN treatment_definitions td
            ON td.id=te.treatment_id
        LEFT JOIN dispatch_jobs dj
            ON dj.id=te.dispatch_job_id
        WHERE te.id IN (
            {placeholders}
        )
          AND te.status='planned'
        ORDER BY
            te.customer_id,
            td.name
        """,
        tuple(
            unique_ids
        ),
    )

    if events.empty:
        return {
            "jobs_created": 0,
            "events_linked": 0,
            "skipped": len(
                unique_ids
            ),
        }

    jobs_created = 0
    events_linked = 0
    skipped = 0

    conn = get_connection()

    try:
        cursor = conn.cursor()

        for (
            customer_id,
            customer_events,
        ) in events.groupby(
            "customer_id"
        ):

            customer_events = (
                customer_events.copy()
            )

            active_mask = (
                customer_events[
                    "dispatch_status"
                ]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.lower()
                .isin(
                    ACTIVE_DISPATCH_STATUSES
                )
            )

            ready_events = (
                customer_events[
                    ~active_mask
                ]
            )

            skipped += int(
                active_mask.sum()
            )

            if ready_events.empty:
                continue

            # IMPORTANT:
            # Search for ANY active dispatch job for this customer.
            # Do not require matching scheduled_date.
            cursor.execute(
                """
                SELECT id
                FROM dispatch_jobs
                WHERE customer_id=?
                  AND LOWER(
                      COALESCE(
                          status,
                          ''
                      )
                  ) IN (
                      'queued',
                      'in_progress',
                      'dispatched'
                  )
                ORDER BY
                    CASE
                        WHEN LOWER(
                            COALESCE(
                                status,
                                ''
                            )
                        )='queued'
                        THEN 0
                        ELSE 1
                    END,
                    id
                LIMIT 1
                """,
                (
                    int(
                        customer_id
                    ),
                ),
            )

            existing_job = (
                cursor.fetchone()
            )

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
                    VALUES (
                        ?,
                        '',
                        ?,
                        '',
                        'queued'
                    )
                    """,
                    (
                        int(
                            customer_id
                        ),
                        scheduled,
                    ),
                )

                dispatch_job_id = (
                    cursor.lastrowid
                )

                jobs_created += 1

            else:

                try:
                    dispatch_job_id = int(
                        existing_job[
                            "id"
                        ]
                    )
                except (
                    TypeError,
                    KeyError,
                ):
                    dispatch_job_id = int(
                        existing_job[
                            0
                        ]
                    )

            for event_id in ready_events[
                "id"
            ]:

                cursor.execute(
                    """
                    UPDATE treatment_events
                    SET dispatch_job_id=?
                    WHERE id=?
                    """,
                    (
                        dispatch_job_id,
                        int(
                            event_id
                        ),
                    ),
                )

                events_linked += 1

            cursor.execute(
                """
                SELECT STRING_AGG(
                    td.name,
                    ', '
                    ORDER BY td.name
                )
                FROM treatment_events te
                INNER JOIN treatment_definitions td
                    ON td.id=te.treatment_id
                WHERE te.dispatch_job_id=?
                  AND te.status='planned'
                """,
                (
                    dispatch_job_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                treatment_names = ""
            else:
                try:
                    treatment_names = (
                        row[0]
                        or ""
                    )
                except Exception:
                    treatment_names = ""

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
        "jobs_created": (
            jobs_created
        ),
        "events_linked": (
            events_linked
        ),
        "skipped": skipped,
    }


# =========================================================
# OVERDUE
# =========================================================

def get_overdue_customers() -> List[Dict[str, Any]]:
    """
    Return customers whose service interval has been exceeded.
    """
    df = get_customers()

    if (
        df is None
        or df.empty
    ):
        return []

    overdue: List[
        Dict[str, Any]
    ] = []

    for _, row in df.iterrows():
        customer = (
            row.to_dict()
        )

        last = customer.get(
            "last_service"
        )

        if not last:
            continue

        interval = get_interval(
            customer.get(
                "service"
            )
        )

        if (
            days_since(last)
            > interval
        ):
            overdue.append(
                customer
            )

    return overdue


# =========================================================
# DISPATCH GENERATION
# =========================================================

def generate_dispatch_for_due(
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Create queued dispatch jobs for due customers.

    Existing active jobs are not duplicated.
    """
    limit = max(
        0,
        int(limit),
    )

    due = get_due_customers()

    active = (
        get_active_dispatch_jobs()
    )

    active_ids: set[int] = set()

    if (
        active is not None
        and not active.empty
        and "customer_id"
        in active.columns
    ):
        active_ids = {
            int(value)
            for value in active[
                "customer_id"
            ].dropna().tolist()
        }

    created: List[
        Dict[str, Any]
    ] = []

    for customer in due:

        if (
            len(created)
            >= limit
        ):
            break

        customer_id = int(
            customer[
                "id"
            ]
        )

        if customer_id in active_ids:
            continue

        add_dispatch_job(
            customer_id=(
                customer_id
            ),
            scheduled_date=(
                datetime.now()
                .date()
                .isoformat()
            ),
            notes=(
                "Auto-generated "
                "from scheduling engine"
            ),
        )

        active_ids.add(
            customer_id
        )

        created.append(
            {
                "customer_id": (
                    customer_id
                ),
                "name": (
                    customer.get(
                        "name"
                    )
                ),
                "address": (
                    customer.get(
                        "address"
                    )
                ),
                "service": (
                    customer.get(
                        "service"
                    )
                ),
                "customer_type": (
                    customer.get(
                        "customer_type"
                    )
                ),
            }
        )

    return created


def generate_weekly_schedule(
    days_ahead: int = 7,
) -> Dict[
    str,
    List[Dict[str, Any]],
]:
    """
    Split due jobs evenly across a simple multi-day planning window.

    This is a planning helper only. It does not create Dispatch jobs.
    """
    days_ahead = max(
        1,
        int(days_ahead),
    )

    due = get_due_customers()

    schedule: Dict[
        str,
        List[Dict[str, Any]],
    ] = {}

    for offset in range(
        days_ahead
    ):
        day = (
            datetime.now()
            + timedelta(
                days=offset
            )
        ).date().isoformat()

        schedule[
            day
        ] = []

    dates = list(
        schedule.keys()
    )

    for index, customer in enumerate(
        due
    ):
        day = dates[
            index
            % len(dates)
        ]

        schedule[
            day
        ].append(
            customer
        )

    return schedule


# =========================================================
# PRIORITY SCORING
# =========================================================

def priority_score(
    customer: Dict[str, Any],
) -> float:
    """
    Higher score = more urgent.

    Customer Type is deliberately not part of the score.
    """
    last = customer.get(
        "last_service"
    )

    interval = get_interval(
        customer.get(
            "service"
        )
    )

    if not last:
        return 100.0

    overdue_days = (
        days_since(last)
        - interval
    )

    if overdue_days <= 0:
        return 0.0

    base = (
        overdue_days
        * 2
    )

    if (
        customer.get(
            "service"
        )
        == "Full Service"
    ):
        base *= 1.2

    return round(
        base,
        2,
    )


def sort_by_priority(
    customers: List[
        Dict[str, Any]
    ],
) -> List[Dict[str, Any]]:
    """
    Sort highest-priority customers first.
    """
    return sorted(
        customers,
        key=priority_score,
        reverse=True,
    )


# =========================================================
# ROUTE PRE-SCHEDULING
# =========================================================

def build_priority_route_candidates(
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Pre-sorted due-customer list for route planning.

    This function does not filter by Customer Type.
    """
    limit = max(
        0,
        int(limit),
    )

    due = (
        get_due_customers()
    )

    sorted_due = (
        sort_by_priority(
            due
        )
    )

    return sorted_due[
        :limit
    ]


# =========================================================
# UTILITIES
# =========================================================

def summarize_schedule(
    schedule: Dict[
        str,
        List[Dict[str, Any]],
    ],
) -> Dict[str, Any]:
    """
    Summarize a generated planning schedule.
    """
    total = sum(
        len(jobs)
        for jobs
        in schedule.values()
    )

    busiest_day = None
    max_jobs = 0

    for day, jobs in schedule.items():

        if len(jobs) > max_jobs:
            busiest_day = day
            max_jobs = len(
                jobs
            )

    return {
        "total_jobs": total,
        "busiest_day": (
            busiest_day
        ),
        "max_jobs": (
            max_jobs
        ),
    }


__all__ = [
    "ACTIVE_DISPATCH_STATUSES",
    "CLOSED_DISPATCH_STATUSES",
    "DEFAULT_SERVICE_INTERVAL_DAYS",
    "DISPATCH_READY_STATUSES",
    "build_priority_route_candidates",
    "build_schedule_candidates",
    "build_treatment_schedule_candidates",
    "days_since",
    "days_until_due",
    "due_date",
    "generate_dispatch_for_due",
    "generate_weekly_schedule",
    "get_active_dispatch_jobs",
    "get_dispatch_ready_jobs",
    "get_due_customers",
    "get_interval",
    "get_overdue_customers",
    "is_dispatch_ready_job",
    "is_due",
    "iso_date",
    "normalize_date",
    "normalize_status",
    "parse_date",
    "priority_score",
    "queue_customers_for_date",
    "queue_treatment_events_for_date",
    "queued_customer_ids",
    "sort_by_priority",
    "summarize_schedule",
]
