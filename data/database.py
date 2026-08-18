#
# Time Out Lawncare CRM
# Database Layer
#

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

import pandas as pd
import streamlit as st

import hashlib

from data.postgres_compat import connect

# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_connection():

    postgres_settings = st.secrets.get(
        "postgres",
        {},
    )

    required = {
        "host",
        "port",
        "dbname",
        "user",
        "password",
    }
    missing = sorted(
        key
        for key in required
        if postgres_settings.get(key) in (None, "")
    )

    if missing:
        raise RuntimeError(
            "Missing Streamlit [postgres] setting(s): "
            + ", ".join(missing)
        )

    return connect(postgres_settings)


# ---------------------------------------------------------
# DATAFRAME HELPER
# ---------------------------------------------------------

def dataframe(sql, params=()):

    conn = get_connection()

    try:

        return pd.read_sql_query(

            sql,

            conn,

            params=params,

        )

    finally:

        conn.close()


# ---------------------------------------------------------
# EXECUTE HELPER
# ---------------------------------------------------------

def execute(sql, params=()):

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(sql, params)

        conn.commit()

        return cursor.lastrowid

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

def init_db():
    """
    Creates every required table.
    """

    conn = get_connection()

    cur = conn.cursor()

# -------------------------------------------------
# Customers
# -------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            customer_number TEXT UNIQUE,

            name TEXT NOT NULL,

            address TEXT,

            street_address TEXT,

            city TEXT,

            state TEXT,

            zip TEXT,

            county TEXT,

            phone TEXT,

            email TEXT,

            text_phone TEXT,

            square_feet REAL,

            turf_type TEXT,

            irrigation TEXT,

            payment_method TEXT,
            
            quote REAL,

            active INTEGER DEFAULT 1,

            special_instructions TEXT,

            lat REAL,

            lng REAL,
            
            neighborhood TEXT,

            cluster_id INTEGER DEFAULT 0,

            distance_from_cluster REAL DEFAULT 0,

            service TEXT,

            last_service TEXT

        )
        """
    )

    # -------------------------------------------------
    # Dispatch
    # -------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_jobs
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

                        customer_id INTEGER NOT NULL,

            treatment_name TEXT,

            scheduled_date TEXT,

            notes TEXT,

            status TEXT DEFAULT 'queued',

            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(customer_id)
                REFERENCES customers(id)
                ON DELETE CASCADE
        )
        """
    )


    cur.execute("""
    CREATE TABLE IF NOT EXISTS route_cache
    (
        origin_hash TEXT NOT NULL,
        destination_hash TEXT NOT NULL,

        origin_address TEXT,
        destination_address TEXT,

        distance_meters REAL,
        duration_seconds REAL,

        provider TEXT,

        updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        PRIMARY KEY
        (
            origin_hash,
            destination_hash
        )
    )
    """)
    
    dispatch_columns = {
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(dispatch_jobs)"
        ).fetchall()
    }

    customer_columns = {
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(customers)"
        ).fetchall()
    }

    if "quote" not in customer_columns:
        cur.execute(
            "ALTER TABLE customers ADD COLUMN quote REAL"
        )


    if "treatment_name" not in dispatch_columns:
        cur.execute(
            """
            ALTER TABLE dispatch_jobs
            ADD COLUMN treatment_name TEXT
            """
        )

    # -------------------------------------------------
    # Geocode Cache
    # -------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache
        (
            address TEXT PRIMARY KEY,

            formatted_address TEXT,

            lat REAL,

            lng REAL,

            provider TEXT,

            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    
    # -------------------------------------------------
    # Service History
    # -------------------------------------------------

    cur.execute(
    """
    CREATE TABLE IF NOT EXISTS service_history
    (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        customer_id INTEGER,

        technician TEXT,

        route_date TEXT,

        arrival_time TEXT,

        start_time TEXT,

        finish_time TEXT,

        drive_minutes REAL DEFAULT 0,

        service_minutes REAL DEFAULT 0,

        total_minutes REAL DEFAULT 0,

        service_type TEXT,

        products_used TEXT,

        chemical_cost REAL DEFAULT 0,

        revenue REAL DEFAULT 0,

        notes TEXT,

        weather TEXT,

        temperature REAL,

        completed INTEGER DEFAULT 1,

        gps_lat REAL,

        gps_lng REAL,

        service_date TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(customer_id)
            REFERENCES customers(id)
            ON DELETE CASCADE
    )
    """
    )

    # -------------------------------------------------
    # Settings
    # -------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings
        (
            key TEXT PRIMARY KEY,

            value TEXT
        )
        """
    )

    # -------------------------------------------------
    # Indexes
    # -------------------------------------------------

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customer_name
        ON customers(name)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dispatch_status
        ON dispatch_jobs(status)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dispatch_customer
        ON dispatch_jobs(customer_id)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_customer
        ON service_history(customer_id)
        """
    )


    create_products_table()

    create_services_table()

    create_treatment_plans_table()

    create_chemical_costs_table()
    
    create_property_details_table()

    create_billing_accounts_table()

    create_customer_notes_table()
    
    create_employees_table()

    create_equipment_table()

    create_routes_table()

    create_route_stops_table()
    
# -------------------------------------------------
# Neighborhood Intelligence
# -------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS neighborhoods
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT UNIQUE,

            center_lat REAL,

            center_lng REAL,

            customer_count INTEGER DEFAULT 0,

            average_square_feet REAL DEFAULT 0,

            average_service_time REAL DEFAULT 0,

            average_drive_time REAL DEFAULT 0,

            preferred_day TEXT,

            preferred_crew TEXT,

            average_revenue REAL DEFAULT 0,

            production_score REAL DEFAULT 0,

            efficiency_score REAL DEFAULT 0,

            last_updated TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()

    conn.close()


# ---------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------

def set_setting(
    key: str,
    value: str,
):
    """
    Stores an application setting.
    """

    execute(
        """
        INSERT INTO settings(key,value)

        VALUES(?,?)

        ON CONFLICT(key)

        DO UPDATE

        SET value=excluded.value
        """,
        (
            key,
            value,
        ),
    )


