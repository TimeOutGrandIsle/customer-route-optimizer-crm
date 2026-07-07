
# Time Out Lawncare CRM

# Main Streamlit Application


from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st

from core.crm import initialize_system

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

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

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

    st.dataframe(
        customer_df,
        use_container_width=True,
        hide_index=True,
    )

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
    
# ==========================================================
# TODAY'S STOPS
# ==========================================================

    st.subheader("Today's Stops")

    if customers.empty:

        st.info("No customers available.")

    else:

        display_columns = []

        for column in [

            "customer_number",

            "name",

            "service",

            "address",

            "phone",

            "text_phone",

        ]:

            if column in customers.columns:

                display_columns.append(column)

        display = customers[display_columns].copy()

        display.reset_index(

            drop=True,

            inplace=True,

        )

        for index, row in display.iterrows():

            st.container(border=True)

            c1, c2, c3, c4, c5 = st.columns([6,1,1,1,1])

            with c1:

                st.markdown(

                    f"**{index+1}. {row.get('name','')}**"

                )

                if "service" in row:

                    st.caption(

                        f"Service: {row.get('service','')}"

                    )

                if "address" in row:

                    st.write(

                        row.get("address","")

                    )

            with c2:

                address = row.get("address", "")

                if address:

                    maps_url = (
                        "https://www.google.com/maps/search/?api=1&query="
                        + address.replace(" ", "+")
                    )

                    st.link_button(
                        "📍",
                        maps_url,
                        use_container_width=True,
                    )

            with c3:

                phone = str(row.get("phone", "")).strip()

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

                if st.button(

                    "✅",

                    key=f"complete_{index}",

                    help="Complete Job",

                    use_container_width=True,

                ):

                    st.success(

                        f"{row.get('name')} marked complete."

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
        build_schedule_candidates,
        queue_customers_for_date,
    )

    candidates = build_schedule_candidates(
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

        schedule_rows["last_service"] = (
            pd.to_datetime(
                schedule_rows["last_service"],
                errors="coerce",
            ).dt.date
        )

        schedule_rows["next_due"] = (
            pd.to_datetime(
                schedule_rows["next_due"],
                errors="coerce",
            ).dt.date
        )

        display_columns = [
            "Schedule",
            "id",
            "name",
            "address",
            "service",
            "last_service",
            "next_due",
            "days_overdue",
            "already_queued",
        ]

        edited_schedule = st.data_editor(
            schedule_rows[display_columns],
            use_container_width=True,
            hide_index=True,
            disabled=[
                "id",
                "name",
                "address",
                "service",
                "last_service",
                "next_due",
                "days_overdue",
                "already_queued",
            ],
            column_config={
                "Schedule": (
                    st.column_config.CheckboxColumn(
                        "Schedule"
                    )
                ),
                "id": None,
                "name": "Customer",
                "address": "Address",
                "service": "Service",
                "last_service": (
                    st.column_config.DateColumn(
                        "Last Service"
                    )
                ),
                "next_due": (
                    st.column_config.DateColumn(
                        "Next Due"
                    )
                ),
                "days_overdue": (
                    st.column_config.NumberColumn(
                        "Days Overdue"
                    )
                ),
                "already_queued": (
                    st.column_config.CheckboxColumn(
                        "Queued"
                    )
                ),
            },
            key=(
                "schedule_due_customers_"
                f"{st.session_state.schedule_editor_version}"
            ),
        )

        selected_ids = edited_schedule.loc[
            edited_schedule["Schedule"]
            & ~edited_schedule["already_queued"],
            "id",
        ].tolist()

        if st.button(
            (
                f"Add {len(selected_ids)} "
                "Selected to Dispatch"
            ),
            type="primary",
            use_container_width=True,
            disabled=not selected_ids,
            key="schedule_add_dispatch",
        ):

            result = queue_customers_for_date(
                selected_ids,
                schedule_date,
            )

            st.success(
                f"Added {result['created']} "
                "customer(s) to dispatch."
            )

            if result["skipped"]:

                st.info(
                    f"Skipped {result['skipped']} "
                    "customer(s) already in dispatch."
                )

            st.rerun()

    else:

        st.success(
            "No active customers are due by this date."
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
                crews=int(crew_count)
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

    route_report_tab, inspector_report_tab = st.tabs(
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
                    [
                        "Application Date",
                        "Customer",
                        "Treatment",
                    ]
                ].drop_duplicates().shape[0]

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

