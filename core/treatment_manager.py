from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import pandas as pd

from data.database import (
    add_service_record,
    dataframe,
    execute,
    get_connection,
)


MAX_TREATMENTS = 10

def save_product_definition(
    product_name: str,
    product_type: str = "",
    manufacturer: str = "",
    epa_number: str = "",
    active_ingredient: str = "",
    default_rate: float = 0.0,
    rate_unit: str = "",
    notes: str = "",
    product_id: int | None = None,
) -> int:
    product_name = product_name.strip()

    if not product_name:
        raise ValueError(
            "Chemical name is required."
        )

    existing = dataframe(
        """
        SELECT id, product_name
        FROM products
        ORDER BY product_name
        """
    )

    matching = existing[
        existing["product_name"]
        .fillna("")
        .str.strip()
        .str.casefold()
        == product_name.casefold()
    ]

    if not matching.empty:
        existing_id = int(
            matching.iloc[0]["id"]
        )

        if product_id is None:
            product_id = existing_id

        elif int(product_id) != existing_id:
            raise ValueError(
                "Another chemical already uses this name."
            )

    if product_id is None:
        return execute(
            """
            INSERT INTO products (
                product_name,
                product_type,
                manufacturer,
                epa_number,
                active_ingredient,
                default_rate,
                rate_unit,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_name,
                product_type.strip(),
                manufacturer.strip(),
                epa_number.strip(),
                active_ingredient.strip(),
                float(default_rate),
                rate_unit.strip(),
                notes.strip(),
            ),
        )

    execute(
        """
        UPDATE products
        SET
            product_name=?,
            product_type=?,
            manufacturer=?,
            epa_number=?,
            active_ingredient=?,
            default_rate=?,
            rate_unit=?,
            notes=?
        WHERE id=?
        """,
        (
            product_name,
            product_type.strip(),
            manufacturer.strip(),
            epa_number.strip(),
            active_ingredient.strip(),
            float(default_rate),
            rate_unit.strip(),
            notes.strip(),
            int(product_id),
        ),
    )

    return int(product_id)


def initialize_treatment_system():
    conn = get_connection()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS treatment_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                standard INTEGER DEFAULT 1,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                target_month INTEGER NOT NULL,
                target_day INTEGER NOT NULL DEFAULT 1,
                active INTEGER DEFAULT 1,
                notes TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS treatment_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                treatment_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                rate_per_acre REAL NOT NULL DEFAULT 0,
                rate_unit TEXT NOT NULL,
                FOREIGN KEY(treatment_id)
                    REFERENCES treatment_definitions(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(product_id)
                    REFERENCES products(id)
                    ON DELETE CASCADE,
                UNIQUE(treatment_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS treatment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                treatment_id INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT DEFAULT 'planned',
                event_type TEXT DEFAULT 'standard',
                override_reason TEXT,
                completed_date TEXT,
                notes TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id)
                    REFERENCES customers(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(treatment_id)
                    REFERENCES treatment_definitions(id)
                    ON DELETE CASCADE,
                UNIQUE(customer_id, treatment_id, due_date)
            );

            CREATE TABLE IF NOT EXISTS application_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                treatment_event_id INTEGER UNIQUE,
                customer_id INTEGER NOT NULL,
                treatment_id INTEGER NOT NULL,
                application_date TEXT NOT NULL,
                property_square_feet REAL DEFAULT 0,
                acres REAL DEFAULT 0,
                notes TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(treatment_event_id)
                    REFERENCES treatment_events(id),
                FOREIGN KEY(customer_id)
                    REFERENCES customers(id),
                FOREIGN KEY(treatment_id)
                    REFERENCES treatment_definitions(id)
            );

            CREATE TABLE IF NOT EXISTS application_chemicals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                epa_number TEXT,
                rate_per_acre REAL DEFAULT 0,
                rate_unit TEXT,
                calculated_amount REAL DEFAULT 0,
                actual_amount REAL DEFAULT 0,
                amount_unit TEXT,
                FOREIGN KEY(application_id)
                    REFERENCES application_records(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(product_id)
                    REFERENCES products(id)
            );

            CREATE INDEX IF NOT EXISTS idx_application_date
            ON application_records(application_date);


            CREATE INDEX IF NOT EXISTS idx_treatment_event_due
            ON treatment_events(due_date, status);

            CREATE INDEX IF NOT EXISTS idx_treatment_event_customer
            ON treatment_events(customer_id);
            """
        )

        conn.commit()

    finally:
        conn.close()


def get_treatment_definitions(
    active_only: bool = False,
) -> pd.DataFrame:
    sql = """
        SELECT
            td.*,
            GROUP_CONCAT(p.product_name, ', ') AS products
        FROM treatment_definitions td
        LEFT JOIN treatment_products tp
            ON tp.treatment_id = td.id
        LEFT JOIN products p
            ON p.id = tp.product_id
    """

    if active_only:
        sql += " WHERE td.active=1 "

    sql += """
        GROUP BY td.id
        ORDER BY td.target_month, td.target_day, td.name
    """

    return dataframe(sql)