def get_setting(
    key: str,
    default: Optional[str] = None,
) -> Optional[str]:

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT value

            FROM settings

            WHERE key=?
            """,
            (key,),
        )

        row = cur.fetchone()

        if row is None:

            return default

        return row["value"]

    finally:

        conn.close()


# ---------------------------------------------------------
# CUSTOMER CRUD
# ---------------------------------------------------------

# ==========================================================
# ADD CUSTOMER
# ==========================================================

def get_next_customer_number(
    conn=None,
) -> str:
    """
    Returns the next numeric customer number.

    PostgreSQL's transaction-level advisory lock prevents two users
    from receiving the same number when customers are added at nearly
    the same time. Non-numeric legacy values such as TEST-001 do not
    affect the numeric sequence.
    """

    owns_connection = conn is None

    if owns_connection:
        conn = get_connection()

    try:

        conn.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtext('customers.customer_number')
            )
            """
        )

        cursor = conn.execute(
            """
            SELECT
                COALESCE(
                    MAX(
                        CAST(customer_number AS BIGINT)
                    ),
                    1000
                ) + 1

            FROM customers

            WHERE customer_number ~ '^[0-9]+$'
            """
        )

        row = cursor.fetchone()

        return str(
            int(row[0])
        )

    finally:

        if owns_connection:
            conn.rollback()
            conn.close()


def _legacy_add_customer(

    customer_number=None,

    name=None,

    address=None,

    street_address=None,

    city=None,

    state=None,

    zip=None,

    county=None,

    phone=None,

    email=None,

    text_phone=None,

    square_feet=None,

    turf_type=None,

    irrigation=None,

    payment_method=None,
    
    quote=None,

    active=1,

    special_instructions=None,

    lat=None,

    lng=None,
    
    neighborhood=None,

    cluster_id=0,

    distance_from_cluster=0,

    service=None,

    last_service=None,

):

    # ---------------------------------------------
    # Build full address if one wasn't supplied
    # ---------------------------------------------

    if not address:

        parts = [

            street_address,

            city,

            state,

            zip,

        ]

        address = ", ".join(

            str(x).strip()

            for x in parts

            if x not in (None, "")

        )

    conn = get_connection()

    if customer_number is None or not str(
        customer_number
    ).strip():

        customer_number = get_next_customer_number(
            conn
        )

    conn.execute(

        """
        INSERT INTO customers (

            customer_number,

            name,

            address,

            street_address,

            city,

            state,

            zip,

            county,

            phone,

            email,

            text_phone,

            square_feet,

            turf_type,

            irrigation,

            payment_method,
            
            quote,

            active,

            special_instructions,

            lat,

            lng,

            neighborhood,

            cluster_id,

            distance_from_cluster,

            service,

            last_service

        )

        VALUES (

            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?

        )
        """,

        (

            customer_number,

            name,

            address,

            street_address,

            city,

            state,

            zip,

            county,

            phone,

            email,

            text_phone,

            square_feet,

            turf_type,

            irrigation,

            payment_method,
            
            quote,

            active,

            special_instructions,

            lat,

            lng,

            neighborhood,

            cluster_id,

            distance_from_cluster,

            service,

            last_service,

        ),

    )

    conn.commit()

    conn.close()

def get_customer(customer_id: int) -> Optional[Dict[str, Any]]:
    """
    Returns a single customer.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT *

            FROM customers

            WHERE id=?
            """,
            (customer_id,),
        )

        row = cur.fetchone()

        if row is None:
            return None

        return dict(row)

    finally:

        conn.close()


def get_customers(
    active_only: bool = False,
) -> pd.DataFrame:
    """
    Returns all customers.
    """

    sql = """
        SELECT *

        FROM customers
    """

    if active_only:

        sql += """

        WHERE active=1

        """

    sql += """

        ORDER BY name

    """

    return dataframe(sql)


def customer_exists(customer_id: int) -> bool:
    """
    Returns True if customer exists.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)

            FROM customers

            WHERE id=?
            """,
            (customer_id,),
        )

        return cur.fetchone()[0] > 0

    finally:

        conn.close()


def update_customer(
    customer_id: int,
    **kwargs,
):
    """
    Updates any customer fields supplied
    through keyword arguments.
    """

    if not kwargs:
        return

    fields = []

    values = []

    for key, value in kwargs.items():

        fields.append(f"{key}=?")

        values.append(value)

    values.append(customer_id)

    sql = f"""
        UPDATE customers

        SET {', '.join(fields)}

        WHERE id=?
    """

    execute(
        sql,
        tuple(values),
    )


def delete_customer(
    customer_id: int,
):
    """
    Permanently removes a customer.
    """

    execute(
        """
        DELETE

        FROM customers

        WHERE id=?
        """,
        (customer_id,),
    )


def deactivate_customer(
    customer_id: int,
):
    """
    Soft delete.
    """

    execute(
        """
        UPDATE customers

        SET active=0

        WHERE id=?
        """,
        (customer_id,),
    )


def search_customers(
    search_text: str,
) -> pd.DataFrame:
    """
    Searches customers by
    name, address, phone,
    email or service.
    """

    like = f"%{search_text}%"

    return dataframe(
        """
        SELECT *

        FROM customers

        WHERE

            name LIKE ?

        OR

            address LIKE ?

        OR

            phone LIKE ?

        OR

            email LIKE ?

        OR

            service LIKE ?

        ORDER BY name
        """,
        (
            like,
            like,
            like,
            like,
            like,
        ),
    )


def customer_count() -> int:
    """
    Returns customer count.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)

            FROM customers
            """
        )

        return cur.fetchone()[0]

    finally:

        conn.close()


def active_customer_count() -> int:
    """
    Returns active customer count.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)

            FROM customers

            WHERE active=1
            """
        )

        return cur.fetchone()[0]

    finally:

        conn.close()


def update_customer_coordinates(
    customer_id: int,
    lat: float,
    lng: float,
):
    """
    Updates GPS coordinates.
    """

    execute(
        """
        UPDATE customers

        SET
            lat=?,
            lng=?

        WHERE id=?
        """,
        (
            lat,
            lng,
            customer_id,
        ),
    )

# ---------------------------------------------------------
# DISPATCH
# ---------------------------------------------------------

def add_dispatch_job(
    customer_id: int,
    scheduled_date: str | None = None,
    notes: str = "",
    treatment_name: str | None = None,
) -> int:
    """
    Queue a customer for dispatch.
    """
    return execute(
        """
        INSERT INTO dispatch_jobs (
            customer_id,
            treatment_name,
            scheduled_date,
            notes
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            customer_id,
            treatment_name,
            scheduled_date,
            notes,
        ),
    )


def get_dispatch_jobs(
    status: str | None = None,
) -> pd.DataFrame:
    """
    Returns dispatch jobs joined with customer information.
    """

    sql = """
        SELECT

            dj.id,
            dj.customer_id,
            c.name,
            c.address,
            c.lat,
            c.lng,
            c.phone,
            c.text_phone,
            COALESCE(
                NULLIF(dj.treatment_name, ''),
                c.service
            ) AS service,
            dj.treatment_name,
            c.neighborhood,
            c.cluster_id,
            c.distance_from_cluster,
            dj.scheduled_date,
            dj.notes,
            dj.status,
            dj.created

        FROM dispatch_jobs dj

        INNER JOIN customers c

            ON dj.customer_id = c.id
    """

    params: list[Any] = []

    if status is not None:

        sql += """

        WHERE dj.status=?

        """

        params.append(status)

    sql += """

        ORDER BY

            dj.scheduled_date,

            c.name

    """

    return dataframe(
        sql,
        tuple(params),
    )


def get_dispatch_job(
    job_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Returns a single dispatch job.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT *

            FROM dispatch_jobs

            WHERE id=?
            """,
            (job_id,),
        )

        row = cur.fetchone()

        if row is None:
            return None

        return dict(row)

    finally:

        conn.close()


