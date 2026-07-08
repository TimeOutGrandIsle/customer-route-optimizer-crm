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


def render(current_email: str):

    st.header("Applications")

    history_tab, correction_tab, audit_tab = st.tabs(
        [
            "Application History",
            "Correct Application",
            "Correction Audit",
        ]
    )

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