from __future__ import annotations

from datetime import date
from urllib.parse import quote

import pandas as pd
import streamlit as st

from core.treatment_manager import (
    complete_treatment_event,
    get_active_applicators,
    get_dispatch_treatment_events,
    get_treatment_products,
)
from ui.dispatch import (
    dispatch_dashboard,
    mark_job_complete,
    mark_job_in_progress,
)


@st.dialog(
    "Complete Stop",
    width="large",
)
def complete_stop(
    dispatch_job_id: int,
):
    events = get_dispatch_treatment_events(
        dispatch_job_id
    )

    if events.empty:

        st.info(
            "No chemical treatment is linked "
            "to this stop."
        )

        if st.button(
            "Complete Stop",
            type="primary",
            use_container_width=True,
        ):

            mark_job_complete(
                dispatch_job_id
            )

            st.rerun()

        return

    application_date = st.date_input(
        "Application Date",
        value=date.today(),
        key=f"field_date_{dispatch_job_id}",
    )
    
    applicators = get_active_applicators()

    if applicators.empty:

        st.error(
            "No active applicators are available."
        )

        return

    applicator_labels = {
        int(row["id"]): (
            f"{row['name']} — "
            f"ID {row['id_number'] or 'Not entered'}"
        )
        for _, row in applicators.iterrows()
    }

    selected_applicator_id = st.selectbox(
        "Applicator",
        options=list(applicator_labels),
        format_func=lambda value: (
            applicator_labels[value]
        ),
        key=f"field_applicator_{dispatch_job_id}",
    )

    notes = st.text_area(
        "Application Notes",
        key=f"field_notes_{dispatch_job_id}",
    )

    completion_records = []

    for _, event in events.iterrows():

        event_id = int(event["id"])
        treatment_id = int(
            event["treatment_id"]
        )

        st.subheader(
            str(event["treatment"])
        )

        square_feet = float(
            event["square_feet"] or 0
        )

        acres = square_feet / 43560.0

        st.caption(
            f"{square_feet:,.0f} sq ft • "
            f"{acres:.4f} acres"
        )

        chemicals = get_treatment_products(
            treatment_id
        )

        rows = []

        for _, chemical in chemicals.iterrows():

            rate = float(
                chemical["rate_per_acre"] or 0
            )

            calculated = rate * acres

            rows.append(
                {
                    "product_id": int(
                        chemical["product_id"]
                    ),
                    "Chemical": chemical[
                        "product_name"
                    ],
                    "EPA": chemical[
                        "epa_number"
                    ],
                    "Rate": rate,
                    "Unit": chemical[
                        "rate_unit"
                    ],
                    "Calculated": round(
                        calculated,
                        4,
                    ),
                    "Actual": round(
                        calculated,
                        4,
                    ),
                }
            )

        if rows:

            edited = st.data_editor(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                disabled=[
                    "product_id",
                    "Chemical",
                    "EPA",
                    "Rate",
                    "Unit",
                    "Calculated",
                ],
                column_config={
                    "product_id": None,
                    "Actual": (
                        st.column_config.NumberColumn(
                            "Actual",
                            min_value=0.0,
                            format="%.4f",
                        )
                    ),
                },
                key=f"field_chemicals_{event_id}",
            )

            amounts = {
                int(row["product_id"]): float(
                    row["Actual"]
                )
                for _, row in edited.iterrows()
            }

        else:

            amounts = {}

            st.warning(
                "No chemicals are assigned."
            )

        completion_records.append(
            {
                "event_id": event_id,
                "amounts": amounts,
            }
        )

    if st.button(
        "Complete and Save Application",
        type="primary",
        use_container_width=True,
    ):

        for record in completion_records:

            complete_treatment_event(
                event_id=record["event_id"],
                notes=notes,
                application_date=application_date,
                actual_amounts=record["amounts"],
                applicator_employee_id=(
                    selected_applicator_id
                ),
            )

        st.success(
            "Stop completed."
        )

        st.rerun()


def render():

    st.markdown(
        """
        <style>
        .field-title {
            font-size: 1.65rem;
            font-weight: 700;
            margin-bottom: .25rem;
        }

        .field-status {
            font-size: .85rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        div[data-testid="stButton"] button,
        div[data-testid="stButton"] button p {
            white-space: nowrap;
            min-height: 44px;
        }

        div[data-testid="stLinkButton"] a {
            min-height: 44px;
        }

        @media (max-width: 700px) {
            .block-container {
                padding-top: 1rem;
                padding-left: .7rem;
                padding-right: .7rem;
            }

            h1, h2, h3 {
                line-height: 1.15;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="field-title">Today’s Route</div>',
        unsafe_allow_html=True,
    )

    dispatch = dispatch_dashboard()

    jobs = dispatch.get(
        "jobs",
        [],
    )

    summary = dispatch.get(
        "summary",
        {},
    )

    queued = sum(
        job.get("status") == "queued"
        for job in jobs
    )

    arrived = sum(
        job.get("status") == "in_progress"
        for job in jobs
    )

    metric1, metric2, metric3 = st.columns(3)

    metric1.metric(
        "Stops",
        len(jobs),
    )

    metric2.metric(
        "Waiting",
        queued,
    )

    metric3.metric(
        "Arrived",
        arrived,
    )

    maps_url = summary.get(
        "google_maps",
        "",
    )

    if maps_url:

        st.link_button(
            "Open Full Route in Google Maps",
            maps_url,
            use_container_width=True,
        )

    st.divider()

    if not jobs:

        st.success(
            "No active stops."
        )

        return

    for index, job in enumerate(jobs):

        job_id = int(job["id"])
        status = str(
            job.get("status", "queued")
        )

        with st.container(border=True):

            st.markdown(
                f"### {index + 1}. "
                f"{job.get('name', '')}"
            )

            if status == "in_progress":

                st.success(
                    "ARRIVED"
                )

            else:

                st.caption(
                    "WAITING"
                )

            treatment = (
                job.get("treatment_name")
                or job.get("service")
                or ""
            )

            st.markdown(
                f"**Treatment:** {treatment}"
            )

            address = str(
                job.get("address", "")
            ).strip()

            if address:

                st.write(address)

            notes = str(
                job.get("notes", "")
            ).strip()

            if notes:

                with st.expander(
                    "Instructions"
                ):

                    st.write(notes)

            action1, action2, action3 = st.columns(3)

            if address:

                maps = (
                    "https://www.google.com/maps/"
                    "search/?api=1&query="
                    + quote(address)
                )

                action1.link_button(
                    "Navigate",
                    maps,
                    use_container_width=True,
                )

            phone = str(
                job.get("phone", "")
            ).strip()

            if phone:

                action2.link_button(
                    "Call",
                    f"tel:{phone}",
                    use_container_width=True,
                )

            text_phone = str(
                job.get(
                    "text_phone",
                    phone,
                )
            ).strip()

            if text_phone:

                action3.link_button(
                    "Text",
                    f"sms:{text_phone}",
                    use_container_width=True,
                )

            arrived_col, completed_col = st.columns(2)

            if status == "queued":

                if arrived_col.button(
                    "Arrived",
                    key=f"field_arrived_{job_id}",
                    use_container_width=True,
                ):

                    mark_job_in_progress(
                        job_id
                    )

                    st.rerun()

            else:

                arrived_col.success(
                    "Arrived"
                )

            if completed_col.button(
                "Completed",
                key=f"field_complete_{job_id}",
                type="primary",
                use_container_width=True,
            ):

                complete_stop(
                    job_id
                )