def update_dispatch_status(
    job_id: int,
    status: str,
):
    """
    Updates dispatch status.
    """

    execute(
        """
        UPDATE dispatch_jobs

        SET status=?

        WHERE id=?
        """,
        (
            status,
            job_id,
        ),
    )


def update_dispatch_notes(
    job_id: int,
    notes: str,
):
    execute(
        """
        UPDATE dispatch_jobs

        SET notes=?

        WHERE id=?
        """,
        (
            notes,
            job_id,
        ),
    )


def reschedule_dispatch(
    job_id: int,
    scheduled_date: str,
):
    execute(
        """
        UPDATE dispatch_jobs

        SET scheduled_date=?

        WHERE id=?
        """,
        (
            scheduled_date,
            job_id,
        ),
    )


def delete_dispatch_job(
    job_id: int,
):
    execute(
        """
        DELETE

        FROM dispatch_jobs

        WHERE id=?
        """,
        (job_id,),
    )


def clear_completed_dispatch():
    """
    Removes completed dispatch jobs.
    """

    execute(
        """
        DELETE

        FROM dispatch_jobs

        WHERE status='completed'
        """
    )


def clear_cancelled_dispatch():
    """
    Removes cancelled jobs.
    """

    execute(
        """
        DELETE

        FROM dispatch_jobs

        WHERE status='cancelled'
        """
    )


def dispatch_job_count(
    status: str | None = None,
) -> int:
    """
    Returns dispatch job count.
    """

    conn = get_connection()

    try:

        cur = conn.cursor()

        if status is None:

            cur.execute(
                """
                SELECT COUNT(*)

                FROM dispatch_jobs
                """
            )

        else:

            cur.execute(
                """
                SELECT COUNT(*)

                FROM dispatch_jobs

                WHERE status=?
                """,
                (status,),
            )

        return cur.fetchone()[0]

    finally:

        conn.close()


def queued_dispatch_count() -> int:
    return dispatch_job_count("queued")


def completed_dispatch_count() -> int:
    return dispatch_job_count("completed")


def cancelled_dispatch_count() -> int:
    return dispatch_job_count("cancelled")


def dispatch_summary() -> Dict[str, int]:
    """
    Dashboard helper.
    """

    return {
        "queued": queued_dispatch_count(),
        "completed": completed_dispatch_count(),
        "cancelled": cancelled_dispatch_count(),
        "total": dispatch_job_count(),
    }


# ---------------------------------------------------------
# SERVICE HISTORY
# ---------------------------------------------------------

def add_service_record(
    customer_id: int,
    service_type: str,
    notes: str = "",
):
    # """
    # Adds a completed service record and updates the
    # customer's last_service date.
    # """

    execute(
        """
        INSERT INTO service_history
        (
            customer_id,
            service_type,
            notes
        )

        VALUES
        (
            ?,?,?
        )
        """,
        (
            customer_id,
            service_type,
            notes,
        ),
    )

    execute(
        """
        UPDATE customers

        SET last_service = CURRENT_DATE::TEXT

        WHERE id=?
        """,
        (customer_id,),
    )


def get_service_history(
    customer_id: int | None = None,
) -> pd.DataFrame:
    """
    Returns service history.
    """

    sql = """
        SELECT

            sh.id,
            sh.customer_id,
            c.name,
            sh.service_type,
            sh.notes,
            sh.service_date

        FROM service_history sh

        INNER JOIN customers c

            ON sh.customer_id = c.id
    """

    params: list[Any] = []

    if customer_id is not None:

        sql += """

        WHERE sh.customer_id=?

        """

        params.append(customer_id)

    sql += """

        ORDER BY sh.service_date DESC

    """

    return dataframe(
        sql,
        tuple(params),
    )


def delete_service_record(
    record_id: int,
):
    execute(
        """
        DELETE

        FROM service_history

        WHERE id=?
        """,
        (record_id,),
    )

# ---------------------------------------------------------
# REPORTING HELPERS
# ---------------------------------------------------------

def customer_service_summary() -> pd.DataFrame:
    """
    Returns one row per customer including the number of
    completed services.
    """

    return dataframe(
        """
        SELECT

            c.id,
            c.name,
            c.address,
            c.service,
            c.last_service,

            COUNT(sh.id) AS total_services

        FROM customers c

        LEFT JOIN service_history sh

            ON c.id = sh.customer_id

        GROUP BY
            c.id,
            c.name,
            c.address,
            c.service,
            c.last_service

        ORDER BY c.name
        """
    )


def customers_without_coordinates() -> pd.DataFrame:
    """
    Returns customers that have not been geocoded.
    """

    return dataframe(
        """
        SELECT *

        FROM customers

        WHERE

            lat IS NULL

        OR

            lng IS NULL

        ORDER BY name
        """
    )


def customers_due_for_service(
    service_days: int = 30,
) -> pd.DataFrame:
    """
    Returns customers whose last service is older than
    the specified number of days.
    """

    return dataframe(
        """
        SELECT *

        FROM customers

        WHERE

            last_service IS NULL

        OR

            CURRENT_DATE -
            CAST(last_service AS DATE) >= ?

        ORDER BY
            last_service,
            name
        """,
        (service_days,),
    )


def dashboard_summary() -> Dict[str, int]:
    """
    Returns dashboard statistics.
    """

    return {
        "customers": customer_count(),
        "active_customers": active_customer_count(),
        "queued_jobs": queued_dispatch_count(),
        "completed_jobs": completed_dispatch_count(),
        "cancelled_jobs": cancelled_dispatch_count(),
    }

# ==========================================================
# COMPLETE JOB
# ==========================================================

