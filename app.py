
# Time Out Lawncare CRM

# Main Streamlit Application


from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st

from core.crm import initialize_system

from datetime import date

from data.database import update_customer

from tabs.import_data import render as render_import_data

from ui.dispatch import (
    dispatch_dashboard,
)

from core.crm import (
    list_customers,
    get_dashboard_stats,
)

# ---------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------

st.set_page_config(
    page_title="Time Out Lawncare",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    div[data-testid="stButton"] button,
    div[data-testid="stButton"] button p {
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if not bool(
    st.user.get(
        "is_logged_in",
        False,
    )
):

    st.title("Time Out Lawncare CRM")

    st.info(
        "Sign in with an authorized Google account."
    )

    if st.button(
        "Sign in",
        type="primary",
    ):
        st.login()

    st.stop()


configured_roles = st.secrets.get(
    "USER_ROLES",
    {},
)

user_roles = {
    str(email).strip().casefold():
    str(role).strip().casefold()
    for email, role
    in configured_roles.items()
}

current_email = str(
    st.user.get("email", "")
).strip().casefold()

current_role = user_roles.get(
    current_email,
    "",
)

valid_roles = {
    "admin",
    "office",
    "field",
}

if current_role not in valid_roles:

    st.error(
        "This Google account is not authorized."
    )

    if st.button("Sign out"):
        st.logout()

    st.stop()


with st.sidebar:

    st.write(
        f"Signed in as {current_email}"
    )
    
    st.caption(
        f"Role: {current_role.title()}"
    )

    if st.button(
        "Sign out",
        key="security_logout",
    ):
        st.logout()

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

if current_role == "field":

    app_mode = "Field Mode"

    st.sidebar.info(
        "Field access"
    )

else:

    app_mode = st.sidebar.radio(
        "Workspace",
        options=[
            "Office Mode",
            "Field Mode",
        ],
        key="app_workspace_mode",
    )

if app_mode == "Field Mode":

    initialize_system()

    from ui.field_view import (
        render as render_field_view,
    )

    render_field_view()

    st.stop()

initialize_system()

# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

DEFAULT_STATE = {

    "selected_customer": None,

    "selected_job": None,

    "selected_route": None,

    "refresh": False,

}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:

        st.session_state[key] = value

# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

st.title("🌱 Time Out Lawncare")

stats = get_dashboard_stats()

c1, c2, c3 = st.columns(3)

with c1:

    st.metric(
        "Customers",
        stats["total_customers"],
    )

with c2:

    st.metric(
        "Queued Jobs",
        stats["queued_jobs"],
    )

with c3:

    st.metric(
        "Completed",
        stats["completed_jobs"],
    )

st.divider()

# ---------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------

try:

    customers = list_customers()

except Exception:

    st.error("Unable to load customers.")

    st.exception(traceback.format_exc())

    customers = pd.DataFrame()

try:

    dispatch = dispatch_dashboard()

except Exception:

    st.error("Unable to load dispatch.")

    st.exception(traceback.format_exc())

    dispatch = {

        "jobs": [],

        "route": [],

        "manifest": [],

        "summary": {},

        "statistics": {},

        "dataframe": pd.DataFrame(),

    }

# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------

tab_dashboard, \
tab_customers, \
tab_dispatch, \
tab_schedule, \
tab_treatments, \
tab_applications, \
tab_invoicing, \
tab_routes, \
tab_reports, \
tab_import, \
tab_settings = st.tabs(
    [
        "Dashboard",
        "Customers",
        "Dispatch",
        "Scheduling",
        "Treatments",
        "Applications",
        "Invoicing",
        "Routing",
        "Reports",
        "Import Data",
        "Settings",
    ]
)

# ==========================================================
# DASHBOARD TAB
# ==========================================================

with tab_dashboard:

    st.header("Business Dashboard")

    col1, col2 = st.columns(2)

    with col1:

        st.subheader("Business Statistics")

        dashboard_stats = dispatch.get(
            "statistics",
            {}
        )

        st.json(
            dashboard_stats
        )

    with col2:

        st.subheader("Today's Route Summary")

        summary = dispatch.get(
            "summary",
            {}
        )

        if summary:

            c1, c2 = st.columns(2)

            with c1:

                st.metric(
                    "Stops",
                    summary.get(
                        "stops",
                        0,
                    ),
                )

                st.metric(
                    "Miles",
                    round(
                        summary.get(
                            "distance_miles",
                            0,
                        ),
                        1,
                    ),
                )

            with c2:

                st.metric(
                    "Drive Time",
                    round(
                        summary.get(
                            "drive_minutes",
                            0,
                        ),
                        1,
                    ),
                )

                st.metric(
                    "Total Time",
                    round(
                        summary.get(
                            "total_minutes",
                            0,
                        ),
                        1,
                    ),
                )

            maps = summary.get(
                "google_maps",
                ""
            )

            if maps:

                st.link_button(
                    "Open Route in Google Maps",
                    maps,
                    use_container_width=True,
                )

        else:

            st.info(
                "No dispatch route has been generated."
            )

    st.divider()

    st.subheader(
        "Today's Driver Manifest"
    )

    manifest = dispatch.get(
        "manifest",
        []
    )

    if manifest:

        st.dataframe(
            pd.DataFrame(
                manifest
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No jobs are currently queued."
        )


# ==========================================================
# CUSTOMERS TAB
# ==========================================================

with tab_customers:

    st.header("Customers")

    left, right = st.columns(
        [3, 1]
    )

    with left:

        search = st.text_input(
            "Search Customers",
            placeholder="Name or address...",
        )

    with right:

        refresh = st.button(
            "Refresh",
            use_container_width=True,
        )

    customer_df = customers.copy()

    if search:

        text = search.lower()

        customer_df = customer_df[
            customer_df.astype(str)
            .apply(
                lambda col:
                col.str.lower()
            )
            .apply(
                lambda col:
                col.str.contains(
                    text,
                    na=False,
                )
            )
            .any(axis=1)
        ]

    st.write(
        f"Customers Found: {len(customer_df)}"
    )

    customer_display_df = customer_df.drop(
        columns=[
            "street_address",
            "city",
            "state",
            "zip",
            "county",
        ],
        errors="ignore",
    )

    st.dataframe(
        customer_display_df,
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    st.subheader("Edit Customer")

    if customers.empty:

        st.info("No customers are available to edit.")

    else:

        def customer_value(row, field, default=""):
            value = row.get(field, default)
            return default if pd.isna(value) else value

        customer_options = (
            customers["id"].astype(int).tolist()
        )

        customer_labels = {
            int(row["id"]): (
                f"{row['name']} — "
                f"{customer_value(row, 'customer_number')}"
            ).rstrip(" —")
            for _, row in customers.iterrows()
        }

        edit_customer_id = st.selectbox(
            "Choose Customer",
            options=customer_options,
            format_func=lambda value: (
                customer_labels[value]
            ),
            key="edit_customer_selection",
        )

        selected_customer = customers[
            customers["id"] == edit_customer_id
        ].iloc[0]

        with st.form("edit_customer_form"):

            c1, c2 = st.columns(2)

            customer_name = c1.text_input(
                "Customer Name",
                value=str(
                    customer_value(
                        selected_customer,
                        "name",
                    )
                ),
            )

            customer_number = c2.text_input(
                "Customer Number",
                value=str(
                    customer_value(
                        selected_customer,
                        "customer_number",
                    )
                ),
            )

            street_address = st.text_input(
                "Street Address",
                value=str(
                    customer_value(
                        selected_customer,
                        "street_address",
                    )
                ),
            )

            city_col, state_col, zip_col = (
                st.columns([2, 1, 1])
            )

            city = city_col.text_input(
                "City",
                value=str(
                    customer_value(
                        selected_customer,
                        "city",
                    )
                ),
            )

            state = state_col.text_input(
                "State",
                value=str(
                    customer_value(
                        selected_customer,
                        "state",
                    )
                ),
            )

            zipcode = zip_col.text_input(
                "ZIP",
                value=str(
                    customer_value(
                        selected_customer,
                        "zip",
                    )
                ),
            )

            county = st.text_input(
                "County",
                value=str(
                    customer_value(
                        selected_customer,
                        "county",
                    )
                ),
            )

            phone_col, email_col = st.columns(2)

            phone = phone_col.text_input(
                "Phone Number",
                value=str(
                    customer_value(
                        selected_customer,
                        "phone",
                    )
                ),
            )

            email = email_col.text_input(
                "Email Address",
                value=str(
                    customer_value(
                        selected_customer,
                        "email",
                    )
                ),
            )

            text_phone = st.text_input(
                "Text Address",
                value=str(
                    customer_value(
                        selected_customer,
                        "text_phone",
                    )
                ),
            )

            area_col, quote_col = st.columns(2)

            square_feet = area_col.number_input(
                "Square Feet",
                min_value=0.0,
                value=float(
                    customer_value(
                        selected_customer,
                        "square_feet",
                        0,
                    )
                    or 0
                ),
            )

            quote = quote_col.number_input(
                "Quote",
                min_value=0.0,
                value=float(
                    customer_value(
                        selected_customer,
                        "quote",
                        0,
                    )
                    or 0
                ),
                format="%.2f",
            )

            turf_col, irrigation_col = (
                st.columns(2)
            )

            turf_type = turf_col.text_input(
                "Turf Type",
                value=str(
                    customer_value(
                        selected_customer,
                        "turf_type",
                    )
                ),
            )

            irrigation = irrigation_col.text_input(
                "Irrigation",
                value=str(
                    customer_value(
                        selected_customer,
                        "irrigation",
                    )
                ),
            )

            payment_method = st.text_input(
                "Payment Method",
                value=str(
                    customer_value(
                        selected_customer,
                        "payment_method",
                    )
                ),
            )

            notes = st.text_area(
                "Notes",
                value=str(
                    customer_value(
                        selected_customer,
                        "special_instructions",
                    )
                ),
            )

            active = st.checkbox(
                "Active Customer",
                value=bool(
                    customer_value(
                        selected_customer,
                        "active",
                        1,
                    )
                ),
            )

            save_customer = (
                st.form_submit_button(
                    "Save Customer Changes",
                    type="primary",
                    use_container_width=True,
                )
            )

            if save_customer:

                if not customer_name.strip():

                    st.error(
                        "Customer name is required."
                    )

                else:

                    full_address = ", ".join(
                        part.strip()
                        for part in [
                            street_address,
                            city,
                            state,
                            zipcode,
                        ]
                        if part.strip()
                    )

                    try:

                        update_customer(
                            edit_customer_id,
                            customer_number=(
                                customer_number.strip()
                                or None
                            ),
                            name=customer_name.strip(),
                            address=full_address,
                            street_address=(
                                street_address.strip()
                            ),
                            city=city.strip(),
                            state=state.strip(),
                            zip=zipcode.strip(),
                            county=county.strip(),
                            phone=phone.strip(),
                            email=email.strip(),
                            text_phone=(
                                text_phone.strip()
                            ),
                            square_feet=square_feet,
                            turf_type=turf_type.strip(),
                            irrigation=(
                                irrigation.strip()
                            ),
                            payment_method=(
                                payment_method.strip()
                            ),
                            quote=quote,
                            special_instructions=(
                                notes.strip()
                            ),
                            active=int(active),
                        )

                    except Exception as exc:

                        st.error(
                            "Customer could not be "
                            f"updated: {exc}"
                        )

                    else:

                        st.success(
                            "Customer updated "
                            "successfully."
                        )

                        st.rerun()

    st.divider()


    st.subheader(
        "Quick Add Customer"
    )

    with st.form(
        "quick_add_customer"
    ):

        name = st.text_input(
            "Customer Name"
        )

        address = st.text_input(
            "Address"
        )

        service = st.text_input(
            "Service"
        )

        submitted = st.form_submit_button(
            "Add Customer"
        )

        if submitted:

            try:

                from core.crm import (
                    create_customer,
                )

                create_customer(
                    name=name,
                    address=address,
                    service=service,
                )

                st.success(
                    "Customer added successfully."
                )

                st.rerun()

            except Exception:

                st.exception(
                    traceback.format_exc()
                )
                
# ==========================================================
# DISPATCH TAB
# ==========================================================

with tab_dispatch:

    st.header("Dispatch")
    
# ==========================================================
# Dispatch Dashboard
# ==========================================================

    from core.crm import list_customers

    import pandas as pd

    customers = list_customers()

    if customers is None:
        customers = pd.DataFrame()

    jobs_today = len(customers)
    completed = 0
    remaining = jobs_today

    estimated_revenue = 0.0

    if (
        not customers.empty
        and "price" in customers.columns
    ):
        estimated_revenue = (
            pd.to_numeric(
                customers["price"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )

    st.subheader("Today's Operations")

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "Customers",
        len(customers),
    )

    c2.metric(
        "Jobs Today",
        jobs_today,
    )

    c3.metric(
        "Completed",
        completed,
    )

    c4.metric(
        "Remaining",
        remaining,
    )

    c5.metric(
        "Revenue",
        f"${estimated_revenue:,.2f}",
    )

    st.divider()
    
# ==========================================================
# Dispatch Action Center
# ==========================================================

    st.subheader("Action Center")

    col1, col2, col3, col4 = st.columns(4)

    optimize_route = col1.button(
        "🛣️ Optimize Route",
        use_container_width=True,
    )

    start_route = col2.button(
        "🚚 Start Route",
        use_container_width=True,
    )

    print_route = col3.button(
        "🖨️ Print Route",
        use_container_width=True,
    )

    driver_mode = col4.button(
        "📱 Driver Mode",
        use_container_width=True,
    )

    if optimize_route:
        st.info("Route optimization will be connected next.")

    if start_route:
        st.success("Route started.")

    if print_route:
        st.info("Printable route sheet coming soon.")

    if driver_mode:
        st.info("Driver Mode coming soon.")

    st.divider()

    @st.dialog(
        "Complete Dispatch Stop",
        width="large",
    )
    def complete_dispatch_stop(
        dispatch_job_id: int,
    ):

        from datetime import date

        from core.treatment_manager import (
            complete_treatment_event,
            get_active_applicators,
            get_dispatch_treatment_events,
            get_treatment_products,
        )

        from ui.dispatch import (
            mark_job_complete,
        )

        treatment_events = (
            get_dispatch_treatment_events(
                dispatch_job_id
            )
        )

        if treatment_events.empty:

            st.info(
                "This is not linked to a treatment record."
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
            key=(
                "dispatch_application_date_"
                f"{dispatch_job_id}"
            ),
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
            key=(
                "office_applicator_"
                f"{dispatch_job_id}"
            ),
        )

        completion_notes = st.text_area(
            "Application Notes",
            key=(
                "dispatch_completion_notes_"
                f"{dispatch_job_id}"
            ),
        )

        completion_records = []

        for _, event in treatment_events.iterrows():

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
                f"{square_feet:,.0f} sq ft "
                f"({acres:.4f} acres)"
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
                        "Calculated": round(
                            calculated,
                            4,
                        ),
                        "Actual Total": round(
                            calculated,
                            4,
                        ),
                    }
                )

            if chemical_rows:

                edited_chemicals = st.data_editor(
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
                        "Calculated",
                    ],
                    column_config={
                        "product_id": None,
                        "Actual Total": (
                            st.column_config.NumberColumn(
                                "Actual Total",
                                min_value=0.0,
                                format="%.4f",
                            )
                        ),
                    },
                    key=(
                        "dispatch_actual_"
                        f"{event_id}"
                    ),
                )

                actual_amounts = {
                    int(row["product_id"]): float(
                        row["Actual Total"]
                    )
                    for _, row
                    in edited_chemicals.iterrows()
                }

            else:

                actual_amounts = {}

                st.warning(
                    "No chemicals are assigned "
                    "to this treatment."
                )

            completion_records.append(
                {
                    "event_id": event_id,
                    "actual_amounts": actual_amounts,
                }
            )

        if st.button(
            "Complete Stop and Save Applications",
            type="primary",
            use_container_width=True,
        ):

            for record in completion_records:

                complete_treatment_event(
                    event_id=record["event_id"],
                    notes=completion_notes,
                    application_date=application_date,
                    actual_amounts=record[
                        "actual_amounts"
                    ],
                    applicator_employee_id=(
                        selected_applicator_id
                    ),
                )

            st.success(
                "Stop completed and application "
                "records saved."
            )

            st.rerun()
    
# ==========================================================
# TODAY'S STOPS
# ==========================================================

    st.subheader("Today's Stops")

    scheduled_stops = dispatch.get(
        "jobs",
        [],
    )

    if not scheduled_stops:

        st.info(
            "There are no queued stops."
        )

    else:

        for index, row in enumerate(
            scheduled_stops
        ):

            with st.container(border=True):

                c1, c2, c3, c4, c5, c6 = st.columns(
                    [5, 1, 1, 1, 1.2, 1.6]
                )

                with c1:

                    st.markdown(
                        f"**{index + 1}. "
                        f"{row.get('name', '')}**"
                    )

                    treatment_name = (
                        row.get("treatment_name")
                        or row.get("service")
                        or ""
                    )

                    st.caption(
                        f"Treatment: {treatment_name}"
                    )

                    st.write(
                        row.get("address", "")
                    )

                    if row.get("scheduled_date"):

                        st.caption(
                            "Scheduled: "
                            f"{row['scheduled_date']}"
                        )

                with c2:

                    address = str(
                        row.get("address", "")
                    ).strip()

                    if address:

                        maps_url = (
                            "https://www.google.com/maps/"
                            "search/?api=1&query="
                            + address.replace(" ", "+")
                        )

                        st.link_button(
                            "📍",
                            maps_url,
                            use_container_width=True,
                        )

                with c3:

                    phone = str(
                        row.get("phone", "")
                    ).strip()

                    if phone:

                        st.link_button(
                            "📞",
                            f"tel:{phone}",
                            use_container_width=True,
                        )

                with c4:

                    text_number = str(
                        row.get(
                            "text_phone",
                            row.get("phone", ""),
                        )
                    ).strip()

                    if text_number:

                        st.link_button(
                            "💬",
                            f"sms:{text_number}",
                            use_container_width=True,
                        )

                with c5:

                    job_status = str(
                        row.get("status", "")
                    )

                    if job_status == "queued":

                        if st.button(
                            "Arrived",
                            key=f"arrived_{row['id']}",
                            use_container_width=True,
                        ):

                            from ui.dispatch import (
                                mark_job_in_progress,
                            )

                            mark_job_in_progress(
                                int(row["id"])
                            )

                            st.rerun()

                    elif job_status == "in_progress":

                        st.success("Arrived")

                    elif job_status == "completed":

                        st.success("Completed")

                with c6:

                    if row.get("status") in {
                        "queued",
                        "in_progress",
                    }:

                        if st.button(
                            "Completed",
                            key=(
                                "complete_stop_"
                                f"{row['id']}"
                            ),
                            use_container_width=True,
                        ):

                            complete_dispatch_stop(
                                int(row["id"])
                            )

        st.caption(
            "Complete treatment visits from the Treatments "
            "tab so actual chemical amounts are recorded."
        )

        st.divider()

    left, middle, right = st.columns(3)

    with left:

        if st.button(
            "Generate Optimized Route",
            use_container_width=True,
            key="dispatch_generate_route",
        ):

            dispatch = dispatch_dashboard()

            st.success(
                "Dispatch route generated."
            )

    with middle:

        if st.button(
            "Refresh Dispatch",
            use_container_width=True,
            key="dispatch_refresh",
        ):

            st.rerun()

    with right:

        if st.button(
            "Clear Queued Jobs",
            use_container_width=True,
            type="secondary",
            key="dispatch_clear_queue",
        ):

            from ui.dispatch import (
                cancel_entire_queue,
            )

            cancel_entire_queue()

            st.success(
                "Queued jobs cleared."
            )

            st.rerun()

    st.divider()

    st.subheader("Queued Jobs")

    jobs = dispatch.get(
        "jobs",
        [],
    )

    if jobs:

        st.dataframe(
            pd.DataFrame(jobs),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "There are no queued jobs."
        )

    st.divider()

    st.subheader("Daily Load Sheet")

    load_col1, load_col2, load_col3 = st.columns(3)

    load_gallons_per_acre = load_col1.number_input(
        "Water Gallons Per Acre",
        min_value=0.1,
        value=20.0,
        step=1.0,
        key="dispatch_water_gpa",
    )

    large_tank_size = load_col2.number_input(
        "Large Tank Gallons",
        min_value=1.0,
        value=200.0,
        step=5.0,
        key="dispatch_large_tank",
    )

    small_tank_size = load_col3.number_input(
        "Small Tank Gallons",
        min_value=1.0,
        value=30.0,
        step=1.0,
        key="dispatch_small_tank",
    )

    from core.load_sheet import (
        build_daily_load_sheet,
        build_daily_load_sheet_html,
    )

    load_sheet = build_daily_load_sheet(
        scheduled_date=date.today(),
        gallons_per_acre=load_gallons_per_acre,
        tank_sizes=[
            large_tank_size,
            small_tank_size,
        ],
    )

    load_summary = load_sheet["summary"]

    load_metric1, load_metric2, load_metric3 = st.columns(3)

    load_metric1.metric(
        "Scheduled Stops",
        load_summary["stops"],
    )

    load_metric2.metric(
        "Total Acres",
        load_summary["acres"],
    )

    load_metric3.metric(
        "Total Water",
        f"{load_summary['water_gallons']} gal",
    )

    with st.expander(
        "Treatment Mix Totals",
        expanded=True,
    ):

        if load_sheet["mix_summary"].empty:

            st.info(
                "No treatment loads are scheduled today."
            )

        else:

            st.dataframe(
                load_sheet["mix_summary"],
                use_container_width=True,
                hide_index=True,
            )

    with st.expander(
        "Total Chemicals Needed",
        expanded=True,
    ):

        if load_sheet["chemical_totals"].empty:

            st.info(
                "No chemicals are assigned to today's treatments."
            )

        else:

            st.dataframe(
                load_sheet["chemical_totals"],
                use_container_width=True,
                hide_index=True,
            )

    with st.expander(
        "Tank Load Breakdown",
        expanded=True,
    ):

        if not load_sheet["tank_plan"].empty:

            st.dataframe(
                load_sheet["tank_plan"],
                use_container_width=True,
                hide_index=True,
            )

    load_sheet_html = build_daily_load_sheet_html(
        load_sheet=load_sheet,
        scheduled_date=date.today(),
        gallons_per_acre=(
            load_gallons_per_acre
        ),
        tank_sizes=[
            large_tank_size,
            small_tank_size,
        ],
    )

    export_col1, export_col2 = st.columns(2)

    export_col1.download_button(
        "Download Printable Load Sheet",
        data=load_sheet_html,
        file_name=(
            f"daily_load_sheet_"
            f"{date.today().isoformat()}.html"
        ),
        mime="text/html",
        use_container_width=True,
    )

    export_col2.download_button(
        "Download Chemical Totals CSV",
        data=load_sheet[
            "chemical_totals"
        ].to_csv(index=False),
        file_name=(
            f"chemical_totals_"
            f"{date.today().isoformat()}.csv"
        ),
        mime="text/csv",
        use_container_width=True,
    )

    export_col3, export_col4 = st.columns(2)

    export_col3.download_button(
        "Download Tank Plan CSV",
        data=load_sheet[
            "tank_plan"
        ].to_csv(index=False),
        file_name=(
            f"tank_plan_"
            f"{date.today().isoformat()}.csv"
        ),
        mime="text/csv",
        use_container_width=True,
    )

    export_col4.download_button(
        "Download Mix Summary CSV",
        data=load_sheet[
            "mix_summary"
        ].to_csv(index=False),
        file_name=(
            f"mix_summary_"
            f"{date.today().isoformat()}.csv"
        ),
        mime="text/csv",
        use_container_width=True,
    )


    st.divider()


    st.subheader("Optimized Route")

    route_df = dispatch.get(
        "dataframe",
        pd.DataFrame(),
    )

    if not route_df.empty:

        st.dataframe(
            route_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No route has been generated."
        )

    st.divider()

    summary = dispatch.get(
        "summary",
        {},
    )

    if summary:

        c1, c2, c3, c4 = st.columns(4)

        with c1:

            st.metric(
                "Stops",
                summary.get(
                    "stops",
                    0,
                ),
            )

        with c2:

            st.metric(
                "Miles",
                round(
                    summary.get(
                        "distance_miles",
                        0,
                    ),
                    1,
                ),
            )

        with c3:

            st.metric(
                "Drive",
                round(
                    summary.get(
                        "drive_minutes",
                        0,
                    ),
                    1,
                ),
            )

        with c4:

            st.metric(
                "Total",
                round(
                    summary.get(
                        "total_minutes",
                        0,
                    ),
                    1,
                ),
            )

        maps = summary.get(
            "google_maps",
            "",
        )

        if maps:

            st.link_button(
                "Open Route in Google Maps",
                maps,
                use_container_width=True,
            )

    st.divider()

    st.subheader("Driver Manifest")

    manifest = dispatch.get(
        "manifest",
        [],
    )

    if manifest:

        st.dataframe(
            pd.DataFrame(manifest),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No driver manifest available."
        )

# ==========================================================
# ROUTE BUILDER
# ==========================================================

    st.subheader("Route Builder")

    rb1, rb2, rb3, rb4 = st.columns(4)

    build_route = rb1.button(
        "🧩 Build Route",
        use_container_width=True,
    )

    optimize_clusters = rb2.button(
        "🏘️ Neighborhoods",
        use_container_width=True,
    )

    balance_routes = rb3.button(
        "⚖️ Balance Workload",
        use_container_width=True,
    )

    save_route = rb4.button(
        "💾 Save Route",
        use_container_width=True,
    )

    if build_route:

        st.success(
            "Building today's route..."
        )

    if optimize_clusters:

        st.info(
            "Neighborhood clustering will be performed."
        )

    if balance_routes:

        st.info(
            "Balancing technician workload..."
        )

    if save_route:

        st.success(
            "Route saved."
        )

    st.divider()

    st.subheader("Today's Route Statistics")

    s1, s2, s3, s4 = st.columns(4)

    s1.metric(
        "Estimated Stops",
        jobs_today,
    )

    s2.metric(
        "Drive Time",
        "--",
    )

    s3.metric(
        "Work Time",
        "--",
    )

    s4.metric(
        "Miles",
        "--",
    )
    
# ==========================================================
# TREATMENTS TAB
# ==========================================================

with tab_treatments:

    from tabs.treatments import (
        render as render_treatments,
    )

    render_treatments()

# ==========================================================
# APPLICATIONS TAB
# ==========================================================
with tab_applications:

    from tabs.applications import (
        render as render_applications,
    )

    render_applications(
        current_email=current_email
    )
    
    
# ==========================================================
# INVOICING TAB
# ==========================================================

with tab_invoicing:

    from tabs.invoicing import (
        render as render_invoicing,
    )

    render_invoicing()

# ==========================================================
# SCHEDULING TAB
# ==========================================================

with tab_schedule:

    st.header("Scheduling")

    st.caption(
        "Review customers by their last service date, "
        "then add selected visits to dispatch."
    )

    schedule_date = st.date_input(
        "Service Date",
        key="schedule_service_date",
    )

    crew_count = st.number_input(
        "Number of Crews",
        min_value=1,
        max_value=10,
        value=1,
        key="schedule_crew_count",
    )

    from core.scheduling import (
        build_treatment_schedule_candidates,
        queue_treatment_events_for_date,
    )

    candidates = build_treatment_schedule_candidates(
        schedule_date
    )

    due_count = len(candidates)

    queued_count = sum(
        bool(item["already_queued"])
        for item in candidates
    )

    ready_count = due_count - queued_count

    m1, m2, m3 = st.columns(3)

    m1.metric(
        "Due by Date",
        due_count,
    )

    m2.metric(
        "Already Queued",
        queued_count,
    )

    m3.metric(
        "Ready to Schedule",
        ready_count,
    )

    if candidates:

        schedule_rows = pd.DataFrame(
            candidates
        )

        if "schedule_select_all" not in st.session_state:
            st.session_state.schedule_select_all = True

        if "schedule_editor_version" not in st.session_state:
            st.session_state.schedule_editor_version = 0

        select_col, deselect_col = st.columns(2)

        if select_col.button(
            "Select All",
            use_container_width=True,
            key="schedule_select_all_button",
        ):
            st.session_state.schedule_select_all = True
            st.session_state.schedule_editor_version += 1
            st.rerun()

        if deselect_col.button(
            "Deselect All",
            use_container_width=True,
            key="schedule_deselect_all_button",
        ):
            st.session_state.schedule_select_all = False
            st.session_state.schedule_editor_version += 1
            st.rerun()

        default_selection = (
            ~schedule_rows["already_queued"]
            if st.session_state.schedule_select_all
            else False
        )

        schedule_rows.insert(
            0,
            "Schedule",
            default_selection,
        )

        schedule_rows["due_date"] = pd.to_datetime(
            schedule_rows["due_date"],
            errors="coerce",
        ).dt.date

        display_columns = [
            "Schedule",
            "event_id",
            "name",
            "treatment",
            "event_type",
            "due_date",
            "days_overdue",
            "address",
            "override_reason",
            "already_queued",
        ]

        edited_schedule = st.data_editor(
            schedule_rows[display_columns],
            use_container_width=True,
            hide_index=True,
            disabled=[
                "event_id",
                "name",
                "treatment",
                "event_type",
                "due_date",
                "days_overdue",
                "address",
                "override_reason",
                "already_queued",
            ],
            column_config={
                "Schedule": (
                    st.column_config.CheckboxColumn(
                        "Schedule"
                    )
                ),
                "event_id": None,
                "name": "Customer",
                "treatment": "Treatment",
                "event_type": "Type",
                "due_date": (
                    st.column_config.DateColumn(
                        "Due Date"
                    )
                ),
                "days_overdue": (
                    st.column_config.NumberColumn(
                        "Days Overdue"
                    )
                ),
                "address": "Address",
                "override_reason": "Weather/Override",
                "already_queued": (
                    st.column_config.CheckboxColumn(
                        "Queued"
                    )
                ),
            },
            key=(
                "schedule_treatments_"
                f"{st.session_state.schedule_editor_version}"
            ),
        )

        selected_event_ids = edited_schedule.loc[
            edited_schedule["Schedule"]
            & ~edited_schedule["already_queued"],
            "event_id",
        ].tolist()

        if st.button(
            (
                f"Add {len(selected_event_ids)} "
                "Treatment(s) to Dispatch"
            ),
            type="primary",
            use_container_width=True,
            disabled=not selected_event_ids,
            key="schedule_add_dispatch",
        ):

            result = queue_treatment_events_for_date(
                selected_event_ids,
                schedule_date,
            )

            st.success(
                f"Created {result['jobs_created']} dispatch "
                f"stop(s) and linked "
                f"{result['events_linked']} treatment(s)."
            )

            if result["skipped"]:

                st.info(
                    f"Skipped {result['skipped']} treatment(s) "
                    "already in dispatch."
                )

            st.rerun()

    else:

        st.info(
            "No planned treatments are due by this date. "
            "Generate the seasonal schedule from the "
            "Treatments tab first."
        )

    st.divider()

    st.subheader(
        "Crew Route Preview"
    )

    if st.button(
        "Preview Routes for Queued Jobs",
        use_container_width=True,
        key="schedule_route_preview",
    ):

        try:

            from ui.dispatch import (
                build_multi_driver_routes,
            )

            routes = build_multi_driver_routes(
                crews=int(crew_count),
                scheduled_date=schedule_date,
            )

            if routes:

                for crew in routes:

                    st.subheader(
                        f"Crew {crew['crew']}"
                    )

                    st.write(
                        crew["summary"]
                    )

                    st.dataframe(
                        pd.DataFrame(
                            crew["manifest"]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

            else:

                st.warning(
                    "No queued jobs found."
                )

        except Exception:

            st.exception(
                traceback.format_exc()
            )

            
# ==========================================================
# ROUTING TAB
# ==========================================================

with tab_routes:

    st.header("Routing")

    st.write(
        "Generate and analyze optimized routes."
    )

    if st.button(
        "Generate Route",
        use_container_width=True,
        key="route_generate",
    ):

        dispatch = dispatch_dashboard()

        st.success(
            "Route generated successfully."
        )

    route_df = dispatch.get(
        "dataframe",
        pd.DataFrame(),
    )

    if not route_df.empty:

        st.dataframe(
            route_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No optimized route available."
        )

    summary = dispatch.get(
        "summary",
        {},
    )

    if summary:

        st.divider()

        c1, c2, c3, c4 = st.columns(4)

        with c1:

            st.metric(
                "Stops",
                summary.get(
                    "stops",
                    0,
                ),
            )

        with c2:

            st.metric(
                "Miles",
                round(
                    summary.get(
                        "distance_miles",
                        0,
                    ),
                    1,
                ),
            )

        with c3:

            st.metric(
                "Drive Minutes",
                round(
                    summary.get(
                        "drive_minutes",
                        0,
                    ),
                    1,
                ),
            )

        with c4:

            st.metric(
                "Total Minutes",
                round(
                    summary.get(
                        "total_minutes",
                        0,
                    ),
                    1,
                ),
            )

        maps = summary.get(
            "google_maps",
            "",
        )

        if maps:

            st.link_button(
                "Open in Google Maps",
                maps,
                use_container_width=True,
            )


# ==========================================================
# REPORTS TAB
# ==========================================================

with tab_reports:

    from datetime import date

    from core.compliance_reports import (
        build_inspector_html,
        build_route_html,
        get_application_report,
    )

    st.header("Reports")

    (
        route_report_tab,
        inspector_report_tab,
    ) = st.tabs(
        [
            "Daily Route",
            "Licensing Inspector",
        ]
    )

    # ======================================================
    # DAILY ROUTE REPORT
    # ======================================================

    with route_report_tab:

        st.subheader("Current Daily Route")

        current_route = dispatch.get(
            "route",
            [],
        )

        route_summary_data = dispatch.get(
            "summary",
            {},
        )

        route_report_date = st.date_input(
            "Route Date",
            value=date.today(),
            key="route_report_date",
        )

        route_report_html = build_route_html(
            current_route,
            route_summary_data,
            route_report_date,
        )

        route_df = dispatch.get(
            "dataframe",
            pd.DataFrame(),
        )

        if route_df.empty:

            st.info(
                "No current route is available."
            )

        else:

            st.dataframe(
                route_df,
                use_container_width=True,
                hide_index=True,
            )

        st.download_button(
            "Download Printable Daily Route",
            data=route_report_html,
            file_name=(
                f"daily_route_{route_report_date}.html"
            ),
            mime="text/html",
            use_container_width=True,
        )

        st.caption(
            "Open the downloaded file and click Print Report."
        )

    # ======================================================
    # INSPECTOR REPORT
    # ======================================================

    with inspector_report_tab:

        st.subheader(
            "Pesticide Application Report"
        )

        today = date.today()

        default_start = today.replace(
            day=1
        )

        range_col1, range_col2 = st.columns(2)

        report_start = range_col1.date_input(
            "Start Application Date",
            value=default_start,
            key="inspector_start_date",
        )

        report_end = range_col2.date_input(
            "End Application Date",
            value=today,
            key="inspector_end_date",
        )

        if report_start > report_end:

            st.error(
                "Start date must be before the end date."
            )

        else:

            inspector_report = get_application_report(
                report_start,
                report_end,
            )

            if inspector_report.empty:

                st.info(
                    "No chemical applications were recorded "
                    "during this period."
                )

            else:

                application_count = inspector_report[
                    "Application ID"
                ].nunique()

                metric_col1, metric_col2 = st.columns(2)

                metric_col1.metric(
                    "Applications",
                    application_count,
                )

                metric_col2.metric(
                    "Chemical Records",
                    len(inspector_report),
                )

                st.dataframe(
                    inspector_report,
                    use_container_width=True,
                    hide_index=True,
                )

            inspector_html = build_inspector_html(
                inspector_report,
                report_start,
                report_end,
            )

            st.subheader(
                "Printable Report Preview"
            )

            import streamlit.components.v1 as components

            components.html(
                inspector_html,
                height=750,
                scrolling=True,
            )

            csv_data = inspector_report.to_csv(
                index=False
            )

            download_col1, download_col2 = st.columns(2)

            download_col1.download_button(
                "Download Printable Report",
                data=inspector_html,
                file_name=(
                    "pesticide_application_report_"
                    f"{report_start}_{report_end}.html"
                ),
                mime="text/html",
                use_container_width=True,
            )

            download_col2.download_button(
                "Download Inspector CSV",
                data=csv_data,
                file_name=(
                    "pesticide_application_report_"
                    f"{report_start}_{report_end}.csv"
                ),
                mime="text/csv",
                use_container_width=True,
            )

# ==========================================================
# IMPORT DATA TAB
# ==========================================================

with tab_import:

    render_import_data()

# ==========================================================
# SETTINGS TAB
# ==========================================================

with tab_settings:

    st.header("Settings")

    from core.crm import (
        get_depot,
        update_depot,
    )

    depot = get_depot()

    with st.form(
        "depot_form"
    ):

        depot_name = st.text_input(

            "Depot Name",

            depot.get(
                "name",
                "",
            ),
        )

        depot_address = st.text_input(

            "Depot Address",

            depot.get(
                "address",
                "",
            ),
        )

        depot_lat = st.number_input(

            "Latitude",

            value=float(
                depot.get(
                    "lat",
                    32.2737,
                )
                or 32.2737
            ),

            format="%.6f",

        )

        depot_lng = st.number_input(

            "Longitude",

            value=float(
                depot.get(
                    "lng",
                    -89.9865,
                )
                or -89.9865
            ),

            format="%.6f",

        )

        save = st.form_submit_button(
            "Save Depot Settings"
        )

        if save:

            update_depot(

                depot_name,

                depot_address,

                depot_lat,

                depot_lng,

            )

            st.success(
                "Depot settings saved."
            )

            st.rerun()

    st.divider()

    st.subheader(
        "System Status"
    )

    try:

        from data.database import (
            database_health,
        )

        st.json(
            database_health()
        )

    except Exception:

        st.exception(
            traceback.format_exc()
        )


# ==========================================================
# FOOTER
# ==========================================================

st.divider()

st.caption(
    "Time Out Lawncare CRM • Version 2.0"
)

