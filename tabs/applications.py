from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.application_corrections import (
    get_application_record,
    get_correction_audit,
    list_application_records,
    save_application_correction,
)
from core.compliance_reports import (
    get_application_report,
)

from core.treatment_manager import (
    get_active_applicators,
    get_treatment_definitions,
    get_treatment_products,
    record_manual_application,
)

from data.database import get_customers

def render(current_email: str):

    st.header("Applications")

    add_tab, history_tab, correction_tab, audit_tab = st.tabs(
        [
            "Add Application",
            "Application History",
            "Correct Application",
            "Correction Audit",
        ]
    )

    # ======================================================
    # ADD APPLICATION
    # ======================================================

    with add_tab:

        st.subheader("Add Completed Application")

        st.caption(
            "Use this for work completed outside "
            "the Dispatch workflow."
        )

        customers = get_customers(active_only=True)

        treatments = get_treatment_definitions(
            active_only=True
        )

        applicators = get_active_applicators()

        if customers.empty:

            st.info(
                "Add an active customer before "
                "recording an application."
            )

        elif treatments.empty:

            st.info(
                "Add an active treatment type before "
                "recording an application."
            )

        else:

            customer_labels = {
                int(row["id"]): (
                    f"{row['name']} — "
                    f"{row.get('address', '')}"
                ).rstrip(" —")
                for _, row in customers.iterrows()
            }

            treatment_labels = {
                int(row["id"]): str(row["name"])
                for _, row in treatments.iterrows()
            }

            customer_id = st.selectbox(
                "Customer",
                options=list(customer_labels),
                format_func=lambda value: (
                    customer_labels[value]
                ),
                key="manual_application_customer",
            )

            treatment_id = st.selectbox(
                "Treatment",
                options=list(treatment_labels),
                format_func=lambda value: (
                    treatment_labels[value]
                ),
                key="manual_application_treatment",
            )

            selected_customer = customers[
                customers["id"] == customer_id
            ].iloc[0]

            square_feet = float(
                selected_customer.get(
                    "square_feet",
                    0,
                )
                or 0
            )

            acres = square_feet / 43560.0

            st.caption(
                f"Treatment area: {square_feet:,.0f} "
                f"sq ft ({acres:.3f} acres)"
            )

            chemicals = get_treatment_products(
                treatment_id
            )

            chemical_rows = []

            for _, chemical in chemicals.iterrows():

                rate = float(
                    chemical["rate_per_acre"]
                    or 0
                )

                calculated = rate * acres

                chemical_rows.append(
                    {
                        "product_id": int(
                            chemical["product_id"]
                        ),
                        "Chemical": chemical[
                            "product_name"
                        ],
                        "EPA Number": chemical[
                            "epa_number"
                        ],
                        "Rate Per Acre": rate,
                        "Unit": chemical[
                            "rate_unit"
                        ],
                        "Calculated Total": round(
                            calculated,
                            4,
                        ),
                        "Actual Total": round(
                            calculated,
                            4,
                        ),
                    }
                )

            with st.form(
                "add_manual_application_form"
            ):

                application_date = st.date_input(
                    "Application Date",
                    value=date.today(),
                )

                applicator_options = [None]

                applicator_labels = {
                    None: "Not specified"
                }

                for _, applicator in (
                    applicators.iterrows()
                ):

                    employee_id = int(
                        applicator["id"]
                    )

                    applicator_options.append(
                        employee_id
                    )

                    applicator_labels[
                        employee_id
                    ] = str(applicator["name"])

                applicator_id = st.selectbox(
                    "Applicator",
                    options=applicator_options,
                    format_func=lambda value: (
                        applicator_labels[value]
                    ),
                )

                if chemical_rows:

                    actual_chemicals = st.data_editor(
                        pd.DataFrame(
                            chemical_rows
                        ),
                        use_container_width=True,
                        hide_index=True,
                        disabled=[
                            "product_id",
                            "Chemical",
                            "EPA Number",
                            "Rate Per Acre",
                            "Unit",
                            "Calculated Total",
                        ],
                        column_config={
                            "product_id": None,
                            "Actual Total": (
                                st.column_config
                                .NumberColumn(
                                    "Actual Total",
                                    min_value=0.0,
                                    format="%.4f",
                                )
                            ),
                        },
                    )

                else:

                    actual_chemicals = (
                        pd.DataFrame()
                    )

                    st.warning(
                        "This treatment has no "
                        "chemicals assigned."
                    )

                notes = st.text_area(
                    "Application Notes",
                    placeholder=(
                        "Weather, turf conditions, "
                        "observations..."
                    ),
                )

                save_application = (
                    st.form_submit_button(
                        "Save Application",
                        type="primary",
                        use_container_width=True,
                    )
                )

                if save_application:

                    actual_amounts = {
                        int(row["product_id"]): float(
                            row["Actual Total"]
                        )
                        for _, row
                        in actual_chemicals.iterrows()
                    }

                    try:

                        record_manual_application(
                            customer_id=customer_id,
                            treatment_id=treatment_id,
                            application_date=(
                                application_date
                            ),
                            notes=notes,
                            actual_amounts=(
                                actual_amounts
                            ),
                            applicator_employee_id=(
                                applicator_id
                            ),
                        )

                    except ValueError as exc:

                        st.error(str(exc))

                    else:

                        st.success(
                            "Application saved."
                        )

                        st.rerun()

    # ======================================================
    # HISTORY
    # ======================================================

    with history_tab:

        st.subheader("Application History")

        today = date.today()

        date_col1, date_col2 = st.columns(2)

        history_start = date_col1.date_input(
            "Start Date",
            value=today.replace(
                month=1,
                day=1,
            ),
            key="application_history_start",
        )

        history_end = date_col2.date_input(
            "End Date",
            value=today,
            key="application_history_end",
        )

        history = get_application_report(
            history_start,
            history_end,
        )

        if history.empty:

            st.info(
                "No applications were found."
            )

        else:

            application_count = history[
                "Application ID"
            ].nunique()

            metric1, metric2 = st.columns(2)

            metric1.metric(
                "Applications",
                application_count,
            )

            metric2.metric(
                "Chemical Records",
                len(history),
            )

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True,
            )

    # ======================================================
    # CORRECTIONS
    # ======================================================

    with correction_tab:

        st.subheader(
            "Correct Completed Application"
        )

        st.warning(
            "Every correction requires a reason "
            "and is recorded in the audit history."
        )

        records = list_application_records()

        if records.empty:

            st.info(
                "No completed applications are available."
            )

        else:

            record_labels = {
                row["record_key"]: (
                    f"{row['application_date']} — "
                    f"{row['customer']} — "
                    f"{row['treatment']} "
                    f"({row['source']})"
                )
                for _, row in records.iterrows()
            }

            selected_record_key = st.selectbox(
                "Application",
                options=list(record_labels),
                format_func=lambda value: (
                    record_labels[value]
                ),
            )

            record = get_application_record(
                selected_record_key
            )

            header = record["header"]
            chemicals = record["chemicals"]

            with st.form(
                "application_correction_form"
            ):

                correction_date = st.date_input(
                    "Application Date",
                    value=pd.to_datetime(
                        header[
                            "application_date"
                        ]
                    ).date(),
                )

                st.text_input(
                    "Customer",
                    value=str(
                        header.get(
                            "customer",
                            "",
                        )
                    ),
                    disabled=True,
                )

                applicator = st.text_input(
                    "Applicator",
                    value=str(
                        header.get(
                            "applicator",
                            "",
                        )
                        or ""
                    ),
                )

                applicator_id = st.text_input(
                    "Applicator ID",
                    value=str(
                        header.get(
                            "applicator_id_number",
                            "",
                        )
                        or ""
                    ),
                )

                header_values = {
                    **header,
                    "application_date":
                        correction_date.isoformat(),
                    "applicator": applicator,
                    "applicator_id_number":
                        applicator_id,
                }

                if record["source"] == "CRM":

                    square_feet = st.number_input(
                        "Area Treated — Square Feet",
                        min_value=0.0,
                        value=float(
                            header.get(
                                "property_square_feet",
                                0,
                            )
                            or 0
                        ),
                    )

                    notes = st.text_area(
                        "Notes",
                        value=str(
                            header.get(
                                "notes",
                                "",
                            )
                            or ""
                        ),
                    )

                    header_values[
                        "property_square_feet"
                    ] = square_feet

                    header_values["notes"] = notes

                else:

                    start_time = st.text_input(
                        "Start Time",
                        value=str(
                            header.get(
                                "application_start_time",
                                "",
                            )
                            or ""
                        ),
                    )

                    end_time = st.text_input(
                        "End Time",
                        value=str(
                            header.get(
                                "application_end_time",
                                "",
                            )
                            or ""
                        ),
                    )

                    treatment = st.text_input(
                        "Treatment",
                        value=str(
                            header.get(
                                "treatment",
                                "",
                            )
                            or ""
                        ),
                    )

                    area = st.text_input(
                        "Area Treated",
                        value=str(
                            header.get(
                                "size_of_area_treated",
                                "",
                            )
                            or ""
                        ),
                    )

                    header_values.update(
                        {
                            "application_start_time":
                                start_time,
                            "application_end_time":
                                end_time,
                            "treatment":
                                treatment,
                            "size_of_area_treated":
                                area,
                        }
                    )

                st.subheader("Chemicals")

                edited_chemicals = st.data_editor(
                    chemicals,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["id"],
                    column_config={
                        "id": None,
                    },
                )

                correction_reason = st.text_area(
                    "Reason for Correction",
                    placeholder=(
                        "Explain what was corrected and why."
                    ),
                )

                save_correction = (
                    st.form_submit_button(
                        "Save Audited Correction",
                        type="primary",
                        use_container_width=True,
                    )
                )

                if save_correction:

                    save_application_correction(
                        record_key=selected_record_key,
                        header_values=header_values,
                        chemical_values=(
                            edited_chemicals
                        ),
                        changed_by=current_email,
                        change_reason=(
                            correction_reason
                        ),
                    )

                    st.success(
                        "Application corrected and "
                        "audit entry saved."
                    )

                    st.rerun()

    # ======================================================
    # AUDIT
    # ======================================================

    with audit_tab:

        st.subheader(
            "Correction Audit History"
        )

        audit = get_correction_audit()

        if audit.empty:

            st.info(
                "No corrections have been recorded."
            )

        else:

            st.dataframe(
                audit,
                use_container_width=True,
                hide_index=True,
            )