def complete_job(

    customer_id,

    technician,

    arrival_time,

    start_time,

    finish_time,

    drive_minutes,

    service_minutes,

    service_type,

    products_used,

    chemical_cost,

    revenue,

    notes,

    weather=None,

    temperature=None,

    gps_lat=None,

    gps_lng=None,

):

    total_minutes = (

        drive_minutes

        + service_minutes

    )

    conn = get_connection()

    conn.execute(

        """
        INSERT INTO service_history
        (

            customer_id,

            technician,

            route_date,

            arrival_time,

            start_time,

            finish_time,

            drive_minutes,

            service_minutes,

            total_minutes,

            service_type,

            products_used,

            chemical_cost,

            revenue,

            notes,

            weather,

            temperature,

            gps_lat,

            gps_lng

        )

        VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)

        """,

        (

            customer_id,

            technician,

            datetime.today().strftime(
                "%Y-%m-%d"
            ),

            arrival_time,

            start_time,

            finish_time,

            drive_minutes,

            service_minutes,

            total_minutes,

            service_type,

            products_used,

            chemical_cost,

            revenue,

            notes,

            weather,

            temperature,

            gps_lat,

            gps_lng,

        ),

    )

    conn.commit()

    conn.close()


# ==========================================================
# NEIGHBORHOODS
# ==========================================================

def get_neighborhoods():

    return dataframe(

        """
        SELECT *

        FROM neighborhoods

        ORDER BY name
        """
    )


def save_neighborhood(

    name,

    center_lat,

    center_lng,

    customer_count,

    average_square_feet,

    average_service_time,

    average_drive_time,

    preferred_day,

    preferred_crew,

    average_revenue,

    production_score,

    efficiency_score,

):

    conn = get_connection()

    conn.execute(

        """
        INSERT INTO neighborhoods
        (

            name,

            center_lat,

            center_lng,

            customer_count,

            average_square_feet,

            average_service_time,

            average_drive_time,

            preferred_day,

            preferred_crew,

            average_revenue,

            production_score,

            efficiency_score

        )

        VALUES

        (?,?,?,?,?,?,?,?,?,?,?,?)

        ON CONFLICT(name)

        DO UPDATE SET

            center_lat=excluded.center_lat,

            center_lng=excluded.center_lng,

            customer_count=excluded.customer_count,

            average_square_feet=excluded.average_square_feet,

            average_service_time=excluded.average_service_time,

            average_drive_time=excluded.average_drive_time,

            preferred_day=excluded.preferred_day,

            preferred_crew=excluded.preferred_crew,

            average_revenue=excluded.average_revenue,

            production_score=excluded.production_score,

            efficiency_score=excluded.efficiency_score

        """,

        (

            name,

            center_lat,

            center_lng,

            customer_count,

            average_square_feet,

            average_service_time,

            average_drive_time,

            preferred_day,

            preferred_crew,

            average_revenue,

            production_score,

            efficiency_score,

        ),

    )

    conn.commit()

    conn.close()


# ---------------------------------------------------------
# LOOKUPS
# ---------------------------------------------------------

def customer_names() -> List[str]:
    """
    Returns customer names.
    """

    df = dataframe(
        """
        SELECT name

        FROM customers

        ORDER BY name
        """
    )

    if df.empty:
        return []

    return df["name"].tolist()


def customer_addresses() -> List[str]:
    """
    Returns customer addresses.
    """

    df = dataframe(
        """
        SELECT address

        FROM customers

        ORDER BY address
        """
    )

    if df.empty:
        return []

    return df["address"].tolist()


# ---------------------------------------------------------
# MAINTENANCE
# ---------------------------------------------------------

def vacuum_database():
    """
    PostgreSQL storage maintenance is managed by Supabase.
    """

    return None


def analyze_database():
    """
    Updates SQLite statistics.
    """

    conn = get_connection()

    try:

        conn.execute("ANALYZE")

    finally:

        conn.close()


def optimize_database():
    """
    Performs routine maintenance.
    """

    analyze_database()
    vacuum_database()


# ---------------------------------------------------------
# RESET
# ---------------------------------------------------------

def clear_dispatch():
    """
    Removes every dispatch job.
    """

    execute(
        """
        DELETE

        FROM dispatch_jobs
        """
    )


def clear_service_history():
    """
    Removes all service history.
    """

    execute(
        """
        DELETE

        FROM service_history
        """
    )


def reset_database():
    """
    Deletes transactional data while preserving customers.
    """

    clear_dispatch()
    clear_service_history()


# ---------------------------------------------------------
# EXPORT HELPERS
# ---------------------------------------------------------

def export_customers() -> pd.DataFrame:
    """
    Returns customers for Excel export.
    """

    return get_customers()


def export_dispatch() -> pd.DataFrame:
    """
    Returns dispatch jobs for Excel export.
    """

    return get_dispatch_jobs()


def export_service_history() -> pd.DataFrame:
    """
    Returns service history for Excel export.
    """

    return get_service_history()


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

def database_health() -> Dict[str, Any]:
    """
    Returns basic database diagnostics.
    """

    return {

        "database": "Supabase PostgreSQL",

        "customers": customer_count(),

        "active_customers": active_customer_count(),

        "dispatch_jobs": dispatch_job_count(),

        "service_records": len(get_service_history()),

        "cached_routes": route_cache_count(),

    }

# ---------------------------------------------------------
# ROUTE CACHE
# ---------------------------------------------------------


def route_hash(address: str) -> str:
    """
    Creates a stable hash for an address.
    """

    if address is None:
        address = ""

    return hashlib.sha256(
        address.strip().upper().encode("utf-8")
    ).hexdigest()


def get_cached_route(
    origin: str,
    destination: str,
):
    """
    Returns cached Google route information.
    """

    return dataframe(
        """
        SELECT *

        FROM route_cache

        WHERE

            origin_hash=?

        AND

            destination_hash=?
        """,
        (
            route_hash(origin),
            route_hash(destination),
        ),
    )


def save_cached_route(
    origin: str,
    destination: str,
    distance_meters: float,
    duration_seconds: float,
    provider: str = "Google",
):
    """
    Saves one route to the cache.
    """

    execute(
        """
        INSERT INTO route_cache
        (
            origin_hash,
            destination_hash,

            origin_address,
            destination_address,

            distance_meters,
            duration_seconds,

            provider
        )

        VALUES
        (
            ?,?,?,?,?,?,?,?
        )

        ON CONFLICT(origin_hash,destination_hash)

        DO UPDATE SET

            distance_meters=excluded.distance_meters,

            duration_seconds=excluded.duration_seconds,

            provider=excluded.provider,

            updated=CURRENT_TIMESTAMP
        """,
        (
            route_hash(origin),
            route_hash(destination),

            origin,
            destination,

            distance_meters,
            duration_seconds,

            provider,
        ),
    )


def clear_route_cache():
    """
    Deletes every cached route.
    """

    execute(
        """
        DELETE FROM route_cache
        """
    )


def route_cache_count() -> int:
    """
    Number of cached routes.
    """

    df = dataframe(
        """
        SELECT COUNT(*) total

        FROM route_cache
        """
    )

    return int(df.iloc[0]["total"])
    
