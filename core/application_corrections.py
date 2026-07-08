from __future__ import annotations

import json
from typing import Any, Dict

import pandas as pd

from data.database import (
    dataframe,
    get_connection,
)


def initialize_correction_audit():
    conn = get_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS application_correction_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_key TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                change_reason TEXT NOT NULL,
                before_data TEXT NOT NULL,
                after_data TEXT NOT NULL,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.commit()

    finally:
        conn.close()


def list_application_records() -> pd.DataFrame:
    current = dataframe(
        """
        SELECT
            'CRM-' || ar.id AS record_key,
            ar.application_date,
            c.name AS customer,
            td.name AS treatment,
            ar.applicator,
            'CRM' AS source
        FROM application_records ar
        INNER JOIN customers c
            ON c.id=ar.customer_id
        INNER JOIN treatment_definitions td
            ON td.id=ar.treatment_id
        """
    )

    imported = dataframe(
        """
        SELECT
            'IMPORT-' || ia.id AS record_key,
            ia.application_date,
            ia.customer_name AS customer,
            ia.treatment_type AS treatment,
            ia.applicator,
            'Workbook Import' AS source
        FROM imported_applications ia
        """
    )

    records = pd.concat(
        [current, imported],
        ignore_index=True,
    )

    if records.empty:
        return records

    records.sort_values(
        [
            "application_date",
            "customer",
        ],
        ascending=[
            False,
            True,
        ],
        inplace=True,
    )

    return records


def get_application_record(
    record_key: str,
) -> Dict[str, Any]:
    source, value = record_key.split(
        "-",
        1,
    )

    application_id = int(value)

    if source == "CRM":

        header = dataframe(
            """
            SELECT
                ar.id,
                ar.application_date,
                ar.applicator,
                ar.applicator_id_number,
                ar.property_square_feet,
                ar.acres,
                ar.notes,
                c.name AS customer,
                td.name AS treatment
            FROM application_records ar
            INNER JOIN customers c
                ON c.id=ar.customer_id
            INNER JOIN treatment_definitions td
                ON td.id=ar.treatment_id
            WHERE ar.id=?
            """,
            (application_id,),
        )

        chemicals = dataframe(
            """
            SELECT
                id,
                product_name AS chemical,
                epa_number,
                rate_per_acre,
                rate_unit,
                calculated_amount,
                actual_amount,
                amount_unit
            FROM application_chemicals
            WHERE application_id=?
            ORDER BY product_name
            """,
            (application_id,),
        )

    else:

        header = dataframe(
            """
            SELECT
                id,
                application_date,
                application_start_time,
                application_end_time,
                applicator,
                applicator_id_number,
                treatment_type AS treatment,
                size_of_area_treated,
                customer_name AS customer
            FROM imported_applications
            WHERE id=?
            """,
            (application_id,),
        )

        chemicals = dataframe(
            """
            SELECT
                id,
                chemical_position,
                brand_name AS chemical,
                active_ingredients,
                rate_per_acre,
                total_amount_oz,
                epa_number
            FROM imported_application_chemicals
            WHERE application_id=?
            ORDER BY chemical_position
            """,
            (application_id,),
        )

    if header.empty:
        raise ValueError(
            "Application record was not found."
        )

    return {
        "record_key": record_key,
        "source": source,
        "application_id": application_id,
        "header": header.iloc[0].to_dict(),
        "chemicals": chemicals,
    }


def _snapshot(
    record_key: str,
) -> str:
    record = get_application_record(
        record_key
    )

    return json.dumps(
        {
            "header": record["header"],
            "chemicals": record[
                "chemicals"
            ].to_dict("records"),
        },
        default=str,
        sort_keys=True,
    )


def save_application_correction(
    record_key: str,
    header_values: Dict[str, Any],
    chemical_values: pd.DataFrame,
    changed_by: str,
    change_reason: str,
):
    reason = str(
        change_reason
    ).strip()

    if not reason:
        raise ValueError(
            "A correction reason is required."
        )

    before_data = _snapshot(
        record_key
    )

    source, value = record_key.split(
        "-",
        1,
    )

    application_id = int(value)

    conn = get_connection()

    try:
        cursor = conn.cursor()

        if source == "CRM":

            square_feet = float(
                header_values.get(
                    "property_square_feet",
                    0,
                )
                or 0
            )

            acres = (
                square_feet / 43560.0
            )

            cursor.execute(
                """
                UPDATE application_records
                SET
                    application_date=?,
                    applicator=?,
                    applicator_id_number=?,
                    property_square_feet=?,
                    acres=?,
                    notes=?
                WHERE id=?
                """,
                (
                    header_values.get(
                        "application_date"
                    ),
                    header_values.get(
                        "applicator"
                    ),
                    header_values.get(
                        "applicator_id_number"
                    ),
                    square_feet,
                    acres,
                    header_values.get(
                        "notes"
                    ),
                    application_id,
                ),
            )

            for _, chemical in chemical_values.iterrows():

                cursor.execute(
                    """
                    UPDATE application_chemicals
                    SET
                        product_name=?,
                        epa_number=?,
                        rate_per_acre=?,
                        rate_unit=?,
                        actual_amount=?,
                        amount_unit=?
                    WHERE id=?
                      AND application_id=?
                    """,
                    (
                        chemical["chemical"],
                        chemical["epa_number"],
                        float(
                            chemical[
                                "rate_per_acre"
                            ]
                            or 0
                        ),
                        chemical["rate_unit"],
                        float(
                            chemical[
                                "actual_amount"
                            ]
                            or 0
                        ),
                        chemical["amount_unit"],
                        int(chemical["id"]),
                        application_id,
                    ),
                )

        else:

            cursor.execute(
                """
                UPDATE imported_applications
                SET
                    application_date=?,
                    application_start_time=?,
                    application_end_time=?,
                    applicator=?,
                    applicator_id_number=?,
                    treatment_type=?,
                    size_of_area_treated=?
                WHERE id=?
                """,
                (
                    header_values.get(
                        "application_date"
                    ),
                    header_values.get(
                        "application_start_time"
                    ),
                    header_values.get(
                        "application_end_time"
                    ),
                    header_values.get(
                        "applicator"
                    ),
                    header_values.get(
                        "applicator_id_number"
                    ),
                    header_values.get(
                        "treatment"
                    ),
                    header_values.get(
                        "size_of_area_treated"
                    ),
                    application_id,
                ),
            )

            for _, chemical in chemical_values.iterrows():

                cursor.execute(
                    """
                    UPDATE imported_application_chemicals
                    SET
                        brand_name=?,
                        active_ingredients=?,
                        rate_per_acre=?,
                        total_amount_oz=?,
                        epa_number=?
                    WHERE id=?
                      AND application_id=?
                    """,
                    (
                        chemical["chemical"],
                        chemical[
                            "active_ingredients"
                        ],
                        chemical["rate_per_acre"],
                        float(
                            chemical[
                                "total_amount_oz"
                            ]
                            or 0
                        ),
                        chemical["epa_number"],
                        int(chemical["id"]),
                        application_id,
                    ),
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    after_data = _snapshot(
        record_key
    )

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT INTO application_correction_audit (
                record_key,
                changed_by,
                change_reason,
                before_data,
                after_data
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record_key,
                changed_by,
                reason,
                before_data,
                after_data,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def get_correction_audit() -> pd.DataFrame:
    return dataframe(
        """
        SELECT
            record_key,
            changed_by,
            change_reason,
            changed_at
        FROM application_correction_audit
        ORDER BY changed_at DESC
        """
    )


initialize_correction_audit()