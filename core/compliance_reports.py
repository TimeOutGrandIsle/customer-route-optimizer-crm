from __future__ import annotations

from datetime import date
from html import escape
from typing import Dict, List

import pandas as pd

from data.database import dataframe


PRINT_STYLE = """
<style>
    body {
        font-family: Arial, sans-serif;
        margin: 28px;
        color: #222;
    }

    h1 {
        margin-bottom: 4px;
    }

    .subtitle {
        color: #555;
        margin-bottom: 20px;
    }

    .summary {
        display: flex;
        gap: 24px;
        margin: 16px 0;
    }

    .metric {
        border: 1px solid #bbb;
        border-radius: 6px;
        padding: 10px 16px;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 18px;
        font-size: 9px;
    }

    th, td {
        border: 1px solid #888;
        padding: 6px;
        text-align: left;
        vertical-align: top;
    }

    th {
        background: #e9efe8;
    }

    .print-button {
        margin-bottom: 20px;
        padding: 8px 18px;
    }

    @media print {
        .print-button {
            display: none;
        }

        body {
            margin: 8px;
        }
    }
    
    @page {
        size: landscape;
        margin: 0.35in;
    }
    
</style>
"""


def get_application_report(
    start_date: date | str,
    end_date: date | str,
) -> pd.DataFrame:
    """
    Combine new CRM applications and imported workbook history.
    """
    start = pd.to_datetime(
        start_date
    ).date().isoformat()

    end = pd.to_datetime(
        end_date
    ).date().isoformat()

    current = dataframe(
        """
        SELECT
            'CRM-' || ar.id AS "Application ID",
            ar.application_date AS "Application Date",
            '' AS "Start Time",
            '' AS "End Time",
            ar.applicator AS "Applicator",
            ar.applicator_id_number AS "Applicator ID",
            c.name AS "Customer",
            COALESCE(
                NULLIF(c.address, ''),
                TRIM(
                    COALESCE(c.street_address, '') ||
                    CASE
                        WHEN c.city IS NOT NULL
                         AND c.city != ''
                        THEN ', ' || c.city
                        ELSE ''
                    END ||
                    CASE
                        WHEN c.state IS NOT NULL
                         AND c.state != ''
                        THEN ', ' || c.state
                        ELSE ''
                    END ||
                    CASE
                        WHEN c.zip IS NOT NULL
                         AND c.zip != ''
                        THEN ' ' || c.zip
                        ELSE ''
                    END
                )
            ) AS "Full Address",
            c.phone AS "Phone",
            c.text_phone AS "Text Phone",
            c.email AS "Email",
            td.name AS "Treatment",
            printf(
                '%.0f sq ft',
                ar.property_square_feet
            ) AS "Area Treated",
            ac.product_name AS "Chemical",
            ac.epa_number AS "EPA Number",
            ac.rate_per_acre AS "Rate",
            ac.rate_unit AS "Rate Unit",
            ac.calculated_amount AS "Calculated Amount",
            ac.actual_amount AS "Total Applied",
            ac.amount_unit AS "Amount Unit",
            ar.property_square_feet AS "Property Sq Ft",
            ar.acres AS "Acres",
            ar.notes AS "Notes",
            'CRM' AS "Source"
        FROM application_records ar
        INNER JOIN customers c
            ON c.id=ar.customer_id
        INNER JOIN treatment_definitions td
            ON td.id=ar.treatment_id
        LEFT JOIN application_chemicals ac
            ON ac.application_id=ar.id
        WHERE DATE(ar.application_date)
            BETWEEN DATE(?) AND DATE(?)
        ORDER BY
            ar.application_date,
            c.name,
            ac.product_name
        """,
        (
            start,
            end,
        ),
    )

    imported = dataframe(
        """
        SELECT
            'IMPORT-' || ia.id AS "Application ID",
            ia.application_date AS "Application Date",
            ia.application_start_time AS "Start Time",
            ia.application_end_time AS "End Time",
            ia.applicator AS "Applicator",
            ia.applicator_id_number AS "Applicator ID",
            COALESCE(
                c.name,
                ia.customer_name
            ) AS "Customer",
            COALESCE(
                NULLIF(c.address, ''),
                TRIM(
                    COALESCE(c.street_address, '') ||
                    CASE
                        WHEN c.city IS NOT NULL
                         AND c.city != ''
                        THEN ', ' || c.city
                        ELSE ''
                    END ||
                    CASE
                        WHEN c.state IS NOT NULL
                         AND c.state != ''
                        THEN ', ' || c.state
                        ELSE ''
                    END ||
                    CASE
                        WHEN c.zip IS NOT NULL
                         AND c.zip != ''
                        THEN ' ' || c.zip
                        ELSE ''
                    END
                ),
                ''
            ) AS "Full Address",
            COALESCE(c.phone, '') AS "Phone",
            COALESCE(c.text_phone, '') AS "Text Phone",
            COALESCE(c.email, '') AS "Email",
            ia.treatment_type AS "Treatment",
            ia.size_of_area_treated AS "Area Treated",
            iac.brand_name AS "Chemical",
            COALESCE(
                NULLIF(iac.epa_number, ''),
                p.epa_number,
                ''
            ) AS "EPA Number",
            iac.rate_per_acre AS "Rate",
            '' AS "Rate Unit",
            NULL AS "Calculated Amount",
            iac.total_amount_oz AS "Total Applied",
            'oz' AS "Amount Unit",
            NULL AS "Property Sq Ft",
            NULL AS "Acres",
            '' AS "Notes",
            'Workbook Import' AS "Source"
        FROM imported_applications ia
        LEFT JOIN customers c
            ON c.id=ia.customer_id
        LEFT JOIN imported_application_chemicals iac
            ON iac.application_id=ia.id
        LEFT JOIN products p
            ON p.id=iac.product_id
        WHERE DATE(ia.application_date)
            BETWEEN DATE(?) AND DATE(?)
        ORDER BY
            ia.application_date,
            ia.customer_name,
            iac.chemical_position
        """,
        (
            start,
            end,
        ),
    )

    report = pd.concat(
        [
            current,
            imported,
        ],
        ignore_index=True,
    )

    if report.empty:
        return report

    report["Application Date"] = pd.to_datetime(
        report["Application Date"],
        errors="coerce",
    )

    report.sort_values(
        [
            "Application Date",
            "Customer",
            "Chemical",
        ],
        inplace=True,
        na_position="last",
    )

    report["Application Date"] = (
        report["Application Date"]
        .dt.date
        .astype(str)
    )

    report.reset_index(
        drop=True,
        inplace=True,
    )

    return report