# ==========================================================
# PRODUCTS
# ==========================================================

def create_products_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            product_name TEXT UNIQUE,

            product_type TEXT,

            manufacturer TEXT,

            epa_number TEXT,

            active_ingredient TEXT,

            default_rate REAL,

            rate_unit TEXT,

            notes TEXT

        )
        """
    )

    conn.commit()

    conn.close()


def add_product(
    product_name,
    product_type=None,
    manufacturer=None,
    epa_number=None,
    active_ingredient=None,
    default_rate=None,
    rate_unit=None,
    notes=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT OR IGNORE INTO products
        (
            product_name,
            product_type,
            manufacturer,
            epa_number,
            active_ingredient,
            default_rate,
            rate_unit,
            notes
        )
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            product_name,
            product_type,
            manufacturer,
            epa_number,
            active_ingredient,
            default_rate,
            rate_unit,
            notes,
        ),
    )

    conn.commit()

    conn.close()


def get_products():

    return pd.read_sql_query(
        "SELECT * FROM products ORDER BY product_name",
        get_connection(),
    )


# ==========================================================
# SERVICES
# ==========================================================

def create_services_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS services (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            service_name TEXT UNIQUE,

            category TEXT,

            price REAL,

            description TEXT

        )
        """
    )

    conn.commit()

    conn.close()


def add_service_definition(
    service_name,
    category=None,
    price=None,
    description=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT OR IGNORE INTO services
        (
            service_name,
            category,
            price,
            description
        )
        VALUES (?,?,?,?)
        """,
        (
            service_name,
            category,
            price,
            description,
        ),
    )

    conn.commit()

    conn.close()


def get_services():

    return pd.read_sql_query(
        "SELECT * FROM services ORDER BY service_name",
        get_connection(),
    )


# ==========================================================
# TREATMENT PLANS
# ==========================================================

def create_treatment_plans_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS treatment_plans (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            plan_name TEXT UNIQUE,

            description TEXT,

            frequency TEXT,

            notes TEXT

        )
        """
    )

    conn.commit()

    conn.close()


def add_treatment_plan(
    plan_name,
    description=None,
    frequency=None,
    notes=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT OR IGNORE INTO treatment_plans
        (
            plan_name,
            description,
            frequency,
            notes
        )
        VALUES (?,?,?,?)
        """,
        (
            plan_name,
            description,
            frequency,
            notes,
        ),
    )

    conn.commit()

    conn.close()


def get_treatment_plans():

    return pd.read_sql_query(
        "SELECT * FROM treatment_plans ORDER BY plan_name",
        get_connection(),
    )


# ==========================================================
# CHEMICAL COSTS
# ==========================================================

def create_chemical_costs_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chemical_costs (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            product_name TEXT,

            container_size TEXT,

            unit_cost REAL,

            cost_per_unit REAL,

            vendor TEXT,

            notes TEXT

        )
        """
    )

    conn.commit()

    conn.close()


def add_chemical_cost(
    product_name,
    container_size=None,
    unit_cost=None,
    cost_per_unit=None,
    vendor=None,
    notes=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO chemical_costs
        (
            product_name,
            container_size,
            unit_cost,
            cost_per_unit,
            vendor,
            notes
        )
        VALUES (?,?,?,?,?,?)
        """,
        (
            product_name,
            container_size,
            unit_cost,
            cost_per_unit,
            vendor,
            notes,
        ),
    )

    conn.commit()

    conn.close()


def get_chemical_costs():

    return pd.read_sql_query(
        "SELECT * FROM chemical_costs ORDER BY product_name",
        get_connection(),
    )

# ==========================================================
# PROPERTY DETAILS
# ==========================================================

def create_property_details_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS property_details (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            customer_id INTEGER NOT NULL,

            subdivision TEXT,

            county TEXT,

            lawn_size_class TEXT,

            square_feet REAL,

            turf_type TEXT,

            irrigation TEXT,

            gate_code TEXT,

            special_instructions TEXT,

            notes TEXT,

            FOREIGN KEY(customer_id)
                REFERENCES customers(id)
                ON DELETE CASCADE

        )
        """
    )

    conn.commit()

    conn.close()


# ==========================================================
# BILLING ACCOUNTS
# ==========================================================

def create_billing_accounts_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_accounts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            customer_id INTEGER NOT NULL,

            payment_method TEXT,

            billing_status TEXT,

            balance_due REAL DEFAULT 0,

            last_payment_date TEXT,

            account_notes TEXT,

            FOREIGN KEY(customer_id)
                REFERENCES customers(id)
                ON DELETE CASCADE

        )
        """
    )

    conn.commit()

    conn.close()


# ==========================================================
# CUSTOMER NOTES
# ==========================================================

def create_customer_notes_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_notes (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            customer_id INTEGER NOT NULL,

            note_date TEXT,

            note_type TEXT,

            note TEXT,

            created_by TEXT,

            FOREIGN KEY(customer_id)
                REFERENCES customers(id)
                ON DELETE CASCADE

        )
        """
    )

    conn.commit()

    conn.close()

# ==========================================================
# PROPERTY DETAILS
# ==========================================================

def add_property_details(
    customer_id,
    subdivision=None,
    county=None,
    lawn_size_class=None,
    square_feet=None,
    turf_type=None,
    irrigation=None,
    gate_code=None,
    special_instructions=None,
    notes=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO property_details
        (
            customer_id,
            subdivision,
            county,
            lawn_size_class,
            square_feet,
            turf_type,
            irrigation,
            gate_code,
            special_instructions,
            notes
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            subdivision,
            county,
            lawn_size_class,
            square_feet,
            turf_type,
            irrigation,
            gate_code,
            special_instructions,
            notes,
        ),
    )

    conn.commit()
    conn.close()


def get_property_details(customer_id):

    return dataframe(
        """
        SELECT *
        FROM property_details
        WHERE customer_id=?
        """,
        (customer_id,),
    )


def update_property_details(customer_id, **kwargs):

    if not kwargs:
        return

    fields = ", ".join(f"{k}=?" for k in kwargs.keys())

    values = list(kwargs.values())
    values.append(customer_id)

    execute(
        f"""
        UPDATE property_details
        SET {fields}
        WHERE customer_id=?
        """,
        tuple(values),
    )


# ==========================================================
# BILLING ACCOUNT
# ==========================================================

