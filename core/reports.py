"""
Reports Module (Time Out Lawncare CRM)

This module handles:
- Revenue and service reporting
- Customer activity summaries
- Dispatch performance analytics
- Seasonal workload reporting
- CSV export helpers for business tracking
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

import pandas as pd

from data.database import (
    get_customers,
    get_dispatch_jobs,
    get_service_history
)


# =========================
# BASIC KPI REPORTING
# =========================
def customer_kpis() -> Dict[str, Any]:
    customers = get_customers()

    if customers is None or customers.empty:
        return {
            "total_customers": 0,
            "active_customers": 0,
            "inactive_customers": 0
        }

    total = len(customers)

    active = customers[customers["last_service"].notna()] if "last_service" in customers else customers
    inactive = customers[customers["last_service"].isna()] if "last_service" in customers else customers.iloc[0:0]

    return {
        "total_customers": total,
        "active_customers": len(active),
        "inactive_customers": len(inactive)
    }


# =========================
# SERVICE REPORTING
# =========================
def service_activity_report(days: int = 30) -> Dict[str, Any]:
    history = get_service_history()

    if history is None or history.empty:
        return {
            "total_services": 0,
            "recent_services": 0,
            "top_service_type": None
        }

    history["service_date"] = pd.to_datetime(history["service_date"], errors="coerce")

    cutoff = datetime.now() - timedelta(days=days)

    recent = history[history["service_date"] >= cutoff]

    top_service = None
    if "service_type" in history.columns and not history.empty:
        top_service = history["service_type"].value_counts().idxmax()

    return {
        "total_services": len(history),
        "recent_services": len(recent),
        "top_service_type": top_service
    }


# =========================
# DISPATCH REPORTING
# =========================
def dispatch_performance_report() -> Dict[str, Any]:
    jobs = get_dispatch_jobs()

    if jobs is None or jobs.empty:
        return {
            "total_jobs": 0,
            "completed": 0,
            "cancelled": 0,
            "queued": 0,
            "completion_rate": 0.0
        }

    status_counts = jobs["status"].value_counts().to_dict()

    total = len(jobs)
    completed = status_counts.get("completed", 0)
    cancelled = status_counts.get("cancelled", 0)
    queued = status_counts.get("queued", 0)

    completion_rate = (completed / total) * 100 if total else 0

    return {
        "total_jobs": total,
        "completed": completed,
        "cancelled": cancelled,
        "queued": queued,
        "completion_rate": round(completion_rate, 2)
    }


# =========================
# CUSTOMER SEGMENTATION
# =========================
def customer_segmentation() -> Dict[str, Any]:
    customers = get_customers()

    if customers is None or customers.empty:
        return {}

    segments = {
        "high_priority": 0,
        "overdue": 0,
        "no_service": 0
    }

    now = datetime.now()

    for _, row in customers.iterrows():
        last = row.get("last_service")

        if not last:
            segments["no_service"] += 1
            continue

        try:
            last_dt = pd.to_datetime(last, errors="coerce")
            days = (now - last_dt).days if pd.notna(last_dt) else 9999

            if days > 30:
                segments["overdue"] += 1
            elif days > 14:
                segments["high_priority"] += 1

        except Exception:
            segments["no_service"] += 1

    return segments


# =========================
# REVENUE ESTIMATION (BASIC MODEL)
# =========================
def estimate_revenue(avg_service_price: float = 55.0) -> Dict[str, Any]:
    history = get_service_history()

    if history is None or history.empty:
        return {
            "estimated_revenue": 0,
            "services_count": 0
        }

    count = len(history)
    revenue = count * avg_service_price

    return {
        "services_count": count,
        "estimated_revenue": round(revenue, 2),
        "avg_service_price": avg_service_price
    }


# =========================
# MONTHLY TREND REPORT
# =========================
def monthly_service_trend() -> pd.DataFrame:
    history = get_service_history()

    if history is None or history.empty:
        return pd.DataFrame()

    history["service_date"] = pd.to_datetime(history["service_date"], errors="coerce")

    history = history.dropna(subset=["service_date"])

    history["month"] = history["service_date"].dt.to_period("M")

    trend = history.groupby("month").size().reset_index(name="service_count")

    return trend.sort_values("month")


# =========================
# EXPORT HELPERS
# =========================
def export_full_report() -> Dict[str, Any]:
    return {
        "kpis": customer_kpis(),
        "service_activity": service_activity_report(),
        "dispatch": dispatch_performance_report(),
        "segments": customer_segmentation(),
        "revenue": estimate_revenue()
    }


def export_report_csv(filepath: str) -> None:
    report = export_full_report()

    # flatten simple structure
    flat = []

    for section, data in report.items():
        if isinstance(data, dict):
            for k, v in data.items():
                flat.append({"section": section, "metric": k, "value": v})

    df = pd.DataFrame(flat)
    df.to_csv(filepath, index=False)