def _document(
    title: str,
    subtitle: str,
    body: str,
) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
{PRINT_STYLE}
</head>
<body>
<button class="print-button" onclick="window.print()">
    Print Report
</button>
<h1>{escape(title)}</h1>
<div class="subtitle">{escape(subtitle)}</div>
{body}
</body>
</html>
"""


def build_inspector_html(
    report: pd.DataFrame,
    start_date: date | str,
    end_date: date | str,
) -> str:
    subtitle = (
        f"Application dates: {start_date} through {end_date}"
    )

    if report.empty:
        body = "<p>No applications were recorded in this period.</p>"

    else:
        application_count = report[
            "Application ID"
        ].nunique()

        body = f"""
<div class="summary">
    <div class="metric">
        <strong>Applications</strong><br>
        {application_count}
    </div>
    <div class="metric">
        <strong>Chemical Records</strong><br>
        {len(report)}
    </div>
</div>
{report.to_html(index=False, border=0)}
"""

    return _document(
        "Pesticide Application Report",
        subtitle,
        body,
    )


def build_route_html(
    route: List[Dict],
    summary: Dict,
    route_date: date | str,
) -> str:
    rows = []

    for stop in route:
        if not stop.get("customer_id"):
            continue

        rows.append(
            {
                "Stop": stop.get(
                    "stop_number",
                    "",
                ),
                "Customer": stop.get(
                    "name",
                    "",
                ),
                "Address": stop.get(
                    "address",
                    "",
                ),
                "Phone": stop.get(
                    "phone",
                    "",
                ),
                "Service": stop.get(
                    "service",
                    "",
                ),
                "Arrival": stop.get(
                    "arrival_minutes",
                    "",
                ),
                "Drive Minutes": stop.get(
                    "drive_minutes",
                    "",
                ),
                "Notes": stop.get(
                    "notes",
                    "",
                ),
            }
        )

    route_df = pd.DataFrame(rows)

    summary_html = f"""
<div class="summary">
    <div class="metric">
        <strong>Stops</strong><br>
        {summary.get("stops", 0)}
    </div>
    <div class="metric">
        <strong>Miles</strong><br>
        {summary.get("distance_miles", 0)}
    </div>
    <div class="metric">
        <strong>Drive Minutes</strong><br>
        {summary.get("drive_minutes", 0)}
    </div>
    <div class="metric">
        <strong>Total Minutes</strong><br>
        {summary.get("total_minutes", 0)}
    </div>
</div>
"""

    if route_df.empty:
        table_html = "<p>No route is currently available.</p>"
    else:
        table_html = route_df.to_html(
            index=False,
            border=0,
        )

    return _document(
        "Daily Route",
        f"Route date: {route_date}",
        summary_html + table_html,
    )