def add_billing_account(
    customer_id,
    payment_method=None,
    billing_status=None,
    balance_due=0,
    last_payment_date=None,
    account_notes=None,
):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO billing_accounts
        (
            customer_id,
            payment_method,
            billing_status,
            balance_due,
            last_payment_date,
            account_notes
        )
        VALUES (?,?,?,?,?,?)
        """,
        (
            customer_id,
            payment_method,
            billing_status,
            balance_due,
            last_payment_date,
            account_notes,
        ),
    )

    conn.commit()
    conn.close()


def get_billing_account(customer_id):

    return dataframe(
        """
        SELECT *
        FROM billing_accounts
        WHERE customer_id=?
        """,
        (customer_id,),
    )


def update_billing_account(customer_id, **kwargs):

    if not kwargs:
        return

    fields = ", ".join(f"{k}=?" for k in kwargs.keys())

    values = list(kwargs.values())
    values.append(customer_id)

    execute(
        f"""
        UPDATE billing_accounts
        SET {fields}
        WHERE customer_id=?
        """,
        tuple(values),
    )


# ==========================================================
# CUSTOMER NOTES
# ==========================================================

def add_customer_note(
    customer_id,
    note,
    note_type="General",
    created_by="System",
    note_date=None,
):

    if note_date is None:

        from datetime import datetime

        note_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    execute(
        """
        INSERT INTO customer_notes
        (
            customer_id,
            note_date,
            note_type,
            note,
            created_by
        )
        VALUES (?,?,?,?,?)
        """,
        (
            customer_id,
            note_date,
            note_type,
            note,
            created_by,
        ),
    )


def get_customer_notes(customer_id):

    return dataframe(
        """
        SELECT *
        FROM customer_notes
        WHERE customer_id=?
        ORDER BY note_date DESC
        """,
        (customer_id,),
    )


def delete_customer_note(note_id):

    execute(
        """
        DELETE FROM customer_notes
        WHERE id=?
        """,
        (note_id,),
    )

# ==========================================================
# EMPLOYEES
# ==========================================================

def create_employees_table():

    execute("""
        CREATE TABLE IF NOT EXISTS employees (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            first_name TEXT,

            last_name TEXT,

            phone TEXT,

            email TEXT,

            hire_date TEXT,

            active INTEGER DEFAULT 1

        )
    """)


# ==========================================================
# EQUIPMENT
# ==========================================================

def create_equipment_table():

    execute("""
        CREATE TABLE IF NOT EXISTS equipment (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            equipment_name TEXT,

            serial_number TEXT,

            purchase_date TEXT,

            purchase_price REAL,

            service_interval_hours REAL,

            current_hours REAL DEFAULT 0,

            active INTEGER DEFAULT 1

        )
    """)


# ==========================================================
# ROUTES
# ==========================================================

def create_routes_table():

    execute("""
        CREATE TABLE IF NOT EXISTS routes (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            route_date TEXT,

            technician_id INTEGER,

            route_name TEXT,

            total_distance REAL,

            total_time REAL,

            status TEXT,

            FOREIGN KEY(technician_id)
                REFERENCES employees(id)

        )
    """)


# ==========================================================
# ROUTE STOPS
# ==========================================================

def create_route_stops_table():

    execute("""
        CREATE TABLE IF NOT EXISTS route_stops (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            route_id INTEGER,

            customer_id INTEGER,

            stop_order INTEGER,

            arrival_time TEXT,

            departure_time TEXT,

            completed INTEGER DEFAULT 0,

            FOREIGN KEY(route_id)
                REFERENCES routes(id),

            FOREIGN KEY(customer_id)
                REFERENCES customers(id)

        )
    """)

    
# ---------------------------------------------------------
# STARTUP
# ---------------------------------------------------------

init_db()

# ==========================================================
# EXTEND DATABASE INITIALIZATION
# ==========================================================

#
# Add these four lines to the END of your existing init_db()
# function, just before it returns:
#
#     create_products_table()
#     create_services_table()
#     create_treatment_plans_table()
#     create_chemical_costs_table()
#


# ==========================================================
# CRM V3 EXTENSIONS
# ==========================================================
# These extensions preserve the existing Supabase/PostgreSQL database layer
# while adding customer categories, crews, persistent dispatch manifests,
# field-status timestamps, and saved table preferences.

CUSTOMER_TYPES = (
    "Residential",
    "Small Commercial",
    "Commercial",
)


def _column_names(table_name: str) -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def _add_column_if_missing(
    table_name: str,
    column_name: str,
    definition: str,
):
    if column_name in _column_names(table_name):
        return
    execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
    )


def init_extended_schema():
    # Customer organization fields.
    _add_column_if_missing(
        "customers",
        "customer_type",
        "TEXT DEFAULT 'Residential'",
    )
    _add_column_if_missing(
        "customers",
        "account_name",
        "TEXT",
    )

    # Dispatch field-status / assignment fields.
    for name, definition in {
        "arrived_time": "TEXT",
        "completed_time": "TEXT",
        "dispatch_id": "INTEGER",
        "crew_id": "INTEGER",
        "route_number": "INTEGER",
        "stop_number": "INTEGER",
    }.items():
        _add_column_if_missing(
            "dispatch_jobs",
            name,
            definition,
        )

    execute(
        """
        UPDATE customers
        SET customer_type='Residential'
        WHERE customer_type IS NULL
           OR TRIM(customer_type)=''
        """
    )

    execute(
        """
        CREATE TABLE IF NOT EXISTS crews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_name TEXT NOT NULL UNIQUE,
            email TEXT,
            phone TEXT,
            active INTEGER DEFAULT 1,
            notes TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    execute(
        """
        CREATE TABLE IF NOT EXISTS dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatch_date TEXT NOT NULL,
            crew_id INTEGER,
            route_number INTEGER,
            status TEXT DEFAULT 'ready',
            dispatch_token TEXT UNIQUE,
            sent_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            notes TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(crew_id) REFERENCES crews(id)
        )
        """
    )

    execute(
        """
        CREATE TABLE IF NOT EXISTS table_preferences (
            table_name TEXT PRIMARY KEY,
            column_order_json TEXT,
            hidden_columns_json TEXT,
            sort_json TEXT,
            updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customers_customer_type
        ON customers(customer_type)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dispatch_jobs_dispatch_id
        ON dispatch_jobs(dispatch_id)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dispatch_jobs_crew_id
        ON dispatch_jobs(crew_id)
        """
    )


