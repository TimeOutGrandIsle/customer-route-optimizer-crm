from __future__ import annotations

from datetime import date, timedelta
from html import escape
from email.message import EmailMessage
import smtplib
import ssl

import pandas as pd
import streamlit as st

import base64
from pathlib import Path

from data.database import dataframe, execute, get_connection, get_setting


def ensure_invoice_tables() -> None:
    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE,
                customer_id INTEGER NOT NULL,
                invoice_date TEXT NOT NULL,
                due_date TEXT,
                status TEXT DEFAULT 'Draft',
                subtotal REAL DEFAULT 0,
                tax REAL DEFAULT 0,
                total REAL DEFAULT 0,
                notes TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id)
                    REFERENCES customers(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS invoice_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                source_type TEXT,
                source_id INTEGER,
                description TEXT NOT NULL,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                FOREIGN KEY(invoice_id)
                    REFERENCES invoices(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT,
                reference TEXT,
                notes TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(invoice_id)
                    REFERENCES invoices(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_invoice_lines_source
            ON invoice_lines(source_type, source_id);
            """
        )

        invoice_columns = {
            row[1]
            for row in cur.execute(
                "PRAGMA table_info(invoices)"
            ).fetchall()
        }

        invoice_fields = {
            "sent_at": "TEXT",
            "delivery_status": "TEXT",
            "delivery_error": "TEXT",
        }

        for column, column_type in invoice_fields.items():
            if column not in invoice_columns:
                cur.execute(
                    f"ALTER TABLE invoices ADD COLUMN {column} {column_type}"
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def next_invoice_number() -> str:
    ensure_invoice_tables()

    year = date.today().year

    rows = dataframe(
        """
        SELECT invoice_number
        FROM invoices
        WHERE invoice_number LIKE ?
        ORDER BY invoice_number DESC
        LIMIT 1
        """,
        (f"INV-{year}-%",),
    )

    if rows.empty:
        return f"INV-{year}-0001"

    last = str(rows.iloc[0]["invoice_number"])

    try:
        number = int(last.rsplit("-", 1)[1]) + 1
    except Exception:
        number = 1

    return f"INV-{year}-{number:04d}"


def get_ready_to_invoice() -> pd.DataFrame:
    ensure_invoice_tables()

    return dataframe(
        """
        SELECT
            ar.id AS application_id,
            ar.application_date,
            ar.customer_id,
            c.name AS customer_name,
            c.customer_number,
            c.address,
            c.quote,
            td.name AS treatment,
            ar.property_square_feet,
            ar.acres,
            COALESCE(c.quote, 0) AS default_price
        FROM application_records ar
        INNER JOIN customers c
            ON c.id=ar.customer_id
        INNER JOIN treatment_definitions td
            ON td.id=ar.treatment_id
        LEFT JOIN invoice_lines il
            ON il.source_type='application'
            AND il.source_id=ar.id
        LEFT JOIN treatment_events te
            ON te.id=ar.treatment_event_id
        LEFT JOIN invoice_lines dispatch_il
            ON dispatch_il.source_type='dispatch'
            AND dispatch_il.source_id=te.dispatch_job_id
        WHERE il.id IS NULL
          AND dispatch_il.id IS NULL
        ORDER BY ar.application_date DESC, c.name
        """
    )


def get_invoices(status: str | None = None) -> pd.DataFrame:
    ensure_invoice_tables()

    sql = """
        SELECT
            i.id,
            i.invoice_number,
            i.invoice_date,
            i.due_date,
            i.status,
            i.customer_id,
            c.name AS customer_name,
            c.address,
            c.email,
            i.subtotal,
            i.tax,
            i.total,
            i.sent_at,
            i.delivery_status,
            i.delivery_error,
            COALESCE(SUM(p.amount), 0) AS paid,
            i.total - COALESCE(SUM(p.amount), 0) AS balance,
            i.notes
        FROM invoices i
        INNER JOIN customers c
            ON c.id=i.customer_id
        LEFT JOIN payments p
            ON p.invoice_id=i.id
    """

    params = []

    if status and status != "All":
        sql += " WHERE i.status=? "
        params.append(status)

    sql += """
        GROUP BY
            i.id,
            i.invoice_number,
            i.invoice_date,
            i.due_date,
            i.status,
            i.customer_id,
            c.name,
            c.address,
            c.email,
            i.subtotal,
            i.tax,
            i.total,
            i.sent_at,
            i.delivery_status,
            i.delivery_error,
            i.notes
        ORDER BY i.invoice_date DESC, i.id DESC
    """

    return dataframe(sql, params)


def get_invoice_lines(invoice_id: int) -> pd.DataFrame:
    ensure_invoice_tables()

    return dataframe(
        """
        SELECT
            id,
            source_type,
            source_id,
            description,
            quantity,
            unit_price,
            line_total
        FROM invoice_lines
        WHERE invoice_id=?
        ORDER BY id
        """,
        (int(invoice_id),),
    )


def get_payments(invoice_id: int) -> pd.DataFrame:
    ensure_invoice_tables()

    return dataframe(
        """
        SELECT
            id,
            payment_date,
            amount,
            payment_method,
            reference,
            notes
        FROM payments
        WHERE invoice_id=?
        ORDER BY payment_date, id
        """,
        (int(invoice_id),),
    )


def create_invoice(
    application_ids: list[int],
    invoice_date: date,
    due_date: date | None,
    notes: str = "",
    subtotal_override: float | None = None,
    tax_override: float | None = None,
) -> int:
    ensure_invoice_tables()

    if not application_ids:
        raise ValueError("Select at least one completed application.")

    placeholders = ",".join("?" for _ in application_ids)

    ready = dataframe(
        f"""
        SELECT *
        FROM (
            SELECT
                ar.id AS application_id,
                ar.application_date,
                ar.customer_id,
                c.quote,
                td.name AS treatment,
                COALESCE(c.quote, 0) AS default_price
            FROM application_records ar
            INNER JOIN customers c
                ON c.id=ar.customer_id
            INNER JOIN treatment_definitions td
                ON td.id=ar.treatment_id
            LEFT JOIN invoice_lines il
                ON il.source_type='application'
                AND il.source_id=ar.id
            LEFT JOIN treatment_events te
                ON te.id=ar.treatment_event_id
            LEFT JOIN invoice_lines dispatch_il
                ON dispatch_il.source_type='dispatch'
                AND dispatch_il.source_id=te.dispatch_job_id
            WHERE il.id IS NULL
              AND dispatch_il.id IS NULL
        )
        WHERE application_id IN ({placeholders})
        ORDER BY application_date
        """,
        tuple(int(x) for x in application_ids),
    )

    if ready.empty:
        raise ValueError("Selected work is already invoiced.")

    customer_ids = ready["customer_id"].drop_duplicates().tolist()

    if len(customer_ids) > 1:
        raise ValueError("Create invoices for one customer at a time.")

    default_subtotal = float(
        ready["default_price"].fillna(0).sum()
    )

    subtotal = (
        float(subtotal_override)
        if subtotal_override is not None
        else default_subtotal
    )

    tax = (
        float(tax_override)
        if tax_override is not None
        else 0.0
    )

    total = subtotal + tax

    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO invoices (
                invoice_number,
                customer_id,
                invoice_date,
                due_date,
                status,
                subtotal,
                tax,
                total,
                notes
            )
            VALUES (?, ?, ?, ?, 'Draft', ?, ?, ?, ?)
            """,
            (
                next_invoice_number(),
                int(customer_ids[0]),
                invoice_date.isoformat(),
                due_date.isoformat() if due_date else None,
                subtotal,
                tax,
                total,
                notes,
            ),
        )

        invoice_id = cur.lastrowid

        for _, row in ready.iterrows():
            price = float(row["default_price"] or 0)

            cur.execute(
                """
                INSERT INTO invoice_lines (
                    invoice_id,
                    source_type,
                    source_id,
                    description,
                    quantity,
                    unit_price,
                    line_total
                )
                VALUES (?, 'application', ?, ?, 1, ?, ?)
                """,
                (
                    invoice_id,
                    int(row["application_id"]),
                    f"{row['treatment']} - {row['application_date']}",
                    price,
                    price,
                ),
            )

        conn.commit()

        return int(invoice_id)

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def update_invoice_status(invoice_id: int, status: str) -> None:
    ensure_invoice_tables()

    execute(
        """
        UPDATE invoices
        SET status=?, updated=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (status, int(invoice_id)),
    )


def add_payment(
    invoice_id: int,
    payment_date: date,
    amount: float,
    payment_method: str = "",
    reference: str = "",
    notes: str = "",
) -> None:
    ensure_invoice_tables()

    execute(
        """
        INSERT INTO payments (
            invoice_id,
            payment_date,
            amount,
            payment_method,
            reference,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(invoice_id),
            payment_date.isoformat(),
            float(amount),
            payment_method,
            reference,
            notes,
        ),
    )

    invoices = get_invoices()
    invoice = invoices[invoices["id"] == int(invoice_id)]

    if invoice.empty:
        return

    balance = float(invoice.iloc[0]["balance"] or 0)

    if balance <= 0:
        update_invoice_status(invoice_id, "Paid")
    else:
        update_invoice_status(invoice_id, "Partially Paid")

def _setting_enabled(key: str, default: bool = False) -> bool:
    value = get_setting(
        key,
        "true" if default else "false",
    )
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def get_invoice_for_application(application_id: int) -> dict | None:
    """Return the invoice already linked to an application, if any."""
    ensure_invoice_tables()

    rows = dataframe(
        """
        SELECT
            i.id,
            i.invoice_number,
            i.customer_id,
            i.invoice_date,
            i.due_date,
            i.status,
            i.subtotal,
            i.tax,
            i.total,
            i.sent_at,
            i.delivery_status,
            i.delivery_error
        FROM invoice_lines il
        INNER JOIN invoices i
            ON i.id=il.invoice_id
        WHERE il.source_type='application'
          AND il.source_id=?
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (int(application_id),),
    )

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def get_completed_application_for_invoice(application_id: int) -> dict | None:
    """Load the completed application and customer billing details."""
    ensure_invoice_tables()

    rows = dataframe(
        """
        SELECT
            ar.id AS application_id,
            ar.application_date,
            ar.customer_id,
            c.name AS customer_name,
            c.email,
            COALESCE(c.quote, 0) AS default_price,
            td.name AS treatment
        FROM application_records ar
        INNER JOIN customers c
            ON c.id=ar.customer_id
        INNER JOIN treatment_definitions td
            ON td.id=ar.treatment_id
        WHERE ar.id=?
        LIMIT 1
        """,
        (int(application_id),),
    )

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def _email_config() -> dict:
    config = st.secrets.get("email", {})

    required = {
        "smtp_server",
        "smtp_port",
        "username",
        "password",
    }

    missing = sorted(
        key
        for key in required
        if config.get(key) in (None, "")
    )

    if missing:
        raise RuntimeError(
            "Missing Streamlit [email] setting(s): "
            + ", ".join(missing)
        )

    return {
        "smtp_server": str(config.get("smtp_server")).strip(),
        "smtp_port": int(config.get("smtp_port")),
        "username": str(config.get("username")).strip(),
        "password": str(config.get("password")),
        "from_name": str(
            config.get("from_name")
            or "Time Out Lawncare"
        ).strip(),
    }


def _record_invoice_delivery(
    invoice_id: int,
    *,
    status: str,
    error: str = "",
    mark_sent: bool = False,
) -> None:
    if mark_sent:
        execute(
            """
            UPDATE invoices
            SET
                status='Sent',
                sent_at=CURRENT_TIMESTAMP,
                delivery_status=?,
                delivery_error=?,
                updated=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                status,
                error or None,
                int(invoice_id),
            ),
        )
    else:
        execute(
            """
            UPDATE invoices
            SET
                delivery_status=?,
                delivery_error=?,
                updated=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                status,
                error or None,
                int(invoice_id),
            ),
        )


def send_invoice_email(invoice_id: int) -> dict:
    """Send one invoice through the Gmail SMTP account in Streamlit secrets."""
    ensure_invoice_tables()

    invoices = get_invoices()
    match = invoices[invoices["id"] == int(invoice_id)]

    if match.empty:
        raise ValueError("Invoice was not found.")

    invoice = match.iloc[0]
    recipient = str(invoice.get("email") or "").strip()

    if not recipient:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Missing Email",
            error="Customer does not have an email address.",
        )
        return {
            "sent": False,
            "reason": "missing_email",
            "invoice_id": int(invoice_id),
        }

    total = float(invoice.get("total") or 0)

    if total <= 0:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Review Price",
            error="Invoice total must be greater than zero before automatic email delivery.",
        )
        return {
            "sent": False,
            "reason": "nonpositive_total",
            "invoice_id": int(invoice_id),
        }

    config = _email_config()
    invoice_html = build_invoice_html(int(invoice_id))
    invoice_number = str(invoice.get("invoice_number") or f"Invoice {invoice_id}")

    message = EmailMessage()
    message["Subject"] = f"Time Out Lawncare Invoice {invoice_number}"
    message["From"] = (
        f"{config['from_name']} <{config['username']}>"
    )
    message["To"] = recipient

    message.set_content(
        "Thank you for choosing Time Out Lawncare.\n\n"
        f"Your invoice {invoice_number} for ${total:,.2f} is attached.\n\n"
        "Time Out Lawncare\n"
        "601-941-3586\n"
        "timeoutlawncare@gmail.com"
    )

    message.add_attachment(
        invoice_html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=f"{invoice_number}.html",
    )

    try:
        context = ssl.create_default_context()

        # Python 3.13+ enables VERIFY_X509_STRICT by default.
        # Some otherwise trusted Windows/network CA chains do not mark
        # Basic Constraints as critical and are rejected only by this
        # stricter flag. Clear only VERIFY_X509_STRICT so certificate
        # validation and hostname checking remain enabled.
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT

        with smtplib.SMTP(
            config["smtp_server"],
            config["smtp_port"],
            timeout=30,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(
                config["username"],
                config["password"],
            )
            smtp.send_message(message)

    except Exception as exc:
        _record_invoice_delivery(
            invoice_id,
            status="Failed",
            error=str(exc)[:1000],
        )
        raise

    _record_invoice_delivery(
        invoice_id,
        status="Delivered to SMTP",
        mark_sent=True,
    )

    return {
        "sent": True,
        "invoice_id": int(invoice_id),
        "recipient": recipient,
        "invoice_number": invoice_number,
    }


def create_invoice_for_completed_application(
    application_id: int,
    *,
    send_if_enabled: bool = True,
) -> dict:
    """
    Idempotently create an invoice for one completed application.

    If automatic sending is enabled in Settings, send it immediately when the
    customer has an email address and the invoice total is greater than zero.
    """
    existing = get_invoice_for_application(
        int(application_id)
    )

    if existing:
        return {
            "created": False,
            "invoice_id": int(existing["id"]),
            "sent": str(existing.get("status") or "").lower() == "sent",
            "reason": "already_invoiced",
        }

    application = get_completed_application_for_invoice(
        int(application_id)
    )

    if not application:
        return {
            "created": False,
            "sent": False,
            "reason": "application_not_found",
        }

    invoice_id = create_invoice(
        application_ids=[int(application_id)],
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        notes="Thank you for your business.",
    )

    result = {
        "created": True,
        "invoice_id": int(invoice_id),
        "sent": False,
        "reason": "draft_created",
    }

    if not send_if_enabled:
        return result

    if not _setting_enabled(
        "auto_send_invoices",
        default=False,
    ):
        result["reason"] = "auto_send_disabled"
        return result

    recipient = str(
        application.get("email")
        or ""
    ).strip()

    if not recipient:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Missing Email",
            error="Customer does not have an email address.",
        )
        result["reason"] = "missing_email"
        return result

    price = float(
        application.get("default_price")
        or 0
    )

    if price <= 0:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Review Price",
            error="Customer quote is zero or missing.",
        )
        result["reason"] = "nonpositive_total"
        return result

    delivery = send_invoice_email(
        int(invoice_id)
    )

    result.update(delivery)
    result["created"] = True
    result["reason"] = (
        "sent"
        if delivery.get("sent")
        else delivery.get("reason", "not_sent")
    )

    return result



def get_invoice_for_dispatch_job(job_id: int) -> dict | None:
    """Return the invoice already linked to a dispatch job, if any."""
    ensure_invoice_tables()

    rows = dataframe(
        """
        SELECT
            i.id,
            i.invoice_number,
            i.customer_id,
            i.invoice_date,
            i.due_date,
            i.status,
            i.subtotal,
            i.tax,
            i.total,
            i.sent_at,
            i.delivery_status,
            i.delivery_error
        FROM invoice_lines il
        INNER JOIN invoices i
            ON i.id=il.invoice_id
        WHERE il.source_type='dispatch'
          AND il.source_id=?
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (int(job_id),),
    )

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def get_completed_dispatch_for_invoice(job_id: int) -> dict | None:
    """
    Load one completed dispatch stop and the customer's billing details.

    A dispatch stop is the correct automatic-billing unit because one stop may
    contain more than one treatment event while the customer's quote is a
    per-visit/service price.
    """
    ensure_invoice_tables()

    rows = dataframe(
        """
        SELECT
            dj.id AS dispatch_job_id,
            dj.customer_id,
            dj.treatment_name,
            dj.scheduled_date,
            dj.completed_time,
            dj.status,
            c.name AS customer_name,
            c.email,
            COALESCE(c.quote, 0) AS default_price
        FROM dispatch_jobs dj
        INNER JOIN customers c
            ON c.id=dj.customer_id
        WHERE dj.id=?
          AND LOWER(COALESCE(dj.status,''))='completed'
        LIMIT 1
        """,
        (int(job_id),),
    )

    if rows.empty:
        return None

    return rows.iloc[0].to_dict()


def _create_invoice_for_dispatch_job(job: dict) -> int:
    """Create one draft invoice whose source is a completed dispatch stop."""
    ensure_invoice_tables()

    job_id = int(job["dispatch_job_id"])

    existing = get_invoice_for_dispatch_job(job_id)
    if existing:
        return int(existing["id"])

    price = float(job.get("default_price") or 0)
    treatment = str(job.get("treatment_name") or "").strip() or "Lawn Treatment"
    service_date = (
        str(job.get("completed_time") or "").strip()
        or str(job.get("scheduled_date") or "").strip()
        or date.today().isoformat()
    )

    # Keep only the date portion when completed_time is a timestamp.
    display_date = service_date[:10]

    conn = get_connection()

    try:
        cur = conn.cursor()

        # Re-check inside the write transaction to reduce the chance of a
        # duplicate invoice if the UI reruns immediately after completion.
        cur.execute(
            """
            SELECT i.id
            FROM invoice_lines il
            INNER JOIN invoices i
                ON i.id=il.invoice_id
            WHERE il.source_type='dispatch'
              AND il.source_id=?
            ORDER BY i.id DESC
            LIMIT 1
            """,
            (job_id,),
        )

        already = cur.fetchone()
        if already is not None:
            return int(already[0])

        cur.execute(
            """
            INSERT INTO invoices (
                invoice_number,
                customer_id,
                invoice_date,
                due_date,
                status,
                subtotal,
                tax,
                total,
                notes
            )
            VALUES (?, ?, ?, ?, 'Draft', ?, 0, ?, ?)
            """,
            (
                next_invoice_number(),
                int(job["customer_id"]),
                date.today().isoformat(),
                (date.today() + timedelta(days=30)).isoformat(),
                price,
                price,
                "Thank you for your business.",
            ),
        )

        invoice_id = int(cur.lastrowid)

        cur.execute(
            """
            INSERT INTO invoice_lines (
                invoice_id,
                source_type,
                source_id,
                description,
                quantity,
                unit_price,
                line_total
            )
            VALUES (?, 'dispatch', ?, ?, 1, ?, ?)
            """,
            (
                invoice_id,
                job_id,
                f"{treatment} - {display_date}",
                price,
                price,
            ),
        )

        conn.commit()
        return invoice_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def create_invoice_for_completed_dispatch_job(
    job_id: int,
    *,
    send_if_enabled: bool = True,
) -> dict:
    """
    Idempotently create one invoice for a completed dispatch stop.

    The dispatch stop remains completed even if invoice creation or email
    delivery later fails. The caller should treat invoicing as a follow-on
    action, not part of the dispatch completion transaction.
    """
    existing = get_invoice_for_dispatch_job(int(job_id))

    if existing:
        return {
            "created": False,
            "invoice_id": int(existing["id"]),
            "sent": str(existing.get("status") or "").lower() == "sent",
            "reason": "already_invoiced",
        }

    job = get_completed_dispatch_for_invoice(int(job_id))

    if not job:
        return {
            "created": False,
            "sent": False,
            "reason": "completed_dispatch_not_found",
        }

    invoice_id = _create_invoice_for_dispatch_job(job)

    result = {
        "created": True,
        "invoice_id": int(invoice_id),
        "sent": False,
        "reason": "draft_created",
    }

    if not send_if_enabled:
        return result

    if not _setting_enabled(
        "auto_send_invoices",
        default=False,
    ):
        result["reason"] = "auto_send_disabled"
        return result

    recipient = str(job.get("email") or "").strip()

    if not recipient:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Missing Email",
            error="Customer does not have an email address.",
        )
        result["reason"] = "missing_email"
        return result

    price = float(job.get("default_price") or 0)

    if price <= 0:
        _record_invoice_delivery(
            invoice_id,
            status="Not Sent - Review Price",
            error="Customer quote is zero or missing.",
        )
        result["reason"] = "nonpositive_total"
        return result

    delivery = send_invoice_email(int(invoice_id))

    result.update(delivery)
    result["created"] = True
    result["reason"] = (
        "sent"
        if delivery.get("sent")
        else delivery.get("reason", "not_sent")
    )

    return result

