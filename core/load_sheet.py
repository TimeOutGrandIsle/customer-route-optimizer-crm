from __future__ import annotations

from math import floor
from typing import Any, Dict, List

import pandas as pd

from data.database import dataframe


def _amount_unit(rate_unit: str) -> str:
    unit = str(rate_unit or "").strip()

    for suffix in [
        "/acre",
        " per acre",
        "/ac",
    ]:
        if unit.lower().endswith(suffix):
            return unit[: -len(suffix)].strip()

    return unit


def build_daily_load_sheet(
    scheduled_date,
    gallons_per_acre: float,
    tank_sizes: List[float],
) -> Dict[str, Any]:
    selected_date = pd.to_datetime(
        scheduled_date
    ).date().isoformat()

    stops = dataframe(
        """
        SELECT
            dj.id AS dispatch_job_id,
            dj.customer_id,
            c.name AS customer,
            c.square_feet,
            dj.treatment_name
        FROM dispatch_jobs dj
        INNER JOIN customers c
            ON c.id=dj.customer_id
        WHERE dj.scheduled_date=?
          AND dj.status IN (
              'queued',
              'in_progress'
          )
        ORDER BY c.name
        """,
        (selected_date,),
    )

    if stops.empty:
        return {
            "summary": {
                "stops": 0,
                "acres": 0,
                "water_gallons": 0,
            },
            "chemical_totals": pd.DataFrame(),
            "mix_summary": pd.DataFrame(),
            "tank_plan": pd.DataFrame(),
        }

    treatments = dataframe(
        """
        SELECT
            te.dispatch_job_id,
            te.id AS treatment_event_id,
            te.treatment_id,
            td.name AS treatment
        FROM treatment_events te
        INNER JOIN treatment_definitions td
            ON td.id=te.treatment_id
        INNER JOIN dispatch_jobs dj
            ON dj.id=te.dispatch_job_id
        WHERE dj.scheduled_date=?
          AND dj.status IN (
              'queued',
              'in_progress'
          )
          AND te.status='planned'
        ORDER BY
            te.dispatch_job_id,
            td.name
        """,
        (selected_date,),
    )

    chemicals = dataframe(
        """
        SELECT
            te.dispatch_job_id,
            te.treatment_id,
            td.name AS treatment,
            p.id AS product_id,
            p.product_name,
            p.epa_number,
            tp.rate_per_acre,
            tp.rate_unit
        FROM treatment_events te
        INNER JOIN treatment_definitions td
            ON td.id=te.treatment_id
        INNER JOIN treatment_products tp
            ON tp.treatment_id=te.treatment_id
        INNER JOIN products p
            ON p.id=tp.product_id
        INNER JOIN dispatch_jobs dj
            ON dj.id=te.dispatch_job_id
        WHERE dj.scheduled_date=?
          AND dj.status IN (
              'queued',
              'in_progress'
          )
          AND te.status='planned'
        ORDER BY
            te.dispatch_job_id,
            p.product_name
        """,
        (selected_date,),
    )

    stops = stops.copy()

    stops["square_feet"] = pd.to_numeric(
        stops["square_feet"],
        errors="coerce",
    ).fillna(0)

    stops["acres"] = (
        stops["square_feet"] / 43560.0
    )

    treatment_groups = {}

    if not treatments.empty:

        for job_id, group in treatments.groupby(
            "dispatch_job_id"
        ):

            names = sorted(
                set(
                    str(value)
                    for value in group["treatment"]
                    if value
                )
            )

            treatment_groups[int(job_id)] = (
                " + ".join(names)
            )

    stops["mix_group"] = stops.apply(
        lambda row: (
            treatment_groups.get(
                int(row["dispatch_job_id"]),
                str(
                    row["treatment_name"]
                    or "Unspecified"
                ),
            )
        ),
        axis=1,
    )

    stops["water_gallons"] = (
        stops["acres"]
        * float(gallons_per_acre)
    )

    mix_rows = []
    tank_rows = []
    daily_chemical_rows = []

    for mix_name, mix_stops in stops.groupby(
        "mix_group"
    ):

        mix_acres = float(
            mix_stops["acres"].sum()
        )

        mix_water = float(
            mix_stops["water_gallons"].sum()
        )

        mix_rows.append(
            {
                "Treatment Mix": mix_name,
                "Stops": len(mix_stops),
                "Acres": round(
                    mix_acres,
                    4,
                ),
                "Water Gallons": round(
                    mix_water,
                    2,
                ),
            }
        )

        job_ids = set(
            mix_stops[
                "dispatch_job_id"
            ].astype(int)
        )

        mix_chemicals = chemicals[
            chemicals[
                "dispatch_job_id"
            ].astype(int).isin(job_ids)
        ].copy() if not chemicals.empty else pd.DataFrame()

        chemical_amounts = {}

        for _, chemical in mix_chemicals.iterrows():

            job_id = int(
                chemical["dispatch_job_id"]
            )

            job_acres = float(
                mix_stops.loc[
                    mix_stops[
                        "dispatch_job_id"
                    ].astype(int) == job_id,
                    "acres",
                ].iloc[0]
            )

            key = (
                int(chemical["product_id"]),
                str(chemical["product_name"]),
                str(chemical["epa_number"] or ""),
                str(chemical["rate_unit"] or ""),
            )

            chemical_amounts[key] = (
                chemical_amounts.get(
                    key,
                    0.0,
                )
                + float(
                    chemical["rate_per_acre"]
                    or 0
                )
                * job_acres
            )

        for (
            product_id,
            product_name,
            epa_number,
            rate_unit,
        ), total_amount in chemical_amounts.items():

            unit = _amount_unit(
                rate_unit
            )

            daily_chemical_rows.append(
                {
                    "Treatment Mix": mix_name,
                    "product_id": product_id,
                    "Chemical": product_name,
                    "EPA Number": epa_number,
                    "Total Amount": total_amount,
                    "Unit": unit,
                }
            )

        for tank_size in tank_sizes:

            tank_size = float(
                tank_size
            )

            if tank_size <= 0:
                continue

            full_tanks = floor(
                mix_water / tank_size
            )

            partial_water = (
                mix_water
                - full_tanks * tank_size
            )

            if partial_water < 0.01:
                partial_water = 0.0

            loads = (
                full_tanks
                + (1 if partial_water > 0 else 0)
            )

            if not chemical_amounts:

                tank_rows.append(
                    {
                        "Treatment Mix": mix_name,
                        "Tank Size": tank_size,
                        "Loads": loads,
                        "Full Tanks": full_tanks,
                        "Partial Tank Water": round(
                            partial_water,
                            2,
                        ),
                        "Chemical": "",
                        "Per Full Tank": 0,
                        "Partial Tank Amount": 0,
                        "Unit": "",
                    }
                )

            for (
                product_id,
                product_name,
                epa_number,
                rate_unit,
            ), total_amount in chemical_amounts.items():

                concentration = (
                    total_amount / mix_water
                    if mix_water > 0
                    else 0
                )

                tank_rows.append(
                    {
                        "Treatment Mix": mix_name,
                        "Tank Size": tank_size,
                        "Loads": loads,
                        "Full Tanks": full_tanks,
                        "Partial Tank Water": round(
                            partial_water,
                            2,
                        ),
                        "Chemical": product_name,
                        "Per Full Tank": round(
                            concentration
                            * tank_size,
                            4,
                        ),
                        "Partial Tank Amount": round(
                            concentration
                            * partial_water,
                            4,
                        ),
                        "Unit": _amount_unit(
                            rate_unit
                        ),
                    }
                )

    chemical_detail = pd.DataFrame(
        daily_chemical_rows
    )

    if chemical_detail.empty:

        chemical_totals = pd.DataFrame()

    else:

        chemical_totals = (
            chemical_detail.groupby(
                [
                    "Chemical",
                    "EPA Number",
                    "Unit",
                ],
                as_index=False,
            )["Total Amount"]
            .sum()
        )

        chemical_totals[
            "Total Amount"
        ] = chemical_totals[
            "Total Amount"
        ].round(4)

    return {
        "summary": {
            "stops": len(stops),
            "acres": round(
                float(stops["acres"].sum()),
                4,
            ),
            "water_gallons": round(
                float(
                    stops[
                        "water_gallons"
                    ].sum()
                ),
                2,
            ),
        },
        "chemical_totals": chemical_totals,
        "mix_summary": pd.DataFrame(
            mix_rows
        ),
        "tank_plan": pd.DataFrame(
            tank_rows
        ),
    }
    
