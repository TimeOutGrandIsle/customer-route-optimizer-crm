"""
Treatments Module (Time Out Lawncare CRM)

This module handles:
- Lawn treatment definitions (pre-emerge, post-emerge, fertilization, pest control)
- Seasonal recommendations
- Customer-specific treatment plans
- Treatment scheduling hooks
- Product/application tracking
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

import pandas as pd

from data.database import get_customers, add_service_record


# =========================
# TREATMENT CATALOG
# =========================
TREATMENT_CATALOG = {
    "pre_emerge": {
        "name": "Pre-Emergent Weed Control",
        "season": ["early_spring", "early_fall"],
        "default_interval_days": 120,
        "notes": "Prevents crabgrass and seasonal weeds from germinating."
    },
    "post_emerge": {
        "name": "Post-Emergent Weed Control",
        "season": ["spring", "summer"],
        "default_interval_days": 45,
        "notes": "Kills existing weeds in turf."
    },
    "fertilization": {
        "name": "Lawn Fertilization",
        "season": ["spring", "summer", "fall"],
        "default_interval_days": 60,
        "notes": "Promotes healthy turf growth and color."
    },
    "pest_control": {
        "name": "Pest Control Treatment",
        "season": ["spring", "summer"],
        "default_interval_days": 90,
        "notes": "Controls armyworms, grubs, and lawn pests."
    },
    "fungus_control": {
        "name": "Fungus & Disease Control",
        "season": ["summer"],
        "default_interval_days": 45,
        "notes": "Treats brown patch, leaf spot, and turf fungus."
    },
    "winterization": {
        "name": "Winterization Treatment",
        "season": ["fall"],
        "default_interval_days": 180,
        "notes": "Prepares lawn for cold weather dormancy."
    }
}


# =========================
# SEASON HELPERS
# =========================
def get_season(month: int) -> str:
    if month in [12, 1, 2]:
        return "winter"
    if month in [3]:
        return "early_spring"
    if month in [4, 5]:
        return "spring"
    if month in [6, 7, 8]:
        return "summer"
    if month in [9]:
        return "early_fall"
    return "fall"


# =========================
# TREATMENT LOGIC
# =========================
def get_applicable_treatments(season: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns treatments suitable for a season.
    """
    if not season:
        season = get_season(datetime.now().month)

    results = []

    for key, t in TREATMENT_CATALOG.items():
        if season in t["season"]:
            results.append({
                "id": key,
                "name": t["name"],
                "notes": t["notes"],
                "interval": t["default_interval_days"]
            })

    return results


def recommend_treatments(customer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Basic rule-based recommendation engine.
    """
    season = get_season(datetime.now().month)
    recommendations = get_applicable_treatments(season)

    service_type = customer.get("service", "")

    # boost fertilization for full service clients
    if service_type == "Full Service":
        for r in recommendations:
            if r["id"] == "fertilization":
                r["priority"] = "high"

    # pest control always for humid months (MS reality)
    if season in ["spring", "summer"]:
        recommendations.append({
            "id": "pest_control",
            "name": "Pest Control (Priority)",
            "notes": "High humidity season risk in Mississippi lawns.",
            "interval": 90,
            "priority": "high"
        })

    return recommendations


# =========================
# CUSTOMER TREATMENT PLAN
# =========================
def build_customer_treatment_plan(customer: Dict[str, Any]) -> Dict[str, Any]:
    recs = recommend_treatments(customer)

    plan = {
        "customer_id": customer.get("id"),
        "name": customer.get("name"),
        "season": get_season(datetime.now().month),
        "generated_at": datetime.now().isoformat(),
        "treatments": recs
    }

    return plan


# =========================
# SERVICE INTEGRATION
# =========================
def apply_treatment(customer_id: int, treatment_id: str, notes: str = "") -> None:
    """
    Logs treatment as service event.
    """
    treatment = TREATMENT_CATALOG.get(treatment_id)

    if not treatment:
        raise ValueError(f"Unknown treatment: {treatment_id}")

    add_service_record(
        customer_id=customer_id,
        service_type=treatment["name"],
        notes=notes or treatment["notes"]
    )


# =========================
# BULK TREATMENT PLANNER
# =========================
def generate_seasonal_treatment_schedule(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Creates recommended treatment plans for all customers.
    """
    df = get_customers()

    if df is None or df.empty:
        return []

    plans = []

    for _, row in df.iterrows():
        customer = row.to_dict()
        plan = build_customer_treatment_plan(customer)
        plans.append(plan)

    return plans[:limit]


# =========================
# REPORTING
# =========================
def treatment_summary(plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_customers = len(plans)

    treatment_counts = {}

    for p in plans:
        for t in p.get("treatments", []):
            tid = t["id"]
            treatment_counts[tid] = treatment_counts.get(tid, 0) + 1

    most_common = None
    max_count = 0

    for k, v in treatment_counts.items():
        if v > max_count:
            most_common = k
            max_count = v

    return {
        "total_customers": total_customers,
        "most_common_treatment": most_common,
        "most_common_count": max_count,
        "breakdown": treatment_counts
    }