def add_customer(
    customer_number=None,
    name=None,
    address=None,
    street_address=None,
    city=None,
    state=None,
    zip=None,
    county=None,
    phone=None,
    email=None,
    text_phone=None,
    square_feet=None,
    turf_type=None,
    irrigation=None,
    payment_method=None,
    quote=None,
    active=1,
    special_instructions=None,
    lat=None,
    lng=None,
    neighborhood=None,
    cluster_id=0,
    distance_from_cluster=0,
    service=None,
    last_service=None,
    customer_type="Residential",
    account_name=None,
):
    """Add a customer while remaining compatible with legacy callers."""
    if not name or not str(name).strip():
        raise ValueError("Customer name is required.")

    if customer_type not in CUSTOMER_TYPES:
        raise ValueError(
            "customer_type must be Residential, Small Commercial, or Commercial."
        )

    if not address:
        parts = [street_address, city, state, zip]
        address = ", ".join(
            str(value).strip()
            for value in parts
            if value not in (None, "")
        )

    conn = get_connection()
    try:
        if customer_number is None or not str(customer_number).strip():
            customer_number = get_next_customer_number(conn)

        cursor = conn.execute(
            """
            INSERT INTO customers (
                customer_number,
                name,
                account_name,
                customer_type,
                address,
                street_address,
                city,
                state,
                zip,
                county,
                phone,
                email,
                text_phone,
                square_feet,
                turf_type,
                irrigation,
                payment_method,
                quote,
                active,
                special_instructions,
                lat,
                lng,
                neighborhood,
                cluster_id,
                distance_from_cluster,
                service,
                last_service
            )
            VALUES (
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?
            )
            """,
            (
                customer_number,
                str(name).strip(),
                account_name,
                customer_type,
                address,
                street_address,
                city,
                state,
                zip,
                county,
                phone,
                email,
                text_phone,
                square_feet,
                turf_type,
                irrigation,
                payment_method,
                quote,
                int(bool(active)),
                special_instructions,
                lat,
                lng,
                neighborhood,
                cluster_id,
                distance_from_cluster,
                service,
                last_service,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_customers_by_type(
    customer_type: str,
    active_only: bool = True,
) -> pd.DataFrame:
    if customer_type not in CUSTOMER_TYPES:
        raise ValueError(f"Unknown customer type: {customer_type}")

    sql = """
        SELECT *
        FROM customers
        WHERE customer_type=?
    """
    params = [customer_type]

    if active_only:
        sql += " AND active=1"

    sql += " ORDER BY name"
    return dataframe(sql, tuple(params))


def set_customer_type(
    customer_id: int,
    customer_type: str,
):
    if customer_type not in CUSTOMER_TYPES:
        raise ValueError(f"Unknown customer type: {customer_type}")
    update_customer(
        int(customer_id),
        customer_type=customer_type,
    )


def get_queued_dispatch_jobs(
    customer_type: str | None = None,
) -> pd.DataFrame:
    """Every queued job is Dispatch-ready regardless of scheduled_date."""
    sql = """
        SELECT
            dj.*,
            c.customer_number,
            c.name,
            c.account_name,
            COALESCE(c.customer_type, 'Residential') AS customer_type,
            c.address,
            c.street_address,
            c.city,
            c.state,
            c.zip,
            c.phone,
            c.email,
            c.text_phone,
            c.square_feet,
            c.turf_type,
            c.special_instructions,
            c.lat,
            c.lng,
            c.neighborhood,
            c.service,
            COALESCE(NULLIF(dj.treatment_name, ''), c.service) AS service_name
        FROM dispatch_jobs dj
        INNER JOIN customers c
            ON c.id=dj.customer_id
        WHERE LOWER(COALESCE(dj.status, ''))='queued'
          AND COALESCE(c.active, 1)=1
    """
    params: list[Any] = []

    if customer_type not in (None, "", "All"):
        sql += " AND COALESCE(c.customer_type, 'Residential')=?"
        params.append(customer_type)

    sql += """
        ORDER BY
            CASE WHEN dj.scheduled_date IS NULL OR dj.scheduled_date='' THEN 1 ELSE 0 END,
            dj.scheduled_date,
            c.name
    """
    return dataframe(sql, tuple(params))


# -----------------------------
# Crew management
# -----------------------------

def create_crew(
    crew_name: str,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
    active: bool = True,
) -> int:
    if not crew_name or not str(crew_name).strip():
        raise ValueError("Crew name is required.")

    return execute(
        """
        INSERT INTO crews (
            crew_name, email, phone, active, notes
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(crew_name).strip(),
            email,
            phone,
            int(bool(active)),
            notes,
        ),
    )


def get_crews(
    active_only: bool = True,
) -> pd.DataFrame:
    sql = "SELECT * FROM crews"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY crew_name"
    return dataframe(sql)


def update_crew(
    crew_id: int,
    **kwargs,
):
    allowed = {
        "crew_name",
        "email",
        "phone",
        "active",
        "notes",
    }
    updates = {
        key: value
        for key, value in kwargs.items()
        if key in allowed
    }
    if not updates:
        return

    if "active" in updates:
        updates["active"] = int(bool(updates["active"]))

    fields = [f"{key}=?" for key in updates]
    values = list(updates.values())
    fields.append("updated=CURRENT_TIMESTAMP")
    values.append(int(crew_id))

    execute(
        f"UPDATE crews SET {', '.join(fields)} WHERE id=?",
        tuple(values),
    )


# -----------------------------
# Persistent dispatch manifests
# -----------------------------

def _new_dispatch_token() -> str:
    import secrets
    return secrets.token_urlsafe(24)


def create_dispatch(
    dispatch_date: str,
    crew_id: int | None,
    route_number: int | None = None,
    status: str = "ready",
    notes: str | None = None,
    dispatch_token: str | None = None,
) -> int:
    token = dispatch_token or _new_dispatch_token()
    return execute(
        """
        INSERT INTO dispatches (
            dispatch_date,
            crew_id,
            route_number,
            status,
            dispatch_token,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            dispatch_date,
            crew_id,
            route_number,
            status,
            token,
            notes,
        ),
    )


def get_dispatch(
    dispatch_id: int,
) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                d.*,
                c.crew_name,
                c.email AS crew_email,
                c.phone AS crew_phone
            FROM dispatches d
            LEFT JOIN crews c ON c.id=d.crew_id
            WHERE d.id=?
            """,
            (int(dispatch_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_dispatch_by_token(
    dispatch_token: str,
) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                d.*,
                c.crew_name,
                c.email AS crew_email,
                c.phone AS crew_phone
            FROM dispatches d
            LEFT JOIN crews c ON c.id=d.crew_id
            WHERE d.dispatch_token=?
            """,
            (dispatch_token,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_dispatches(
    dispatch_date: str | None = None,
) -> pd.DataFrame:
    sql = """
        SELECT
            d.*,
            c.crew_name,
            c.email AS crew_email,
            c.phone AS crew_phone,
            COUNT(dj.id) AS stop_count,
            SUM(
                CASE WHEN LOWER(COALESCE(dj.status,''))='completed'
                     THEN 1 ELSE 0 END
            ) AS completed_count
        FROM dispatches d
        LEFT JOIN crews c ON c.id=d.crew_id
        LEFT JOIN dispatch_jobs dj ON dj.dispatch_id=d.id
    """
    params: list[Any] = []
    if dispatch_date:
        sql += " WHERE d.dispatch_date=?"
        params.append(dispatch_date)
    sql += """
        GROUP BY d.id, c.crew_name, c.email, c.phone
        ORDER BY d.dispatch_date DESC,
                 COALESCE(d.route_number, 9999),
                 c.crew_name
    """
    return dataframe(sql, tuple(params))


def assign_job_to_dispatch(
    job_id: int,
    dispatch_id: int,
    crew_id: int | None,
    route_number: int,
    stop_number: int,
):
    execute(
        """
        UPDATE dispatch_jobs
        SET
            dispatch_id=?,
            crew_id=?,
            route_number=?,
            stop_number=?,
            status='dispatched'
        WHERE id=?
        """,
        (
            int(dispatch_id),
            crew_id,
            int(route_number),
            int(stop_number),
            int(job_id),
        ),
    )


def get_dispatch_jobs_for_manifest(
    dispatch_id: int,
) -> pd.DataFrame:
    return dataframe(
        """
        SELECT
            dj.*,
            c.customer_number,
            c.name,
            c.account_name,
            COALESCE(c.customer_type, 'Residential') AS customer_type,
            c.address,
            c.street_address,
            c.city,
            c.state,
            c.zip,
            c.phone,
            c.email,
            c.text_phone,
            c.square_feet,
            c.special_instructions,
            c.lat,
            c.lng,
            c.service,
            d.dispatch_date,
            d.dispatch_token,
            d.status AS dispatch_status,
            cr.crew_name
        FROM dispatch_jobs dj
        INNER JOIN customers c ON c.id=dj.customer_id
        INNER JOIN dispatches d ON d.id=dj.dispatch_id
        LEFT JOIN crews cr ON cr.id=dj.crew_id
        WHERE dj.dispatch_id=?
        ORDER BY dj.stop_number, dj.id
        """,
        (int(dispatch_id),),
    )


def mark_dispatch_sent(
    dispatch_id: int,
):
    execute(
        """
        UPDATE dispatches
        SET status='sent',
            sent_at=CURRENT_TIMESTAMP,
            updated=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (int(dispatch_id),),
    )


def mark_job_arrived(
    job_id: int,
):
    execute(
        """
        UPDATE dispatch_jobs
        SET status='in_progress',
            arrived_time=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (int(job_id),),
    )

    execute(
        """
        UPDATE dispatches
        SET status='in_progress',
            started_at=COALESCE(started_at, CURRENT_TIMESTAMP),
            updated=CURRENT_TIMESTAMP
        WHERE id=(
            SELECT dispatch_id
            FROM dispatch_jobs
            WHERE id=?
        )
        """,
        (int(job_id),),
    )


def mark_job_completed(
    job_id: int,
):
    execute(
        """
        UPDATE dispatch_jobs
        SET status='completed',
            completed_time=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (int(job_id),),
    )

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT dispatch_id FROM dispatch_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()

        dispatch_id = row[0] if row else None

        if dispatch_id is not None:
            remaining = conn.execute(
                """
                SELECT COUNT(*)
                FROM dispatch_jobs
                WHERE dispatch_id=?
                  AND LOWER(COALESCE(status,'')) NOT IN (
                      'completed', 'cancelled', 'canceled'
                  )
                """,
                (int(dispatch_id),),
            ).fetchone()[0]

            if int(remaining) == 0:
                conn.execute(
                    """
                    UPDATE dispatches
                    SET status='completed',
                        completed_at=CURRENT_TIMESTAMP,
                        updated=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (int(dispatch_id),),
                )
                conn.commit()
    finally:
        conn.close()


def queue_dispatch_job(
    job_id: int,
):
    execute(
        """
        UPDATE dispatch_jobs
        SET status='queued',
            dispatch_id=NULL,
            crew_id=NULL,
            route_number=NULL,
            stop_number=NULL,
            arrived_time=NULL,
            completed_time=NULL
        WHERE id=?
        """,
        (int(job_id),),
    )


def clear_dispatch_manifest(
    dispatch_id: int,
    requeue_unfinished: bool = True,
):
    conn = get_connection()
    try:
        if requeue_unfinished:
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET
                    status=CASE
                        WHEN LOWER(COALESCE(status,'')) IN (
                            'completed','cancelled','canceled'
                        ) THEN status
                        ELSE 'queued'
                    END,
                    dispatch_id=NULL,
                    crew_id=NULL,
                    route_number=NULL,
                    stop_number=NULL,
                    arrived_time=CASE
                        WHEN LOWER(COALESCE(status,''))='completed'
                        THEN arrived_time ELSE NULL END,
                    completed_time=CASE
                        WHEN LOWER(COALESCE(status,''))='completed'
                        THEN completed_time ELSE NULL END
                WHERE dispatch_id=?
                """,
                (int(dispatch_id),),
            )
        else:
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET dispatch_id=NULL,
                    crew_id=NULL,
                    route_number=NULL,
                    stop_number=NULL
                WHERE dispatch_id=?
                """,
                (int(dispatch_id),),
            )

        conn.execute(
            "DELETE FROM dispatches WHERE id=?",
            (int(dispatch_id),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# Persistent table preferences
# -----------------------------

def save_table_preferences(
    table_name: str,
    column_order=None,
    hidden_columns=None,
    sort_state=None,
):
    import json
    execute(
        """
        INSERT INTO table_preferences (
            table_name,
            column_order_json,
            hidden_columns_json,
            sort_json,
            updated
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(table_name)
        DO UPDATE SET
            column_order_json=excluded.column_order_json,
            hidden_columns_json=excluded.hidden_columns_json,
            sort_json=excluded.sort_json,
            updated=CURRENT_TIMESTAMP
        """,
        (
            table_name,
            json.dumps(list(column_order or [])),
            json.dumps(list(hidden_columns or [])),
            json.dumps(sort_state or {}),
        ),
    )


def get_table_preferences(
    table_name: str,
) -> Dict[str, Any]:
    import json
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                column_order_json,
                hidden_columns_json,
                sort_json
            FROM table_preferences
            WHERE table_name=?
            """,
            (table_name,),
        ).fetchone()

        if row is None:
            return {
                "column_order": [],
                "hidden_columns": [],
                "sort": {},
            }

        def load(value, fallback):
            if value in (None, ""):
                return fallback
            try:
                return json.loads(value)
            except Exception:
                return fallback

        return {
            "column_order": load(row[0], []),
            "hidden_columns": load(row[1], []),
            "sort": load(row[2], {}),
        }
    finally:
        conn.close()


# Apply CRM v3 schema upgrades after the legacy schema has been initialized.
init_extended_schema()