def save_treatment_definition(
    name: str,
    window_start: str,
    window_end: str,
    target_month: int,
    target_day: int,
    description: str = "",
    standard: bool = True,
    active: bool = True,
    notes: str = "",
    treatment_id: int | None = None,
) -> int:
    name = name.strip()

    if not name:
        raise ValueError("Treatment name is required.")

    existing = get_treatment_definitions()

    matching = existing[
        existing["name"]
        .fillna("")
        .str.strip()
        .str.casefold()
        == name.casefold()
    ]

    if not matching.empty:
        existing_id = int(
            matching.iloc[0]["id"]
        )

        if treatment_id is None:
            treatment_id = existing_id

        elif int(treatment_id) != existing_id:
            raise ValueError(
                "Another treatment already uses this name."
            )

    if treatment_id is None and len(existing) >= MAX_TREATMENTS:
        raise ValueError(
            "A maximum of 10 treatment types is allowed."
        )

    if treatment_id is None:
        return execute(
            """
            INSERT INTO treatment_definitions (
                name,
                description,
                standard,
                window_start,
                window_end,
                target_month,
                target_day,
                active,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                int(standard),
                window_start,
                window_end,
                int(target_month),
                int(target_day),
                int(active),
                notes,
            ),
        )

    execute(
        """
        UPDATE treatment_definitions
        SET
            name=?,
            description=?,
            standard=?,
            window_start=?,
            window_end=?,
            target_month=?,
            target_day=?,
            active=?,
            notes=?
        WHERE id=?
        """,
        (
            name,
            description,
            int(standard),
            window_start,
            window_end,
            int(target_month),
            int(target_day),
            int(active),
            notes,
            int(treatment_id),
        ),
    )

    return int(treatment_id)


def get_treatment_products(
    treatment_id: int,
) -> pd.DataFrame:
    return dataframe(
        """
        SELECT
            tp.id,
            tp.treatment_id,
            tp.product_id,
            p.product_name,
            p.product_type,
            p.epa_number,
            tp.rate_per_acre,
            tp.rate_unit
        FROM treatment_products tp
        INNER JOIN products p
            ON p.id = tp.product_id
        WHERE tp.treatment_id=?
        ORDER BY p.product_name
        """,
        (int(treatment_id),),
    )


def replace_treatment_products(
    treatment_id: int,
    products: List[Dict[str, Any]],
):
    conn = get_connection()

    try:
        conn.execute(
            """
            DELETE FROM treatment_products
            WHERE treatment_id=?
            """,
            (int(treatment_id),),
        )

        for product in products:
            conn.execute(
                """
                INSERT INTO treatment_products (
                    treatment_id,
                    product_id,
                    rate_per_acre,
                    rate_unit
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(treatment_id),
                    int(product["product_id"]),
                    float(product["rate_per_acre"]),
                    str(product["rate_unit"]).strip(),
                ),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def generate_standard_events(
    year: int,
) -> Dict[str, int]:
    treatments = get_treatment_definitions(
        active_only=True
    )

    treatments = treatments[
        treatments["standard"] == 1
    ]

    customers = dataframe(
        """
        SELECT id
        FROM customers
        WHERE active=1
        """
    )

    created = 0
    skipped = 0

    for _, customer in customers.iterrows():
        for _, treatment in treatments.iterrows():
            due = date(
                int(year),
                int(treatment["target_month"]),
                int(treatment["target_day"]),
            ).isoformat()

            try:
                execute(
                    """
                    INSERT INTO treatment_events (
                        customer_id,
                        treatment_id,
                        due_date,
                        status,
                        event_type
                    )
                    VALUES (?, ?, ?, 'planned', 'standard')
                    """,
                    (
                        int(customer["id"]),
                        int(treatment["id"]),
                        due,
                    ),
                )

                created += 1

            except Exception as ex:
                if "UNIQUE constraint failed" in str(ex):
                    skipped += 1
                else:
                    raise

    return {
        "created": created,
        "skipped": skipped,
    }


def add_customer_treatment(
    customer_id: int,
    treatment_id: int,
    due_date: date | str,
    notes: str = "",
):
    due = pd.to_datetime(due_date).date().isoformat()

    return execute(
        """
        INSERT INTO treatment_events (
            customer_id,
            treatment_id,
            due_date,
            status,
            event_type,
            notes
        )
        VALUES (?, ?, ?, 'planned', 'add_on', ?)
        """,
        (
            int(customer_id),
            int(treatment_id),
            due,
            notes,
        ),
    )


def get_treatment_events(
    include_completed: bool = False,
) -> pd.DataFrame:
    sql = """
        SELECT
            te.id,
            te.customer_id,
            c.name AS customer,
            c.address,
            c.square_feet,
            te.treatment_id,
            td.name AS treatment,
            td.window_start,
            td.window_end,
            te.due_date,
            te.status,
            te.event_type,
            te.override_reason,
            te.completed_date,
            te.notes
        FROM treatment_events te
        INNER JOIN customers c
            ON c.id = te.customer_id
        INNER JOIN treatment_definitions td
            ON td.id = te.treatment_id
    """

    if not include_completed:
        sql += """
            WHERE te.status='planned'
        """

    sql += """
        ORDER BY
            te.due_date,
            c.name,
            td.name
    """

    return dataframe(sql)


def reschedule_treatment_event(
    event_id: int,
    new_date: date | str,
    reason: str = "",
):
    due = pd.to_datetime(new_date).date().isoformat()

    execute(
        """
        UPDATE treatment_events
        SET
            due_date=?,
            override_reason=?
        WHERE id=?
        """,
        (
            due,
            reason,
            int(event_id),
        ),
    )


def shift_pending_treatments(
    treatment_id: int,
    days: int,
    reason: str,
) -> int:
    pending = dataframe(
        """
        SELECT id, due_date
        FROM treatment_events
        WHERE treatment_id=?
          AND status='planned'
        """,
        (int(treatment_id),),
    )

    for _, event in pending.iterrows():
        current = pd.to_datetime(
            event["due_date"]
        ).date()

        reschedule_treatment_event(
            int(event["id"]),
            current + timedelta(days=int(days)),
            reason,
        )

    return len(pending)


def complete_treatment_event(
    event_id: int,
    notes: str = "",
    application_date: date | str | None = None,
    actual_amounts: Dict[int, float] | None = None,
):
    events = dataframe(
        """
        SELECT
            te.id,
            te.customer_id,
            te.treatment_id,
            c.square_feet,
            td.name AS treatment_name
        FROM treatment_events te
        INNER JOIN customers c
            ON c.id = te.customer_id
        INNER JOIN treatment_definitions td
            ON td.id = te.treatment_id
        WHERE te.id=?
        """,
        (int(event_id),),
    )

    if events.empty:
        raise ValueError(
            "Treatment event was not found."
        )

    event = events.iloc[0]

    applied_date = pd.to_datetime(
        application_date or date.today()
    ).date().isoformat()

    square_feet = float(
        event["square_feet"] or 0
    )

    acres = square_feet / 43560.0

    chemicals = get_treatment_products(
        int(event["treatment_id"])
    )

    actual_amounts = actual_amounts or {}

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO application_records (
                treatment_event_id,
                customer_id,
                treatment_id,
                application_date,
                property_square_feet,
                acres,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(event_id),
                int(event["customer_id"]),
                int(event["treatment_id"]),
                applied_date,
                square_feet,
                acres,
                notes,
            ),
        )

        application_id = cursor.lastrowid

        for _, chemical in chemicals.iterrows():
            product_id = int(
                chemical["product_id"]
            )

            rate = float(
                chemical["rate_per_acre"] or 0
            )

            calculated_amount = rate * acres

            actual_amount = float(
                actual_amounts.get(
                    product_id,
                    calculated_amount,
                )
            )

            cursor.execute(
                """
                INSERT INTO application_chemicals (
                    application_id,
                    product_id,
                    product_name,
                    epa_number,
                    rate_per_acre,
                    rate_unit,
                    calculated_amount,
                    actual_amount,
                    amount_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    product_id,
                    str(chemical["product_name"]),
                    str(
                        chemical["epa_number"] or ""
                    ),
                    rate,
                    str(chemical["rate_unit"] or ""),
                    calculated_amount,
                    actual_amount,
                    str(chemical["rate_unit"] or ""),
                ),
            )

        cursor.execute(
            """
            UPDATE treatment_events
            SET
                status='completed',
                completed_date=?,
                notes=?
            WHERE id=?
            """,
            (
                applied_date,
                notes,
                int(event_id),
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    add_service_record(
        customer_id=int(event["customer_id"]),
        service_type=str(event["treatment_name"]),
        notes=notes,
    )


def calculate_mixture(
    treatment_id: int,
    acres: float,
    gallons_per_acre: float,
    tank_gallons: float,
) -> pd.DataFrame:
    products = get_treatment_products(
        treatment_id
    )

    total_spray_gallons = (
        float(acres) * float(gallons_per_acre)
    )

    rows = []

    for _, product in products.iterrows():
        rate = float(product["rate_per_acre"])
        total_product = rate * float(acres)

        if total_spray_gallons > 0:
            product_per_gallon = (
                total_product / total_spray_gallons
            )
        else:
            product_per_gallon = 0

        product_per_tank = (
            product_per_gallon * float(tank_gallons)
        )

        rows.append(
            {
                "Product": product["product_name"],
                "Rate Per Acre": rate,
                "Unit": product["rate_unit"],
                "Total Product": round(
                    total_product,
                    4,
                ),
                "Product Per Gallon": round(
                    product_per_gallon,
                    4,
                ),
                "Product Per Full Tank": round(
                    product_per_tank,
                    4,
                ),
                "Total Spray Gallons": round(
                    total_spray_gallons,
                    2,
                ),
            }
        )

    return pd.DataFrame(rows)


initialize_treatment_system()