def get_logo_data_uri() -> str:
    logo_path = Path("assets") / "logo.png"

    if not logo_path.exists():
        return ""

    encoded = base64.b64encode(
        logo_path.read_bytes()
    ).decode("utf-8")

    return f"data:image/png;base64,{encoded}"


def build_invoice_html(invoice_id: int) -> str:
    invoices = get_invoices()
    invoice = invoices[invoices["id"] == int(invoice_id)]

    if invoice.empty:
        raise ValueError("Invoice was not found.")

    row = invoice.iloc[0]
    lines = get_invoice_lines(invoice_id)
    payments = get_payments(invoice_id)
    logo_data_uri = get_logo_data_uri()

    logo_html = (
        f'<img src="{logo_data_uri}" class="logo" alt="Time Out Lawncare logo">'
        if logo_data_uri
        else ""
    )

    line_rows = ""

    for _, line in lines.iterrows():
        line_rows += f"""
        <tr>
            <td>{escape(str(line['description']))}</td>
            <td class="num">{float(line['quantity']):,.2f}</td>
            <td class="num">${float(line['unit_price']):,.2f}</td>
            <td class="num">${float(line['line_total']):,.2f}</td>
        </tr>
        """

    payment_rows = ""

    for _, payment in payments.iterrows():
        payment_rows += f"""
        <tr>
            <td>{escape(str(payment['payment_date']))}</td>
            <td>{escape(str(payment['payment_method'] or ''))}</td>
            <td>{escape(str(payment['reference'] or ''))}</td>
            <td class="num">${float(payment['amount']):,.2f}</td>
        </tr>
        """

    if not payment_rows:
        payment_rows = """
        <tr>
            <td colspan="4">No payments recorded.</td>
        </tr>
        """

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{escape(str(row['invoice_number']))}</title>
        <style>
            .header {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 24px;
            }}

            .logo {{
                max-height: 90px;
                max-width: 220px;
                object-fit: contain;
            }}
            body {{
                font-family: Arial, sans-serif;
                margin: 32px;
                color: #1f2933;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin-top: 16px;
            }}
            th, td {{
                border: 1px solid #d0d7de;
                padding: 8px;
                text-align: left;
            }}
            th {{
                background: #f6f8fa;
            }}
            .num {{
                text-align: right;
            }}
            .summary {{
                width: 320px;
                margin-left: auto;
            }}
            @media print {{
                button {{
                    display: none;
                }}
            }}
        </style>
    </head>
    <body>
        <button onclick="window.print()">Print Invoice</button>

        <div class="header">
            <div>
                <h1>Time Out Lawncare</h1>
                <p>
                    303 East Brandon Court<br>
                    Brandon, MS 39042<br>
                    601-941-3586<br>
                    timeoutlawncare@gmail.com
                </p>
                <h2>Invoice {escape(str(row['invoice_number']))}</h2>
            </div>
            {logo_html}
        </div>

        <p>
            <strong>Invoice Date:</strong> {escape(str(row['invoice_date']))}<br>
            <strong>Due Date:</strong> {escape(str(row['due_date'] or ''))}<br>
            <strong>Status:</strong> {escape(str(row['status']))}
        </p>

        <h2>Bill To</h2>
        <p>
            {escape(str(row['customer_name']))}<br>
            {escape(str(row['address'] or ''))}
        </p>

        <h2>Invoice Lines</h2>
        <table>
            <thead>
                <tr>
                    <th>Description</th>
                    <th class="num">Qty</th>
                    <th class="num">Unit Price</th>
                    <th class="num">Total</th>
                </tr>
            </thead>
            <tbody>
                {line_rows}
            </tbody>
        </table>

        <table class="summary">
            <tr><th>Subtotal</th><td class="num">${float(row['subtotal']):,.2f}</td></tr>
            <tr><th>Tax</th><td class="num">${float(row['tax']):,.2f}</td></tr>
            <tr><th>Total</th><td class="num">${float(row['total']):,.2f}</td></tr>
            <tr><th>Paid</th><td class="num">${float(row['paid']):,.2f}</td></tr>
            <tr><th>Balance</th><td class="num">${float(row['balance']):,.2f}</td></tr>
        </table>

        <h2>Payments</h2>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Method</th>
                    <th>Reference</th>
                    <th class="num">Amount</th>
                </tr>
            </thead>
            <tbody>
                {payment_rows}
            </tbody>
        </table>

        <p>{escape(str(row['notes'] or ''))}</p>
    </body>
    </html>
    """
