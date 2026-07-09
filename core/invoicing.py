from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd

import base64
from pathlib import Path

from data.database import dataframe, execute, get_connection


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
        WHERE il.id IS NULL
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
            i.subtotal,
            i.tax,
            i.total,
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
        GROUP BY i.id
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
            WHERE il.id IS NULL
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