def build_daily_load_sheet_html(
    load_sheet: Dict[str, Any],
    scheduled_date,
    gallons_per_acre: float,
    tank_sizes: List[float],
) -> str:
    selected_date = pd.to_datetime(
        scheduled_date
    ).date().isoformat()

    summary = load_sheet["summary"]
    mix_summary = load_sheet["mix_summary"]
    chemical_totals = load_sheet[
        "chemical_totals"
    ]
    tank_plan = load_sheet["tank_plan"]

    tank_description = ", ".join(
        f"{float(size):g} gallon"
        for size in tank_sizes
    )

    def table_html(
        df: pd.DataFrame,
        empty_message: str,
    ) -> str:
        if df.empty:
            return (
                f"<p>{empty_message}</p>"
            )

        return df.to_html(
            index=False,
            border=0,
        )

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Daily Load Sheet — {selected_date}</title>
<style>
    @page {{
        size: landscape;
        margin: 0.4in;
    }}

    body {{
        font-family: Arial, sans-serif;
        margin: 24px;
        color: #222;
    }}

    h1 {{
        margin-bottom: 4px;
    }}

    h2 {{
        margin-top: 26px;
    }}

    .subtitle {{
        color: #555;
        margin-bottom: 18px;
    }}

    .metrics {{
        display: flex;
        gap: 18px;
        margin: 18px 0;
    }}

    .metric {{
        border: 1px solid #999;
        border-radius: 6px;
        padding: 10px 18px;
        min-width: 130px;
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 10px;
    }}

    th, td {{
        border: 1px solid #888;
        padding: 6px;
        text-align: left;
    }}

    th {{
        background: #e9efe8;
    }}

    .print-button {{
        padding: 9px 20px;
        margin-bottom: 18px;
    }}

    @media print {{
        .print-button {{
            display: none;
        }}

        body {{
            margin: 0;
        }}
    }}
</style>
</head>
<body>

<button
    class="print-button"
    onclick="window.print()"
>
    Print Load Sheet
</button>

<h1>Daily Chemical and Water Load Sheet</h1>

<div class="subtitle">
    Date: {selected_date}<br>
    Water rate: {gallons_per_acre:g} gallons per acre<br>
    Tank sizes: {tank_description}
</div>

<div class="metrics">
    <div class="metric">
        <strong>Scheduled Stops</strong><br>
        {summary["stops"]}
    </div>

    <div class="metric">
        <strong>Total Acres</strong><br>
        {summary["acres"]}
    </div>

    <div class="metric">
        <strong>Total Water</strong><br>
        {summary["water_gallons"]} gallons
    </div>
</div>

<h2>Treatment Mix Totals</h2>
{table_html(
    mix_summary,
    "No treatment mixes scheduled."
)}

<h2>Total Chemicals Needed</h2>
{table_html(
    chemical_totals,
    "No chemicals are assigned."
)}

<h2>Tank Load Breakdown</h2>
{table_html(
    tank_plan,
    "No tank loads were calculated."
)}

</body>
</html>
"""