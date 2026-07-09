from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.invoicing import (
    add_payment,
    build_invoice_html,
    create_invoice,
    ensure_invoice_tables,
    get_invoice_lines,
    get_invoices,
    get_payments,
    get_ready_to_invoice,
    update_invoice_status,
)


def render() -> None:
    ensure_invoice_tables()

    st.header("Invoicing")

    ready_tab, invoices_tab, payments_tab = st.tabs(
        [
            "Ready to Invoice",
            "Invoices",
            "Payments",
        ]
    )

    with ready_tab:
        st.subheader("Completed Work Ready to Invoice")

        ready = get_ready_to_invoice()

        if ready.empty:
            st.info("No completed uninvoiced work is available.")
        else:
            customers = ready[
                ["customer_id", "customer_name"]
            ].drop_duplicates()

            customer_labels = {
                int(row["customer_id"]): row["customer_name"]
                for _, row in customers.iterrows()
            }

            selected_customer_id = st.selectbox(
                "Customer",
                options=list(customer_labels),
                format_func=lambda value: customer_labels[value],
            )

            customer_ready = ready[
                ready["customer_id"] == selected_customer_id
            ].copy()

            customer_ready.insert(0, "Invoice", True)

            edited = st.data_editor(
                customer_ready[
                    [
                        "Invoice",
                        "application_id",
                        "application_date",
                        "customer_name",
                        "treatment",
                        "property_square_feet",
                        "acres",
                        "default_price",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                disabled=[
                    "application_id",
                    "application_date",
                    "customer_name",
                    "treatment",
                    "property_square_feet",
                    "acres",
                    "default_price",
                ],
                column_config={
                    "Invoice": st.column_config.CheckboxColumn(
                        "Invoice"
                    ),
                    "application_id": None,
                    "application_date": "Application Date",
                    "customer_name": "Customer",
                    "treatment": "Treatment",
                    "property_square_feet": "Sq Ft",
                    "acres": "Acres",
                    "default_price": st.column_config.NumberColumn(
                        "Price",
                        format="$%.2f",
                    ),
                },
            )

            selected_ids = edited.loc[
                edited["Invoice"],
                "application_id",
            ].astype(int).tolist()

            invoice_col, due_col = st.columns(2)

            invoice_date = invoice_col.date_input(
                "Invoice Date",
                value=date.today(),
            )

            due_date = due_col.date_input(
                "Due Date",
                value=date.today() + timedelta(days=30),
            )

            notes = st.text_area(
                "Invoice Notes",
                value="Thank you for your business.",
            )

            if st.button(
                "Create Draft Invoice",
                type="primary",
                use_container_width=True,
                disabled=not selected_ids,
            ):
                try:
                    invoice_id = create_invoice(
                        application_ids=selected_ids,
                        invoice_date=invoice_date,
                        due_date=due_date,
                        notes=notes,
                    )

                except Exception as exc:
                    st.error(f"Invoice could not be created: {exc}")

                else:
                    st.success(
                        f"Draft invoice created. Invoice ID: {invoice_id}"
                    )
                    st.rerun()

    with invoices_tab:
        st.subheader("Invoices")

        status_filter = st.selectbox(
            "Status",
            options=[
                "All",
                "Draft",
                "Sent",
                "Partially Paid",
                "Paid",
                "Void",
            ],
        )

        invoices = get_invoices(status_filter)

        if invoices.empty:
            st.info("No invoices found.")
        else:
            st.dataframe(
                invoices,
                use_container_width=True,
                hide_index=True,
            )

            invoice_labels = {
                int(row["id"]): (
                    f"{row['invoice_number']} - "
                    f"{row['customer_name']} - "
                    f"${float(row['balance'] or 0):,.2f} balance"
                )
                for _, row in invoices.iterrows()
            }

            selected_invoice_id = st.selectbox(
                "Open Invoice",
                options=list(invoice_labels),
                format_func=lambda value: invoice_labels[value],
            )

            selected = invoices[
                invoices["id"] == selected_invoice_id
            ].iloc[0]

            st.markdown(
                f"""
                **Invoice:** {selected['invoice_number']}  
                **Customer:** {selected['customer_name']}  
                **Status:** {selected['status']}  
                **Total:** ${float(selected['total'] or 0):,.2f}  
                **Balance:** ${float(selected['balance'] or 0):,.2f}
                """
            )

            lines = get_invoice_lines(selected_invoice_id)

            st.subheader("Invoice Lines")

            st.dataframe(
                lines,
                use_container_width=True,
                hide_index=True,
            )

            new_status = st.selectbox(
                "Update Status",
                options=[
                    "Draft",
                    "Sent",
                    "Partially Paid",
                    "Paid",
                    "Void",
                ],
                index=[
                    "Draft",
                    "Sent",
                    "Partially Paid",
                    "Paid",
                    "Void",
                ].index(str(selected["status"])),
            )

            if st.button(
                "Save Invoice Status",
                use_container_width=True,
            ):
                update_invoice_status(
                    selected_invoice_id,
                    new_status,
                )
                st.success("Invoice status updated.")
                st.rerun()

            invoice_html = build_invoice_html(selected_invoice_id)

            st.download_button(
                "Download Printable Invoice",
                data=invoice_html,
                file_name=(
                    f"{selected['invoice_number']}.html"
                ),
                mime="text/html",
                use_container_width=True,
            )

            st.download_button(
                "Download Invoice Lines CSV",
                data=lines.to_csv(index=False),
                file_name=(
                    f"{selected['invoice_number']}_lines.csv"
                ),
                mime="text/csv",
                use_container_width=True,
            )

    with payments_tab:
        st.subheader("Record Payment")

        invoices = get_invoices()

        open_invoices = invoices[
            invoices["status"].isin(
                ["Draft", "Sent", "Partially Paid"]
            )
        ]

        if open_invoices.empty:
            st.info("No open invoices are available.")
        else:
            payment_labels = {
                int(row["id"]): (
                    f"{row['invoice_number']} - "
                    f"{row['customer_name']} - "
                    f"${float(row['balance'] or 0):,.2f} balance"
                )
                for _, row in open_invoices.iterrows()
            }

            invoice_id = st.selectbox(
                "Invoice",
                options=list(payment_labels),
                format_func=lambda value: payment_labels[value],
                key="payment_invoice",
            )

            selected = open_invoices[
                open_invoices["id"] == invoice_id
            ].iloc[0]

            default_amount = float(selected["balance"] or 0)

            with st.form("payment_form"):
                payment_date = st.date_input(
                    "Payment Date",
                    value=date.today(),
                )

                amount = st.number_input(
                    "Amount",
                    min_value=0.0,
                    value=default_amount,
                    format="%.2f",
                )

                payment_method = st.text_input(
                    "Payment Method",
                    value="",
                    placeholder="Check, Cash, Card, ACH",
                )

                reference = st.text_input(
                    "Reference",
                    value="",
                    placeholder="Check number or transaction ID",
                )

                notes = st.text_area("Notes")

                save_payment = st.form_submit_button(
                    "Save Payment",
                    type="primary",
                    use_container_width=True,
                )

                if save_payment:
                    if amount <= 0:
                        st.error("Payment amount must be greater than zero.")
                    else:
                        add_payment(
                            invoice_id=invoice_id,
                            payment_date=payment_date,
                            amount=amount,
                            payment_method=payment_method,
                            reference=reference,
                            notes=notes,
                        )
                        st.success("Payment saved.")
                        st.rerun()

            st.subheader("Payment History")

            payments = get_payments(invoice_id)

            if payments.empty:
                st.info("No payments recorded for this invoice.")
            else:
                st.dataframe(
                    payments,
                    use_container_width=True,
                    hide_index=True,
                )