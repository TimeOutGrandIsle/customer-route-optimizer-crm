"""
app.py

Time Out Lawncare CRM
Main Streamlit Application

This root app.py is the application entry point used locally and by
Streamlit Cloud.

Architecture:
- core/      business logic
- data/      Supabase/PostgreSQL data layer
- services/  routing, geocoding, imports, learning/support services
- tabs/      feature-specific office screens
- ui/        Dispatch and Field Mode

Business rules implemented here:
- Customer Type keeps the Customers tab organized but does not affect routing.
- Every job with status "queued" is Dispatch-ready regardless of scheduled_date.
- Dispatch supports multiple crews.
- Each persistent crew dispatch can be opened in Field Mode.
"""

from __future__ import annotations

import smtplib
import ssl
import traceback
from datetime import date, datetime
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.crm import (
    CUSTOMER_TYPES,
    create_customer,
    edit_customer,
    filter_customers,
    get_dashboard_stats,
    get_depot,
    initialize_system,
    list_customers,
    update_depot,
)
from data.database import (
    create_crew,
    get_crews,
    get_setting,
    set_setting,
    update_crew,
)
from tabs.import_data import render as render_import_data
from ui.dispatch import (
    build_multi_driver_routes,
    cancel_entire_queue,
    cancel_saved_dispatch,
    clear_saved_dispatch,
    create_multi_crew_dispatch,
    crew_dispatch_link,
    dispatch_dashboard,
    get_saved_dispatch_manifest,
    get_saved_dispatches,
    get_dispatch_reschedule_history,
    mark_dispatch_as_sent,
    mark_job_in_progress,
    reassign_saved_dispatch,
    remove_stops_from_saved_dispatch,
    reschedule_dispatch_job,
)


def send_crew_dispatch_email(
    recipient: str,
    dispatch_id: int,
    crew_name: str,
    dispatch_date_value: str,
    field_link: str,
    manifest: List[Dict[str, Any]],
) -> None:
    """
    Send a saved crew dispatch using the existing [email] SMTP secrets.
    """
    email_cfg = st.secrets.get("email", {})
    smtp_server = str(
        email_cfg.get("smtp_server", "smtp.gmail.com")
    ).strip()
    smtp_port = int(
        email_cfg.get("smtp_port", 587)
    )
    username = str(
        email_cfg.get("username", "")
    ).strip()
    password = str(
        email_cfg.get("password", "")
    ).strip()
    from_name = str(
        email_cfg.get("from_name", "Time Out Lawncare")
    ).strip()

    if not username or not password:
        raise RuntimeError(
            "Email SMTP settings are not configured."
        )

    stop_lines = []
    for index, stop in enumerate(manifest, start=1):
        customer = (
            safe_text(stop.get("name"))
            or safe_text(stop.get("customer_name"))
            or f"Stop {index}"
        )
        address = safe_text(stop.get("address"))
        treatment = (
            safe_text(stop.get("treatment_name"))
            or safe_text(stop.get("service"))
        )
        job_id = stop.get("id") or stop.get("job_id")

        parts = [f"{index}. {customer}"]
        if address:
            parts.append(address)
        if treatment:
            parts.append(treatment)
        if job_id:
            parts.append(f"Job #{int(job_id)}")
        stop_lines.append(" — ".join(parts))

    message = EmailMessage()
    message["Subject"] = (
        f"Time Out Lawncare Dispatch #{int(dispatch_id)}"
        f" — {dispatch_date_value}"
    )
    message["From"] = (
        f"{from_name} <{username}>"
        if from_name
        else username
    )
    message["To"] = recipient

    message.set_content(
        "\n".join(
            [
                f"Crew: {crew_name}",
                f"Dispatch #{int(dispatch_id)}",
                f"Date: {dispatch_date_value}",
                "",
                "Open Field Mode:",
                field_link,
                "",
                "Stops:",
                *stop_lines,
            ]
        )
    )

    context = ssl.create_default_context()

    # Preserve certificate verification while avoiding the Python 3.14
    # strict-X509 incompatibility previously encountered with Gmail SMTP.
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT

    with smtplib.SMTP(
        smtp_server,
        smtp_port,
        timeout=30,
    ) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(username, password)
        server.send_message(message)



# ==========================================================
# PAGE CONFIG
# ==========================================================

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

    div[data-testid="stMetric"] {
        border: 1px solid rgba(49, 51, 63, 0.15);
        border-radius: 0.5rem;
        padding: 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================================
# AUTHENTICATION
# ==========================================================

def authenticate() -> tuple[str, str]:
    if not bool(
        st.user.get(
            "is_logged_in",
            False,
        )
    ):
        st.title(
            "Time Out Lawncare CRM"
        )

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
        str(email)
        .strip()
        .casefold():
        str(role)
        .strip()
        .casefold()
        for email, role
        in configured_roles.items()
    }

    current_email = str(
        st.user.get(
            "email",
            "",
        )
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

        if st.button(
            "Sign out"
        ):
            st.logout()

        st.stop()

    return (
        current_email,
        current_role,
    )


current_email, current_role = (
    authenticate()
)

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


# ==========================================================
# SYSTEM INITIALIZATION
# ==========================================================

try:
    initialize_system()
except Exception:
    st.error(
        "The CRM database could not be initialized."
    )
    st.exception(
        traceback.format_exc()
    )
    st.stop()


# ==========================================================
# WORKSPACE MODE
# ==========================================================

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
    from ui.field_view import (
        render as render_field_view,
    )

    render_field_view()
    st.stop()


# ==========================================================
# SESSION STATE
# ==========================================================

DEFAULT_STATE = {
    "selected_customer": None,
    "selected_job": None,
    "selected_route": None,
    "refresh": False,
    "schedule_select_all": False,
    "schedule_editor_version": 0,
    "dispatch_preview_routes": [],
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[
            key
        ] = value


# ==========================================================
# COMMON HELPERS
# ==========================================================

def safe_float(
    value: Any,
    fallback: float = 0.0,
) -> float:
    try:
        if value is None or pd.isna(
            value
        ):
            return float(
                fallback
            )

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return float(
            fallback
        )


def safe_text(
    value: Any,
    fallback: str = "",
) -> str:
    if value is None:
        return fallback

    try:
        if pd.isna(
            value
        ):
            return fallback
    except Exception:
        pass

    return str(
        value
    )


def load_float_setting(
    setting_key: str,
    fallback: float,
) -> float:
    try:
        return float(
            get_setting(
                setting_key,
                str(
                    fallback
                ),
            )
            or fallback
        )

    except (
        TypeError,
        ValueError,
    ):
        return float(
            fallback
        )



def load_bool_setting(
    setting_key: str,
    fallback: bool = False,
) -> bool:
    try:
        value = get_setting(
            setting_key,
            "1" if fallback else "0",
        )
    except Exception:
        return bool(fallback)

    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def get_live_customers() -> pd.DataFrame:
    try:
        return list_customers()
    except Exception:
        st.error(
            "Unable to load customers."
        )
        st.exception(
            traceback.format_exc()
        )
        return pd.DataFrame()


def get_live_dispatch() -> Dict[str, Any]:
    try:
        return dispatch_dashboard()
    except Exception:
        st.error(
            "Unable to load dispatch."
        )
        st.exception(
            traceback.format_exc()
        )

        return {
            "jobs": [],
            "route": [],
            "manifest": [],
            "summary": {},
            "statistics": {},
            "dataframe": pd.DataFrame(),
        }


# ==========================================================
# HEADER
# ==========================================================

st.title(
    "🌱 Time Out Lawncare"
)

stats = get_dashboard_stats()

# Saved crew dispatches are persistent routes and are separate from the
# live queued-job dashboard. Load them here so active saved routes are
# visible in the office header and Dashboard as soon as they are created.
try:
    header_saved_dispatches = get_saved_dispatches() or []
except Exception:
    header_saved_dispatches = []

header_saved_df = pd.DataFrame(header_saved_dispatches)

if header_saved_df.empty:
    active_saved_df = pd.DataFrame()
else:
    header_status = (
        header_saved_df.get(
            "status",
            pd.Series("", index=header_saved_df.index),
        )
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    active_saved_df = header_saved_df[
        ~header_status.isin(
            [
                "completed",
                "cancelled",
                "canceled",
                "rescheduled",
            ]
        )
    ].copy()

active_saved_count = len(active_saved_df)

header_1, header_2, header_3, header_4, header_5 = (
    st.columns(
        5
    )
)

header_1.metric(
    "Customers",
    stats.get(
        "total_customers",
        0,
    ),
)

header_2.metric(
    "Queued Jobs",
    stats.get(
        "queued_jobs",
        0,
    ),
)

header_3.metric(
    "Active Dispatches",
    active_saved_count,
)

header_4.metric(
    "Completed",
    stats.get(
        "completed_jobs",
        0,
    ),
)

header_5.metric(
    "Commercial",
    (
        stats.get(
            "small_commercial_customers",
            0,
        )
        + stats.get(
            "commercial_customers",
            0,
        )
    ),
)

st.divider()

customers = (
    get_live_customers()
)

dispatch = (
    get_live_dispatch()
)


# ==========================================================
# TABS
# ==========================================================

(
    tab_dashboard,
    tab_customers,
    tab_dispatch,
    tab_schedule,
    tab_treatments,
    tab_applications,
    tab_invoicing,
    tab_routes,
    tab_reports,
    tab_import,
    tab_settings,
) = st.tabs(
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
# DASHBOARD
# ==========================================================

with tab_dashboard:
    st.header(
        "Business Dashboard"
    )

    dashboard_stats = (
        dispatch.get(
            "statistics",
            {},
        )
    )

    dash_1, dash_2, dash_3, dash_4, dash_5 = (
        st.columns(
            5
        )
    )

    dash_1.metric(
        "Dispatch Ready",
        dashboard_stats.get(
            "dispatch_ready",
            dashboard_stats.get(
                "queued",
                0,
            ),
        ),
    )

    dash_2.metric(
        "Active Dispatches",
        active_saved_count,
    )

    dash_3.metric(
        "Dispatched Stops",
        dashboard_stats.get(
            "dispatched",
            0,
        ),
    )

    dash_4.metric(
        "In Progress",
        dashboard_stats.get(
            "in_progress",
            0,
        ),
    )

    dash_5.metric(
        "Completed",
        dashboard_stats.get(
            "completed",
            0,
        ),
    )

    future_queued = int(
        dashboard_stats.get(
            "future_queued_included",
            dashboard_stats.get(
                "future_active",
                0,
            ),
        )
        or 0
    )

    if future_queued:
        st.info(
            f"{future_queued} queued job(s) have future scheduled dates "
            "and are correctly included in the Dispatch-ready pool."
        )

    st.divider()

    st.subheader(
        "Active Crew Dispatches"
    )

    if active_saved_df.empty:
        st.info(
            "No active saved crew dispatches."
        )
    else:
        active_dashboard_columns = [
            column
            for column in (
                "id",
                "dispatch_date",
                "crew_name",
                "route_number",
                "status",
                "stop_count",
                "completed_count",
            )
            if column in active_saved_df.columns
        ]

        active_dashboard_display = (
            active_saved_df[active_dashboard_columns]
            .copy()
        )

        st.dataframe(
            active_dashboard_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": "Dispatch #",
                "dispatch_date": "Dispatch Date",
                "crew_name": "Crew",
                "route_number": "Route",
                "status": "Status",
                "stop_count": "Stops",
                "completed_count": "Completed",
            },
        )

    st.divider()

    st.subheader(
        "Dispatch-Ready Route Preview"
    )

    summary = dispatch.get(
        "summary",
        {},
    )

    if summary:
        summary_1, summary_2, summary_3, summary_4 = (
            st.columns(
                4
            )
        )

        summary_1.metric(
            "Stops",
            int(
                summary.get(
                    "stops",
                    0,
                )
                or 0
            ),
        )

        summary_2.metric(
            "Miles",
            f"{safe_float(summary.get('distance_miles')):.1f}",
        )

        summary_3.metric(
            "Drive",
            f"{safe_float(summary.get('drive_minutes')):.0f} min",
        )

        summary_4.metric(
            "Total",
            f"{safe_float(summary.get('total_minutes')):.0f} min",
        )

        maps = safe_text(
            summary.get(
                "google_maps"
            )
        )

        if maps:
            st.link_button(
                "Open Route in Google Maps",
                maps,
                use_container_width=True,
            )

    else:
        st.info(
            "No dispatch route is available."
        )

    manifest = dispatch.get(
        "manifest",
        [],
    )

    if manifest:
        st.subheader(
            "Driver Manifest"
        )

        st.dataframe(
            pd.DataFrame(
                manifest
            ),
            use_container_width=True,
            hide_index=True,
        )


# ==========================================================
# CUSTOMERS
# ==========================================================

with tab_customers:
    st.header(
        "Customers"
    )

    st.caption(
        "Customer Type keeps this screen organized. "
        "It does not separate or restrict route optimization."
    )

    type_col, search_col, status_col = (
        st.columns(
            [1.3, 2.4, 1]
        )
    )

    customer_type_filter = (
        type_col.selectbox(
            "Customer Type",
            options=[
                "Residential",
                "Small Commercial",
                "Commercial",
                "All",
            ],
            index=0,
            key="customers_type_filter",
        )
    )

    customer_search = (
        search_col.text_input(
            "Search Customers",
            placeholder=(
                "Name, account, address, phone, email..."
            ),
            key="customer_search",
        )
    )

    active_filter = (
        status_col.selectbox(
            "Status",
            options=[
                "Active",
                "All",
            ],
            key="customer_active_filter",
        )
    )

    customer_df = filter_customers(
        customers,
        customer_type=(
            customer_type_filter
        ),
        search=(
            customer_search
        ),
        active_only=(
            active_filter
            == "Active"
        ),
    )

    customer_metric_1, customer_metric_2 = (
        st.columns(
            2
        )
    )

    customer_metric_1.metric(
        "Shown",
        len(
            customer_df
        ),
    )

    customer_metric_2.metric(
        "All Customers",
        len(
            customers
        ),
    )

    display_columns = [
        column
        for column
        in (
            "customer_number",
            "name",
            "account_name",
            "customer_type",
            "address",
            "phone",
            "email",
            "square_feet",
            "turf_type",
            "service",
            "quote",
            "active",
        )
        if column
        in customer_df.columns
    ]

    if customer_df.empty:
        st.info(
            "No customers match the selected view."
        )
    else:
        st.dataframe(
            customer_df[
                display_columns
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    edit_tab, add_tab = st.tabs(
        [
            "Edit Customer",
            "Add Customer",
        ]
    )

    with edit_tab:
        if customers.empty:
            st.info(
                "No customers are available to edit."
            )
        else:
            customer_options = (
                customers[
                    "id"
                ]
                .astype(
                    int
                )
                .tolist()
            )

            customer_labels = {}

            for _, row in customers.iterrows():
                name = safe_text(
                    row.get(
                        "name"
                    )
                )

                account = safe_text(
                    row.get(
                        "account_name"
                    )
                )

                number = safe_text(
                    row.get(
                        "customer_number"
                    )
                )

                label = (
                    account
                    if account
                    else name
                )

                if account and name:
                    label += (
                        f" — {name}"
                    )

                if number:
                    label += (
                        f" — #{number}"
                    )

                customer_labels[
                    int(
                        row[
                            "id"
                        ]
                    )
                ] = label

            edit_customer_id = (
                st.selectbox(
                    "Choose Customer",
                    options=customer_options,
                    format_func=lambda value: (
                        customer_labels[
                            value
                        ]
                    ),
                    key="edit_customer_selection",
                )
            )

            selected_customer = (
                customers[
                    customers[
                        "id"
                    ].astype(
                        int
                    )
                    == int(
                        edit_customer_id
                    )
                ]
                .iloc[0]
            )

            current_type = (
                safe_text(
                    selected_customer.get(
                        "customer_type"
                    ),
                    "Residential",
                )
            )

            if current_type not in CUSTOMER_TYPES:
                current_type = (
                    "Residential"
                )

            with st.form(
                "edit_customer_form"
            ):
                edit_1, edit_2, edit_3 = (
                    st.columns(
                        [2, 1, 1]
                    )
                )

                customer_name = (
                    edit_1.text_input(
                        "Customer / Contact Name",
                        value=safe_text(
                            selected_customer.get(
                                "name"
                            )
                        ),
                    )
                )

                customer_number = (
                    edit_2.text_input(
                        "Customer Number",
                        value=safe_text(
                            selected_customer.get(
                                "customer_number"
                            )
                        ),
                    )
                )

                customer_type = (
                    edit_3.selectbox(
                        "Customer Type",
                        options=list(
                            CUSTOMER_TYPES
                        ),
                        index=list(
                            CUSTOMER_TYPES
                        ).index(
                            current_type
                        ),
                    )
                )

                account_name = (
                    st.text_input(
                        "Commercial Account / Property Name",
                        value=safe_text(
                            selected_customer.get(
                                "account_name"
                            )
                        ),
                        help=(
                            "Optional. Useful for commercial accounts "
                            "where the property/account name differs "
                            "from the contact name."
                        ),
                    )
                )

                current_full_address = (
                    safe_text(
                        selected_customer.get(
                            "address"
                        )
                    )
                )

                full_address = (
                    st.text_input(
                        "Full Address",
                        value=current_full_address,
                        help=(
                            "Edit this field to replace the complete address, "
                            "or edit the separate address fields below to have "
                            "the full address rebuilt automatically."
                        ),
                    )
                )

                street_address = (
                    st.text_input(
                        "Street Address",
                        value=safe_text(
                            selected_customer.get(
                                "street_address"
                            )
                        ),
                    )
                )

                city_col, state_col, zip_col = (
                    st.columns(
                        [2, 1, 1]
                    )
                )

                city = (
                    city_col.text_input(
                        "City",
                        value=safe_text(
                            selected_customer.get(
                                "city"
                            )
                        ),
                    )
                )

                state = (
                    state_col.text_input(
                        "State",
                        value=safe_text(
                            selected_customer.get(
                                "state"
                            )
                        ),
                    )
                )

                zipcode = (
                    zip_col.text_input(
                        "ZIP",
                        value=safe_text(
                            selected_customer.get(
                                "zip"
                            )
                        ),
                    )
                )

                county = (
                    st.text_input(
                        "County",
                        value=safe_text(
                            selected_customer.get(
                                "county"
                            )
                        ),
                    )
                )

                phone_col, email_col = (
                    st.columns(
                        2
                    )
                )

                phone = phone_col.text_input(
                    "Phone",
                    value=safe_text(
                        selected_customer.get(
                            "phone"
                        )
                    ),
                )

                email = email_col.text_input(
                    "Email",
                    value=safe_text(
                        selected_customer.get(
                            "email"
                        )
                    ),
                )

                text_phone = (
                    st.text_input(
                        "Text Phone",
                        value=safe_text(
                            selected_customer.get(
                                "text_phone"
                            )
                        ),
                    )
                )

                area_col, quote_col = (
                    st.columns(
                        2
                    )
                )

                square_feet = (
                    area_col.number_input(
                        "Square Feet",
                        min_value=0.0,
                        value=safe_float(
                            selected_customer.get(
                                "square_feet"
                            )
                        ),
                    )
                )

                quote = (
                    quote_col.number_input(
                        "Quote",
                        min_value=0.0,
                        value=safe_float(
                            selected_customer.get(
                                "quote"
                            )
                        ),
                        format="%.2f",
                    )
                )

                turf_col, irrigation_col = (
                    st.columns(
                        2
                    )
                )

                turf_type = (
                    turf_col.text_input(
                        "Turf Type",
                        value=safe_text(
                            selected_customer.get(
                                "turf_type"
                            )
                        ),
                    )
                )

                irrigation = (
                    irrigation_col.text_input(
                        "Irrigation",
                        value=safe_text(
                            selected_customer.get(
                                "irrigation"
                            )
                        ),
                    )
                )

                payment_method = (
                    st.text_input(
                        "Payment Method",
                        value=safe_text(
                            selected_customer.get(
                                "payment_method"
                            )
                        ),
                    )
                )

                service = (
                    st.text_input(
                        "Primary Service",
                        value=safe_text(
                            selected_customer.get(
                                "service"
                            )
                        ),
                    )
                )

                special_instructions = (
                    st.text_area(
                        "Special Instructions / Notes",
                        value=safe_text(
                            selected_customer.get(
                                "special_instructions"
                            )
                        ),
                    )
                )

                active = (
                    st.checkbox(
                        "Active Customer",
                        value=bool(
                            selected_customer.get(
                                "active",
                                1,
                            )
                        ),
                    )
                )

                auto_email_invoices = (
                    st.checkbox(
                        "Automatically Email Invoices",
                        value=load_bool_setting(
                            (
                                "auto_email_customer_"
                                f"{int(edit_customer_id)}"
                            ),
                            True,
                        ),
                        help=(
                            "When the company-wide auto-send setting is ON, "
                            "completed-job invoices for this customer are "
                            "emailed automatically. Turn this OFF to create "
                            "the invoice as a Draft without emailing it."
                        ),
                    )
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
                        try:
                            edit_customer(
                                int(
                                    edit_customer_id
                                ),
                                customer_number=(
                                    customer_number.strip()
                                    or None
                                ),
                                name=(
                                    customer_name.strip()
                                ),
                                customer_type=(
                                    customer_type
                                ),
                                account_name=(
                                    account_name.strip()
                                    or None
                                ),
                                street_address=(
                                    street_address.strip()
                                ),
                                city=(
                                    city.strip()
                                ),
                                state=(
                                    state.strip()
                                ),
                                zip=(
                                    zipcode.strip()
                                ),
                                county=(
                                    county.strip()
                                ),
                                phone=(
                                    phone.strip()
                                ),
                                email=(
                                    email.strip()
                                ),
                                text_phone=(
                                    text_phone.strip()
                                ),
                                square_feet=(
                                    square_feet
                                ),
                                turf_type=(
                                    turf_type.strip()
                                ),
                                irrigation=(
                                    irrigation.strip()
                                ),
                                payment_method=(
                                    payment_method.strip()
                                ),
                                quote=quote,
                                special_instructions=(
                                    special_instructions.strip()
                                ),
                                service=(
                                    service.strip()
                                ),
                                active=int(
                                    active
                                ),
                                **(
                                    {
                                        "address": (
                                            full_address.strip()
                                        )
                                    }
                                    if (
                                        full_address.strip()
                                        != current_full_address.strip()
                                    )
                                    else {}
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Customer could not be updated: "
                                f"{exc}"
                            )
                        else:
                            set_setting(
                                (
                                    "auto_email_customer_"
                                    f"{int(edit_customer_id)}"
                                ),
                                (
                                    "1"
                                    if auto_email_invoices
                                    else "0"
                                ),
                            )
                            st.success(
                                "Customer updated successfully."
                            )
                            st.rerun()

    with add_tab:
        with st.form(
            "add_customer_form"
        ):
            add_1, add_2 = (
                st.columns(
                    2
                )
            )

            new_name = (
                add_1.text_input(
                    "Customer / Contact Name"
                )
            )

            new_type = (
                add_2.selectbox(
                    "Customer Type",
                    options=list(
                        CUSTOMER_TYPES
                    ),
                )
            )

            new_account = (
                st.text_input(
                    "Commercial Account / Property Name"
                )
            )

            new_address = (
                st.text_input(
                    "Address"
                )
            )

            new_service = (
                st.text_input(
                    "Service"
                )
            )

            new_auto_email_invoices = (
                st.checkbox(
                    "Automatically Email Invoices",
                    value=True,
                    help=(
                        "Turn this OFF if this customer's invoices should "
                        "be created as Drafts instead of being emailed "
                        "automatically."
                    ),
                )
            )

            add_customer_submit = (
                st.form_submit_button(
                    "Add Customer",
                    type="primary",
                    use_container_width=True,
                )
            )

            if add_customer_submit:
                try:
                    new_customer_id = create_customer(
                        name=(
                            new_name
                        ),
                        address=(
                            new_address
                        ),
                        service=(
                            new_service
                        ),
                        customer_type=(
                            new_type
                        ),
                        account_name=(
                            new_account.strip()
                            or None
                        ),
                    )

                    if new_customer_id is not None:
                        set_setting(
                            (
                                "auto_email_customer_"
                                f"{int(new_customer_id)}"
                            ),
                            (
                                "1"
                                if new_auto_email_invoices
                                else "0"
                            ),
                        )

                except Exception as exc:
                    st.error(
                        f"Customer could not be added: {exc}"
                    )
                else:
                    st.success(
                        "Customer added successfully."
                    )
                    st.rerun()


# ==========================================================
# DISPATCH
# ==========================================================

with tab_dispatch:
    st.header(
        "Dispatch"
    )

    st.caption(
        "Every queued job is available here regardless of its scheduled date."
    )

    queued_jobs = dispatch.get(
        "jobs",
        [],
    )

    dispatch_stats = dispatch.get(
        "statistics",
        {},
    )

    dispatch_1, dispatch_2, dispatch_3, dispatch_4 = (
        st.columns(
            4
        )
    )

    dispatch_1.metric(
        "Dispatch Ready",
        len(
            queued_jobs
        ),
    )

    dispatch_2.metric(
        "In Progress",
        dispatch_stats.get(
            "in_progress",
            0,
        ),
    )

    dispatch_3.metric(
        "Completed",
        dispatch_stats.get(
            "completed",
            0,
        ),
    )

    dispatch_4.metric(
        "Future-Dated Queued",
        dispatch_stats.get(
            "future_queued_included",
            0,
        ),
    )

    if queued_jobs:
        st.subheader(
            "Dispatch Pool"
        )

        dispatch_pool_df = (
            pd.DataFrame(
                queued_jobs
            )
        )

        pool_columns = [
            column
            for column
            in (
                "id",
                "name",
                "account_name",
                "customer_type",
                "treatment_name",
                "service",
                "scheduled_date",
                "address",
                "status",
            )
            if column
            in dispatch_pool_df.columns
        ]

        st.dataframe(
            dispatch_pool_df[
                pool_columns
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": None,
                "name": "Customer",
                "account_name": "Account",
                "customer_type": "Type",
                "treatment_name": "Treatment",
                "scheduled_date": "Scheduled",
                "address": "Address",
                "status": "Status",
            },
        )

    else:
        st.info(
            "There are no queued jobs."
        )

    if queued_jobs:
        with st.expander(
            "Postpone / Reschedule Queued Job",
            expanded=False,
        ):
            queued_labels = {}
            queued_by_id = {}

            for job in queued_jobs:
                job_id = int(job.get("id"))
                queued_by_id[job_id] = job
                customer_name = (
                    safe_text(job.get("name"))
                    or safe_text(job.get("customer_name"))
                    or f"Job #{job_id}"
                )
                treatment = (
                    safe_text(job.get("treatment_name"))
                    or safe_text(job.get("service"))
                )
                scheduled = safe_text(job.get("scheduled_date"))
                parts = [customer_name]
                if treatment:
                    parts.append(treatment)
                if scheduled:
                    parts.append(f"Currently {scheduled}")
                parts.append(f"Job #{job_id}")
                queued_labels[job_id] = " — ".join(parts)

            reschedule_queue_job_id = st.selectbox(
                "Queued Job",
                options=list(queued_labels),
                format_func=lambda value: queued_labels[value],
                key="reschedule_queued_job_id",
            )

            selected_queue_job = queued_by_id[
                int(reschedule_queue_job_id)
            ]

            try:
                current_queue_date = pd.to_datetime(
                    selected_queue_job.get("scheduled_date"),
                    errors="coerce",
                )
                if pd.isna(current_queue_date):
                    current_queue_date = date.today()
                else:
                    current_queue_date = current_queue_date.date()
            except Exception:
                current_queue_date = date.today()

            new_queue_date = st.date_input(
                "New Scheduled Date",
                value=current_queue_date,
                key="reschedule_queued_new_date",
            )

            if st.button(
                "Reschedule Job",
                type="primary",
                use_container_width=True,
                key="reschedule_queued_job_button",
            ):
                reschedule_dispatch_job(
                    int(reschedule_queue_job_id),
                    new_queue_date,
                    return_to_queue=False,
                )
                st.success(
                    f"Job moved to {new_queue_date:%B %d, %Y}."
                )
                st.rerun()

    st.divider()

    st.subheader(
        "Crew Dispatch Builder"
    )

    active_crews = get_crews(
        active_only=True
    )

    if (
        active_crews is None
        or active_crews.empty
    ):
        st.warning(
            "No active crews are configured. "
            "Add at least one crew in Settings."
        )

        selected_crew_ids: List[int] = []

    else:
        crew_labels = {
            int(
                row[
                    "id"
                ]
            ): safe_text(
                row.get(
                    "crew_name"
                )
            )
            for _, row in active_crews.iterrows()
        }

        selected_crew_ids = (
            st.multiselect(
                "Crews for this Dispatch",
                options=list(
                    crew_labels
                ),
                default=list(
                    crew_labels
                ),
                format_func=lambda value: (
                    crew_labels[
                        value
                    ]
                ),
            )
        )

    max_stops = (
        st.number_input(
            "Maximum Stops per Route",
            min_value=1,
            max_value=50,
            value=int(
                load_float_setting(
                    "max_stops_per_route",
                    10,
                )
            ),
            step=1,
        )
    )

    preview_col, create_col, clear_col = (
        st.columns(
            3
        )
    )

    preview_routes = (
        preview_col.button(
            "Preview Crew Routes",
            use_container_width=True,
            disabled=(
                not queued_jobs
                or not selected_crew_ids
            ),
        )
    )

    create_dispatches = (
        create_col.button(
            "Create Crew Dispatches",
            type="primary",
            use_container_width=True,
            disabled=(
                not queued_jobs
                or not selected_crew_ids
            ),
        )
    )

    clear_queue = (
        clear_col.button(
            "Clear Active Queue",
            use_container_width=True,
            type="secondary",
            disabled=(
                not queued_jobs
            ),
        )
    )

    if preview_routes:
        selected_crews = (
            active_crews[
                active_crews[
                    "id"
                ]
                .astype(
                    int
                )
                .isin(
                    selected_crew_ids
                )
            ]
            .to_dict(
                "records"
            )
        )

        st.session_state[
            "dispatch_preview_routes"
        ] = build_multi_driver_routes(
            crews=selected_crews,
            max_stops_per_route=int(
                max_stops
            ),
        )

    if create_dispatches:
        selected_crews = (
            active_crews[
                active_crews[
                    "id"
                ]
                .astype(
                    int
                )
                .isin(
                    selected_crew_ids
                )
            ]
            .to_dict(
                "records"
            )
        )

        try:
            created = (
                create_multi_crew_dispatch(
                    selected_crews,
                    dispatch_date=date.today(),
                    max_stops_per_route=int(
                        max_stops
                    ),
                )
            )

        except Exception:
            st.error(
                "Crew dispatches could not be created."
            )
            st.exception(
                traceback.format_exc()
            )
        else:
            st.success(
                f"Created {len(created)} crew dispatch(es)."
            )

            st.session_state[
                "dispatch_preview_routes"
            ] = []

            st.rerun()

    if clear_queue:
        cancel_entire_queue()
        st.success(
            "Active dispatch queue cleared."
        )
        st.rerun()

    preview = st.session_state.get(
        "dispatch_preview_routes",
        [],
    )

    if preview:
        st.divider()
        st.subheader(
            "Crew Route Preview"
        )

        for crew_route in preview:
            st.markdown(
                f"### {crew_route.get('crew', 'Crew')}"
            )

            route_summary = (
                crew_route.get(
                    "summary",
                    {},
                )
            )

            p1, p2, p3, p4 = (
                st.columns(
                    4
                )
            )

            p1.metric(
                "Stops",
                int(
                    route_summary.get(
                        "stops",
                        0,
                    )
                ),
            )

            p2.metric(
                "Miles",
                f"{safe_float(route_summary.get('distance_miles')):.1f}",
            )

            p3.metric(
                "Drive",
                f"{safe_float(route_summary.get('drive_minutes')):.0f} min",
            )

            p4.metric(
                "Total",
                f"{safe_float(route_summary.get('total_minutes')):.0f} min",
            )

            maps = (
                crew_route.get(
                    "google_maps"
                )
                or route_summary.get(
                    "google_maps"
                )
            )

            if maps:
                st.link_button(
                    f"Open {crew_route.get('crew', 'Crew')} Route in Google Maps",
                    maps,
                    use_container_width=True,
                )

            manifest = crew_route.get(
                "manifest",
                [],
            )

            if manifest:
                st.dataframe(
                    pd.DataFrame(
                        manifest
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

    st.divider()

    st.subheader(
        "Saved Crew Dispatches"
    )

    saved_dispatches = get_saved_dispatches()

    if saved_dispatches:
        saved_df = pd.DataFrame(
            saved_dispatches
        )

        saved_columns = [
            column
            for column
            in (
                "id",
                "dispatch_date",
                "crew_name",
                "route_number",
                "status",
                "stop_count",
                "completed_count",
            )
            if column in saved_df.columns
        ]

        status_series = (
            saved_df.get(
                "status",
                pd.Series(
                    "",
                    index=saved_df.index,
                ),
            )
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        active_mask = ~status_series.isin(
            [
                "completed",
                "cancelled",
                "canceled",
                "rescheduled",
            ]
        )

        completed_mask = status_series.eq(
            "completed"
        )

        saved_dates = pd.to_datetime(
            saved_df.get(
                "completed_at",
                saved_df.get(
                    "dispatch_date",
                    pd.Series(
                        pd.NaT,
                        index=saved_df.index,
                    ),
                ),
            ),
            errors="coerce",
            utc=True,
        )

        recent_cutoff = (
            pd.Timestamp.now(tz="UTC").normalize()
            - pd.Timedelta(days=30)
        )

        recent_completed_mask = (
            completed_mask
            & saved_dates.ge(
                recent_cutoff
            )
        )

        history_mask = (
            ~active_mask
            & ~recent_completed_mask
        )

        active_df = saved_df[
            active_mask
        ].copy()

        recent_completed_df = saved_df[
            recent_completed_mask
        ].copy()

        history_df = saved_df[
            history_mask
        ].copy()

        st.markdown(
            "#### Active Dispatches"
        )

        if active_df.empty:
            st.info(
                "No active saved crew dispatches."
            )
        else:
            st.dataframe(
                active_df[saved_columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": "Dispatch #",
                    "dispatch_date": "Dispatch Date",
                    "crew_name": "Crew",
                    "route_number": "Route",
                    "status": "Status",
                    "stop_count": "Stops",
                    "completed_count": "Completed",
                },
            )

        st.markdown(
            "#### Recent Completed — Last 30 Days"
        )

        if recent_completed_df.empty:
            st.caption(
                "No completed dispatches in the last 30 days."
            )
        else:
            recent_completed_df = (
                recent_completed_df.assign(
                    _sort_date=pd.to_datetime(
                        recent_completed_df.get(
                            "completed_at",
                            recent_completed_df.get(
                                "dispatch_date"
                            ),
                        ),
                        errors="coerce",
                    )
                )
                .sort_values(
                    "_sort_date",
                    ascending=False,
                )
                .drop(
                    columns=["_sort_date"]
                )
            )

            st.dataframe(
                recent_completed_df[
                    saved_columns
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": "Dispatch #",
                    "dispatch_date": "Dispatch Date",
                    "crew_name": "Crew",
                    "route_number": "Route",
                    "status": "Status",
                    "stop_count": "Stops",
                    "completed_count": "Completed",
                },
            )

        st.markdown(
            "#### Manage Saved Dispatch"
        )

        manageable = active_df.copy()

        if "status" in manageable.columns:
            normalized_saved_status = (
                manageable["status"]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.lower()
            )
            manageable = manageable[
                ~normalized_saved_status.isin(
                    [
                        "completed",
                        "cancelled",
                        "canceled",
                        "rescheduled",
                    ]
                )
            ].copy()

        if manageable.empty:
            st.caption(
                "There are no active saved dispatches to manage."
            )
        else:
            dispatch_labels = {}

            for _, row in manageable.iterrows():
                dispatch_id = int(row["id"])
                parts = [
                    safe_text(row.get("dispatch_date")),
                    safe_text(row.get("crew_name"))
                    or "Unassigned Crew",
                ]

                route_number = safe_text(
                    row.get("route_number")
                )
                if route_number:
                    parts.append(
                        f"Route {route_number}"
                    )

                parts.extend(
                    [
                        safe_text(row.get("status"))
                        or "Unknown",
                        f"Dispatch #{dispatch_id}",
                    ]
                )

                dispatch_labels[dispatch_id] = (
                    " — ".join(
                        part
                        for part in parts
                        if part
                    )
                )

            def _clear_saved_dispatch_management_state(
                clear_dispatch_selection=False,
            ):
                """
                Clear widget state that belongs to the previously managed
                saved dispatch so selections/confirmations never carry
                over to another Dispatch #.
                """
                state_keys = [
                    "saved_dispatch_new_crew",
                    "saved_dispatch_remove_stops",
                    "reschedule_saved_job_id",
                    "reschedule_saved_new_date",
                    "confirm_cancel_saved_dispatch",
                ]

                for state_key in state_keys:
                    st.session_state.pop(
                        state_key,
                        None,
                    )

                if clear_dispatch_selection:
                    st.session_state.pop(
                        "manage_saved_dispatch_id",
                        None,
                    )

            selected_saved_dispatch_id = st.selectbox(
                "Saved Dispatch",
                options=list(dispatch_labels),
                format_func=lambda value: (
                    dispatch_labels[value]
                ),
                key="manage_saved_dispatch_id",
                on_change=(
                    _clear_saved_dispatch_management_state
                ),
            )

            st.caption(
                f"Managing Dispatch #{int(selected_saved_dispatch_id)}"
            )

            selected_manifest = (
                get_saved_dispatch_manifest(
                    int(
                        selected_saved_dispatch_id
                    )
                )
            )

            selected_saved_row = manageable[
                manageable["id"].astype(int)
                == int(selected_saved_dispatch_id)
            ]

            if not selected_saved_row.empty:
                selected_saved_record = (
                    selected_saved_row.iloc[0].to_dict()
                )
            else:
                selected_saved_record = {}

            crew_id_value = selected_saved_record.get(
                "crew_id"
            )
            crew_name_value = (
                safe_text(
                    selected_saved_record.get(
                        "crew_name"
                    )
                )
                or "Crew"
            )
            dispatch_date_value = safe_text(
                selected_saved_record.get(
                    "dispatch_date"
                )
            )

            crew_email = ""
            if crew_id_value is not None:
                try:
                    all_crews_for_email = get_crews(
                        active_only=False
                    )
                    if (
                        all_crews_for_email is not None
                        and not all_crews_for_email.empty
                    ):
                        crew_match = all_crews_for_email[
                            all_crews_for_email["id"].astype(int)
                            == int(crew_id_value)
                        ]
                        if not crew_match.empty:
                            crew_email = safe_text(
                                crew_match.iloc[0].get(
                                    "email"
                                )
                            ).strip()
                except Exception:
                    crew_email = ""

            app_base_url = str(
                st.secrets.get(
                    "APP_BASE_URL",
                    "https://timeout-lawncare-crm.streamlit.app",
                )
            ).strip()

            field_link = crew_dispatch_link(
                int(selected_saved_dispatch_id),
                app_base_url,
            )

            email_col, link_col = st.columns(2)

            email_disabled = (
                not crew_email
                or not field_link
                or not selected_manifest
            )

            if email_col.button(
                (
                    f"Email Dispatch #{int(selected_saved_dispatch_id)} "
                    f"to {crew_name_value}"
                ),
                use_container_width=True,
                disabled=email_disabled,
                key=(
                    "email_saved_dispatch_"
                    f"{int(selected_saved_dispatch_id)}"
                ),
            ):
                try:
                    send_crew_dispatch_email(
                        recipient=crew_email,
                        dispatch_id=int(
                            selected_saved_dispatch_id
                        ),
                        crew_name=crew_name_value,
                        dispatch_date_value=(
                            dispatch_date_value
                        ),
                        field_link=field_link,
                        manifest=selected_manifest,
                    )
                    mark_dispatch_as_sent(
                        int(
                            selected_saved_dispatch_id
                        )
                    )
                    st.success(
                        f"Dispatch #{int(selected_saved_dispatch_id)} "
                        f"emailed to {crew_email}."
                    )
                except Exception:
                    st.error(
                        "The dispatch email could not be sent."
                    )
                    st.exception(
                        traceback.format_exc()
                    )

            if field_link:
                link_col.link_button(
                    (
                        f"Open Dispatch #{int(selected_saved_dispatch_id)} "
                        "Crew Link"
                    ),
                    field_link,
                    use_container_width=True,
                )

            if not crew_email:
                st.caption(
                    "Add an email address for this crew in Settings "
                    "to enable dispatch email."
                )

            management_tabs = st.tabs(
                [
                    "Reassign Crew",
                    "Edit Stops",
                    "Postpone / Reschedule",
                    "Return to Queue",
                    "Cancel Dispatch",
                ]
            )

            with management_tabs[0]:
                crews_for_reassignment = get_crews(
                    active_only=True
                )

                if (
                    crews_for_reassignment is None
                    or crews_for_reassignment.empty
                ):
                    st.warning(
                        "No active crews are available."
                    )
                else:
                    reassign_labels = {
                        int(row["id"]): (
                            safe_text(
                                row.get("crew_name")
                            )
                            or f"Crew {int(row['id'])}"
                        )
                        for _, row
                        in crews_for_reassignment.iterrows()
                    }

                    new_crew_id = st.selectbox(
                        "Assign Remaining Stops To",
                        options=list(
                            reassign_labels
                        ),
                        format_func=lambda value: (
                            reassign_labels[value]
                        ),
                        key="saved_dispatch_new_crew",
                    )

                    if st.button(
                        "Reassign Crew",
                        type="primary",
                        use_container_width=True,
                        key="reassign_saved_dispatch",
                    ):
                        reassign_saved_dispatch(
                            int(
                                selected_saved_dispatch_id
                            ),
                            int(new_crew_id),
                        )
                        st.success(
                            "Unfinished stops reassigned to "
                            f"{reassign_labels[new_crew_id]}."
                        )
                        _clear_saved_dispatch_management_state()
                        st.rerun()

            with management_tabs[1]:
                unfinished_stops = [
                    stop
                    for stop in selected_manifest
                    if safe_text(
                        stop.get("status")
                    ).strip().lower()
                    not in {
                        "completed",
                        "cancelled",
                        "canceled",
                    }
                ]

                if not unfinished_stops:
                    st.info(
                        "This dispatch has no unfinished stops to edit."
                    )
                else:
                    stop_labels = {}

                    for stop in unfinished_stops:
                        job_id = (
                            stop.get("id")
                            or stop.get("job_id")
                        )

                        if job_id is None:
                            continue

                        job_id = int(job_id)

                        customer_name = (
                            safe_text(
                                stop.get("name")
                            )
                            or safe_text(
                                stop.get(
                                    "customer_name"
                                )
                            )
                            or f"Job #{job_id}"
                        )

                        address = safe_text(
                            stop.get("address")
                        )

                        stop_labels[job_id] = (
                            f"Dispatch #{int(selected_saved_dispatch_id)}"
                            f" — Job #{job_id}"
                            f" — {customer_name}"
                            + (
                                f" — {address}"
                                if address
                                else ""
                            )
                        )

                    stops_to_remove = st.multiselect(
                        "Customers to Remove From This Dispatch",
                        options=list(
                            stop_labels
                        ),
                        format_func=lambda value: (
                            stop_labels[value]
                        ),
                        key="saved_dispatch_remove_stops",
                    )

                    st.caption(
                        "Removed customers return to the general "
                        "Dispatch queue."
                    )

                    if st.button(
                        "Remove Selected Customers",
                        type="secondary",
                        use_container_width=True,
                        disabled=(
                            not stops_to_remove
                        ),
                        key="remove_saved_dispatch_stops",
                    ):
                        changed = (
                            remove_stops_from_saved_dispatch(
                                int(
                                    selected_saved_dispatch_id
                                ),
                                stops_to_remove,
                            )
                        )
                        st.success(
                            f"{changed} stop"
                            f"{'' if changed == 1 else 's'} "
                            "returned to the queue."
                        )
                        _clear_saved_dispatch_management_state()
                        st.rerun()

            with management_tabs[2]:
                unfinished_for_reschedule = [
                    stop
                    for stop in selected_manifest
                    if safe_text(stop.get("status")).strip().lower()
                    not in {
                        "completed",
                        "cancelled",
                        "canceled",
                    }
                ]

                if not unfinished_for_reschedule:
                    st.info(
                        "This dispatch has no unfinished stops to reschedule."
                    )
                else:
                    reschedule_saved_labels = {}
                    reschedule_saved_by_id = {}

                    for stop in unfinished_for_reschedule:
                        job_id = stop.get("id") or stop.get("job_id")
                        if job_id is None:
                            continue
                        job_id = int(job_id)
                        reschedule_saved_by_id[job_id] = stop
                        customer_name = (
                            safe_text(stop.get("name"))
                            or safe_text(stop.get("customer_name"))
                            or f"Job #{job_id}"
                        )
                        treatment = (
                            safe_text(stop.get("treatment_name"))
                            or safe_text(stop.get("service_name"))
                            or safe_text(stop.get("service"))
                        )
                        scheduled = safe_text(stop.get("scheduled_date"))
                        parts = [customer_name]
                        if treatment:
                            parts.append(treatment)
                        if scheduled:
                            parts.append(f"Currently {scheduled}")
                        parts.append(
                            f"Dispatch #{int(selected_saved_dispatch_id)}"
                        )
                        parts.append(f"Job #{job_id}")
                        reschedule_saved_labels[job_id] = " — ".join(parts)

                    saved_job_to_reschedule = st.selectbox(
                        "Dispatch Stop",
                        options=list(reschedule_saved_labels),
                        format_func=lambda value: (
                            reschedule_saved_labels[value]
                        ),
                        key="reschedule_saved_job_id",
                    )

                    saved_stop = reschedule_saved_by_id[
                        int(saved_job_to_reschedule)
                    ]

                    try:
                        current_saved_date = pd.to_datetime(
                            saved_stop.get("scheduled_date"),
                            errors="coerce",
                        )
                        if pd.isna(current_saved_date):
                            current_saved_date = date.today()
                        else:
                            current_saved_date = current_saved_date.date()
                    except Exception:
                        current_saved_date = date.today()

                    new_saved_date = st.date_input(
                        "New Scheduled Date",
                        value=current_saved_date,
                        key="reschedule_saved_new_date",
                    )

                    st.caption(
                        "This removes the stop from the saved crew route, "
                        "keeps the same job and treatment link, and returns "
                        "it to the Dispatch queue for the new date."
                    )

                    if st.button(
                        "Postpone / Reschedule Stop",
                        type="primary",
                        use_container_width=True,
                        key="reschedule_saved_job_button",
                    ):
                        reschedule_dispatch_job(
                            int(saved_job_to_reschedule),
                            new_saved_date,
                            return_to_queue=True,
                            dispatch_id=int(
                                selected_saved_dispatch_id
                            ),
                        )
                        st.success(
                            "Stop returned to the queue for "
                            f"{new_saved_date:%B %d, %Y}."
                        )
                        _clear_saved_dispatch_management_state()
                        st.rerun()

            with management_tabs[3]:
                st.caption(
                    "Dissolve this saved route and return every "
                    "unfinished stop to the general Dispatch queue. "
                    "Completed stops stay completed."
                )

                if st.button(
                    "Return Entire Dispatch to Queue",
                    type="secondary",
                    use_container_width=True,
                    key="return_saved_dispatch_to_queue",
                ):
                    clear_saved_dispatch(
                        int(
                            selected_saved_dispatch_id
                        ),
                        requeue_unfinished=True,
                    )
                    st.success(
                        "Unfinished stops returned to the queue."
                    )
                    st.session_state[
                        "dispatch_preview_routes"
                    ] = []
                    _clear_saved_dispatch_management_state(
                        clear_dispatch_selection=True,
                    )
                    st.rerun()

            with management_tabs[4]:
                st.warning(
                    "Cancel Dispatch removes all unfinished stops "
                    "from Dispatch. They will NOT return to the queue. "
                    "Completed stops remain completed."
                )

                confirm_cancel = st.checkbox(
                    "Yes, permanently cancel the unfinished stops "
                    "in this dispatch.",
                    key="confirm_cancel_saved_dispatch",
                )

                if st.button(
                    "Cancel Dispatch",
                    type="primary",
                    use_container_width=True,
                    disabled=(
                        not confirm_cancel
                    ),
                    key="cancel_saved_dispatch",
                ):
                    cancelled_count = (
                        cancel_saved_dispatch(
                            int(
                                selected_saved_dispatch_id
                            )
                        )
                    )
                    st.success(
                        f"Dispatch cancelled. "
                        f"{cancelled_count} unfinished stop"
                        f"{'' if cancelled_count == 1 else 's'} "
                        "cancelled."
                    )
                    st.session_state[
                        "dispatch_preview_routes"
                    ] = []
                    _clear_saved_dispatch_management_state(
                        clear_dispatch_selection=True,
                    )
                    st.rerun()


        with st.expander(
            "Dispatch History",
            expanded=False,
        ):
            st.caption(
                "Older completed, cancelled, and rescheduled dispatches are retained here. "
                "Search by customer, crew, date, status, route, or dispatch number."
            )

            history_search = st.text_input(
                "Search Dispatch History",
                placeholder=(
                    "Customer, crew, date, status, route, or dispatch #"
                ),
                key="dispatch_history_search",
            )

            filtered_history = history_df.copy()

            if not filtered_history.empty:
                history_dates = pd.to_datetime(
                    filtered_history.get(
                        "completed_at",
                        filtered_history.get(
                            "dispatch_date"
                        ),
                    ),
                    errors="coerce",
                )

                valid_history_dates = (
                    history_dates.dropna()
                )

                if not valid_history_dates.empty:
                    min_history_date = (
                        valid_history_dates.min().date()
                    )
                    max_history_date = (
                        valid_history_dates.max().date()
                    )

                    history_date_range = st.date_input(
                        "History Date Range",
                        value=(
                            min_history_date,
                            max_history_date,
                        ),
                        key="dispatch_history_date_range",
                        help=(
                            "Choose any start and end dates. The default range "
                            "covers the history currently stored."
                        ),
                    )

                    if (
                        isinstance(
                            history_date_range,
                            (tuple, list),
                        )
                        and len(
                            history_date_range
                        ) == 2
                    ):
                        start_history_date = (
                            history_date_range[0]
                        )
                        end_history_date = (
                            history_date_range[1]
                        )

                        date_values = pd.to_datetime(
                            filtered_history.get(
                                "completed_at",
                                filtered_history.get(
                                    "dispatch_date"
                                ),
                            ),
                            errors="coerce",
                        )

                        filtered_history = (
                            filtered_history[
                                date_values.dt.date.between(
                                    start_history_date,
                                    end_history_date,
                                )
                            ].copy()
                        )

                search_text = (
                    safe_text(
                        history_search
                    )
                    .strip()
                    .lower()
                )

                if search_text:
                    matching_ids = []

                    for _, history_row in (
                        filtered_history.iterrows()
                    ):
                        dispatch_id = int(
                            history_row["id"]
                        )

                        searchable_parts = [
                            safe_text(
                                history_row.get(
                                    "dispatch_date"
                                )
                            ),
                            safe_text(
                                history_row.get(
                                    "crew_name"
                                )
                            ),
                            safe_text(
                                history_row.get(
                                    "route_number"
                                )
                            ),
                            safe_text(
                                history_row.get(
                                    "status"
                                )
                            ),
                            str(dispatch_id),
                            f"dispatch {dispatch_id}",
                        ]

                        row_haystack = " ".join(
                            searchable_parts
                        ).lower()

                        if search_text in row_haystack:
                            matching_ids.append(
                                dispatch_id
                            )
                            continue

                        manifest = (
                            get_saved_dispatch_manifest(
                                dispatch_id
                            )
                        )
                        rescheduled_manifest = (
                            get_dispatch_reschedule_history(
                                dispatch_id
                            )
                        )

                        customer_haystack = " ".join(
                            " ".join(
                                [
                                    safe_text(
                                        stop.get(
                                            "name"
                                        )
                                    ),
                                    safe_text(
                                        stop.get(
                                            "customer_name"
                                        )
                                    ),
                                    safe_text(
                                        stop.get(
                                            "address"
                                        )
                                    ),
                                ]
                            )
                            for stop in (
                                list(manifest)
                                + list(rescheduled_manifest)
                            )
                        ).lower()

                        if search_text in customer_haystack:
                            matching_ids.append(
                                dispatch_id
                            )

                    filtered_history = (
                        filtered_history[
                            filtered_history["id"]
                            .astype(int)
                            .isin(
                                matching_ids
                            )
                        ].copy()
                    )

                if filtered_history.empty:
                    st.info(
                        "No dispatch history matches those filters."
                    )
                else:
                    filtered_history = (
                        filtered_history.assign(
                            _sort_date=pd.to_datetime(
                                filtered_history.get(
                                    "completed_at",
                                    filtered_history.get(
                                        "dispatch_date"
                                    ),
                                ),
                                errors="coerce",
                            )
                        )
                        .sort_values(
                            "_sort_date",
                            ascending=False,
                        )
                        .drop(
                            columns=["_sort_date"]
                        )
                    )

                    st.dataframe(
                        filtered_history[
                            saved_columns
                        ],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "id": "Dispatch #",
                            "dispatch_date": "Dispatch Date",
                            "crew_name": "Crew",
                            "route_number": "Route",
                            "status": "Status",
                            "stop_count": "Stops",
                            "completed_count": "Completed",
                        },
                    )

                    visible_history_ids = {
                        int(value)
                        for value in filtered_history["id"].tolist()
                    }

                    rescheduled_stops = [
                        row
                        for row in get_dispatch_reschedule_history()
                        if int(row.get("dispatch_id") or 0)
                        in visible_history_ids
                    ]

                    if rescheduled_stops:
                        st.markdown("#### Rescheduled Stops")
                        st.caption(
                            "These are historical snapshots of stops removed "
                            "from saved dispatches. The live Job # continues "
                            "in the queue on its new scheduled date."
                        )

                        rescheduled_df = pd.DataFrame(
                            rescheduled_stops
                        )

                        rescheduled_columns = [
                            column
                            for column in [
                                "dispatch_id",
                                "job_id",
                                "customer_name",
                                "treatment_name",
                                "old_scheduled_date",
                                "new_scheduled_date",
                                "status",
                                "rescheduled_at",
                            ]
                            if column in rescheduled_df.columns
                        ]

                        st.dataframe(
                            rescheduled_df[
                                rescheduled_columns
                            ],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "dispatch_id": "Dispatch #",
                                "job_id": "Job #",
                                "customer_name": "Customer",
                                "treatment_name": "Treatment",
                                "old_scheduled_date": "Original Date",
                                "new_scheduled_date": "Rescheduled Date",
                                "status": "Status",
                                "rescheduled_at": "Rescheduled At",
                            },
                        )
            else:
                st.caption(
                    "No older dispatch history yet."
                )


    else:
        st.info(
            "No saved crew dispatches yet."
        )

    st.divider()

    st.subheader(
        "Daily Load Sheet"
    )

    from core.load_sheet import (
        build_daily_load_sheet,
        build_daily_load_sheet_html,
    )

    if st.session_state.pop(
        "reload_spray_defaults",
        False,
    ):
        for widget_key in (
            "dispatch_water_gpa",
            "dispatch_large_tank",
            "dispatch_small_tank",
            "dispatch_spot_tank",
        ):
            st.session_state.pop(
                widget_key,
                None,
            )

    saved_water_gpa = (
        load_float_setting(
            "water_gallons_per_acre",
            20.0,
        )
    )

    saved_large_tank = (
        load_float_setting(
            "large_tank_gallons",
            200.0,
        )
    )

    saved_small_tank = (
        load_float_setting(
            "small_tank_gallons",
            30.0,
        )
    )

    saved_spot_tank = (
        load_float_setting(
            "spot_tank_gallons",
            1.0,
        )
    )

    (
        load_col1,
        load_col2,
        load_col3,
        load_col4,
    ) = st.columns(
        4
    )

    load_gallons_per_acre = (
        load_col1.number_input(
            "Water Gallons Per Acre",
            min_value=0.1,
            value=saved_water_gpa,
            step=1.0,
            key="dispatch_water_gpa",
        )
    )

    large_tank_size = (
        load_col2.number_input(
            "Large Tank Gallons",
            min_value=1.0,
            value=saved_large_tank,
            step=5.0,
            key="dispatch_large_tank",
        )
    )

    small_tank_size = (
        load_col3.number_input(
            "Small Tank Gallons",
            min_value=1.0,
            value=saved_small_tank,
            step=1.0,
            key="dispatch_small_tank",
        )
    )

    spot_tank_size = (
        load_col4.number_input(
            "Spot Treatment Gallons",
            min_value=0.1,
            value=saved_spot_tank,
            step=0.25,
            key="dispatch_spot_tank",
        )
    )

    try:
        load_sheet = (
            build_daily_load_sheet(
                scheduled_date=date.today(),
                gallons_per_acre=(
                    load_gallons_per_acre
                ),
                tank_sizes=[
                    large_tank_size,
                    small_tank_size,
                ],
                spot_tank_size=(
                    spot_tank_size
                ),
            )
        )

    except Exception:
        st.error(
            "Daily load sheet could not be built."
        )
        st.exception(
            traceback.format_exc()
        )
        load_sheet = None

    if load_sheet:
        load_summary = (
            load_sheet[
                "summary"
            ]
        )

        l1, l2, l3 = (
            st.columns(
                3
            )
        )

        l1.metric(
            "Scheduled Stops",
            load_summary.get(
                "stops",
                0,
            ),
        )

        l2.metric(
            "Total Acres",
            load_summary.get(
                "acres",
                0,
            ),
        )

        l3.metric(
            "Total Water",
            f"{load_summary.get('water_gallons', 0)} gal",
        )

        for title, key in (
            (
                "Treatment Mix Totals",
                "mix_summary",
            ),
            (
                "Total Chemicals Needed",
                "chemical_totals",
            ),
            (
                "Tank Load Breakdown",
                "tank_plan",
            ),
        ):
            with st.expander(
                title,
                expanded=(
                    title
                    != "Tank Load Breakdown"
                ),
            ):
                table = (
                    load_sheet.get(
                        key
                    )
                )

                if (
                    table is None
                    or table.empty
                ):
                    st.info(
                        "No data available."
                    )
                else:
                    st.dataframe(
                        table,
                        use_container_width=True,
                        hide_index=True,
                    )

        try:
            load_sheet_html = (
                build_daily_load_sheet_html(
                    load_sheet=(
                        load_sheet
                    ),
                    scheduled_date=date.today(),
                    gallons_per_acre=(
                        load_gallons_per_acre
                    ),
                    tank_sizes=[
                        large_tank_size,
                        small_tank_size,
                    ],
                    spot_tank_size=(
                        spot_tank_size
                    ),
                )
            )
        except TypeError:
            load_sheet_html = (
                build_daily_load_sheet_html(
                    load_sheet=(
                        load_sheet
                    ),
                    scheduled_date=date.today(),
                    gallons_per_acre=(
                        load_gallons_per_acre
                    ),
                    tank_sizes=[
                        large_tank_size,
                        small_tank_size,
                    ],
                )
            )

        st.download_button(
            "Download Printable Load Sheet",
            data=(
                load_sheet_html
            ),
            file_name=(
                "daily_load_sheet_"
                f"{date.today().isoformat()}.html"
            ),
            mime="text/html",
            use_container_width=True,
        )


# ==========================================================
# SCHEDULING
# ==========================================================

with tab_schedule:
    st.header(
        "Scheduling"
    )

    st.caption(
        "Schedule treatment visits. Once a visit is queued, "
        "its scheduled date no longer prevents it from appearing in Dispatch."
    )

    notice = st.session_state.pop(
        "schedule_dispatch_notice",
        None,
    )

    if notice:
        st.success(
            f"Created {notice['jobs_created']} dispatch stop(s) "
            f"and linked {notice['events_linked']} treatment(s)."
        )

        if notice.get(
            "skipped"
        ):
            st.info(
                f"Skipped {notice['skipped']} treatment(s) "
                "already in dispatch."
            )

    schedule_date = (
        st.date_input(
            "Service Date",
            value=date.today(),
            key="schedule_service_date",
        )
    )

    from core.scheduling import (
        build_treatment_schedule_candidates,
        queue_treatment_events_for_date,
    )

    customer_search = (
        st.text_input(
            "Customer Search",
            value="",
            placeholder=(
                "Try John, Smith, Joh, or 123 Oak"
            ),
            key="schedule_customer_search",
        )
    )

    search_text = (
        customer_search.strip().lower()
    )

    search_terms = [
        term
        for term in search_text.split()
        if term
    ]

    candidates = (
        build_treatment_schedule_candidates(
            schedule_date,
            include_future=bool(
                search_terms
            ),
        )
    )

    def schedule_search_match(
        item
    ):
        searchable_text = " ".join(
            [
                safe_text(
                    item.get(
                        "name"
                    )
                ),
                safe_text(
                    item.get(
                        "address"
                    )
                ),
                safe_text(
                    item.get(
                        "customer_number"
                    )
                ),
                safe_text(
                    item.get(
                        "account_name"
                    )
                ),
            ]
        ).lower()

        return all(
            term in searchable_text
            for term in search_terms
        )

    displayed_candidates = (
        candidates
        if not search_terms
        else [
            item
            for item in candidates
            if schedule_search_match(
                item
            )
        ]
    )

    if search_terms:
        st.caption(
            f"Showing {len(displayed_candidates)} matching planned "
            f"treatment(s), including future treatments."
        )

    due_count = len(
        displayed_candidates
    )

    queued_count = sum(
        bool(
            item.get(
                "already_queued"
            )
        )
        for item in displayed_candidates
    )

    ready_count = (
        due_count
        - queued_count
    )

    s1, s2, s3 = (
        st.columns(
            3
        )
    )

    s1.metric(
        "Due by Date",
        due_count,
    )

    s2.metric(
        "Already Queued",
        queued_count,
    )

    s3.metric(
        "Ready to Schedule",
        ready_count,
    )

    if displayed_candidates:
        schedule_rows = (
            pd.DataFrame(
                displayed_candidates
            )
        )

        select_col, deselect_col = (
            st.columns(
                2
            )
        )

        if select_col.button(
            "Select All",
            use_container_width=True,
            key="schedule_select_all_button",
        ):
            st.session_state[
                "schedule_select_all"
            ] = True

            st.session_state[
                "schedule_editor_version"
            ] += 1

            st.rerun()

        if deselect_col.button(
            "Deselect All",
            use_container_width=True,
            key="schedule_deselect_all_button",
        ):
            st.session_state[
                "schedule_select_all"
            ] = False

            st.session_state[
                "schedule_editor_version"
            ] += 1

            st.rerun()

        default_selection = (
            ~schedule_rows[
                "already_queued"
            ]
            if st.session_state[
                "schedule_select_all"
            ]
            else False
        )

        schedule_rows.insert(
            0,
            "Schedule",
            default_selection,
        )

        schedule_rows[
            "due_date"
        ] = pd.to_datetime(
            schedule_rows[
                "due_date"
            ],
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

        edited_schedule = (
            st.data_editor(
                schedule_rows[
                    display_columns
                ],
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
                    f"{st.session_state['schedule_editor_version']}"
                ),
            )
        )

        selected_event_ids = (
            edited_schedule.loc[
                edited_schedule[
                    "Schedule"
                ]
                & ~edited_schedule[
                    "already_queued"
                ],
                "event_id",
            ]
            .astype(
                int
            )
            .tolist()
        )

        if st.button(
            (
                f"Add {len(selected_event_ids)} "
                "Treatment(s) to Dispatch"
            ),
            type="primary",
            use_container_width=True,
            disabled=(
                not selected_event_ids
            ),
            key="schedule_add_dispatch",
        ):
            result = (
                queue_treatment_events_for_date(
                    selected_event_ids,
                    schedule_date,
                )
            )

            st.session_state[
                "schedule_dispatch_notice"
            ] = result

            st.session_state[
                "schedule_select_all"
            ] = False

            st.session_state[
                "schedule_editor_version"
            ] += 1

            st.rerun()

    else:
        if candidates and search_terms:
            st.info(
                "No scheduling candidates match that customer search."
            )
        else:
            st.info(
                "No planned treatments are due by this date. "
                "Generate the seasonal schedule from Treatments first."
            )

    st.divider()

    st.subheader(
        "Crew Route Preview"
    )

    st.caption(
        "This preview uses the entire queued Dispatch pool, "
        "including jobs scheduled for other dates."
    )

    preview_crews = (
        get_crews(
            active_only=True
        )
    )

    if (
        preview_crews is None
        or preview_crews.empty
    ):
        st.info(
            "Add active crews in Settings before previewing multi-crew routes."
        )
    else:
        preview_crew_labels = {
            int(
                row[
                    "id"
                ]
            ): safe_text(
                row.get(
                    "crew_name"
                )
            )
            for _, row in preview_crews.iterrows()
        }

        preview_selected_ids = (
            st.multiselect(
                "Preview Crews",
                options=list(
                    preview_crew_labels
                ),
                default=list(
                    preview_crew_labels
                ),
                format_func=lambda value: (
                    preview_crew_labels[
                        value
                    ]
                ),
                key="schedule_preview_crews",
            )
        )

        if st.button(
            "Preview Routes for Queued Jobs",
            use_container_width=True,
            key="schedule_route_preview",
            disabled=(
                not preview_selected_ids
            ),
        ):
            try:
                selected = (
                    preview_crews[
                        preview_crews[
                            "id"
                        ]
                        .astype(
                            int
                        )
                        .isin(
                            preview_selected_ids
                        )
                    ]
                    .to_dict(
                        "records"
                    )
                )

                routes = (
                    build_multi_driver_routes(
                        crews=selected,
                    )
                )

                if routes:
                    for crew_route in routes:
                        st.markdown(
                            f"### {crew_route['crew']}"
                        )

                        crew_summary = (
                            crew_route.get(
                                "summary",
                                {},
                            )
                        )

                        preview_1, preview_2, preview_3, preview_4 = (
                            st.columns(
                                4
                            )
                        )

                        preview_1.metric(
                            "Stops",
                            int(
                                crew_summary.get(
                                    "stops",
                                    0,
                                )
                            ),
                        )

                        preview_2.metric(
                            "Distance",
                            f"{safe_float(crew_summary.get('distance_miles')):.1f} mi",
                        )

                        preview_3.metric(
                            "Drive Time",
                            f"{safe_float(crew_summary.get('drive_minutes')):.0f} min",
                        )

                        preview_4.metric(
                            "Total Time",
                            f"{safe_float(crew_summary.get('total_minutes')):.0f} min",
                        )

                        maps = (
                            crew_route.get(
                                "google_maps"
                            )
                            or crew_summary.get(
                                "google_maps"
                            )
                        )

                        if maps:
                            st.link_button(
                                f"Open {crew_route['crew']} Route in Google Maps",
                                maps,
                                use_container_width=True,
                            )

                        st.dataframe(
                            pd.DataFrame(
                                crew_route[
                                    "manifest"
                                ]
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
# TREATMENTS
# ==========================================================

with tab_treatments:
    from tabs.treatments import (
        render as render_treatments,
    )

    render_treatments()


# ==========================================================
# APPLICATIONS
# ==========================================================

with tab_applications:
    from tabs.applications import (
        render as render_applications,
    )

    render_applications(
        current_email=current_email
    )


# ==========================================================
# INVOICING
# ==========================================================

with tab_invoicing:
    from tabs.invoicing import (
        render as render_invoicing,
    )

    render_invoicing()


# ==========================================================
# ROUTING
# ==========================================================

with tab_routes:
    st.header(
        "Routing"
    )

    st.caption(
        "This view analyzes the current complete Dispatch-ready queue."
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
            "No optimized route is available."
        )

    summary = dispatch.get(
        "summary",
        {},
    )

    if summary:
        st.divider()

        r1, r2, r3, r4 = (
            st.columns(
                4
            )
        )

        r1.metric(
            "Stops",
            summary.get(
                "stops",
                0,
            ),
        )

        r2.metric(
            "Miles",
            f"{safe_float(summary.get('distance_miles')):.1f}",
        )

        r3.metric(
            "Drive Minutes",
            f"{safe_float(summary.get('drive_minutes')):.0f}",
        )

        r4.metric(
            "Total Minutes",
            f"{safe_float(summary.get('total_minutes')):.0f}",
        )

        maps = safe_text(
            summary.get(
                "google_maps"
            )
        )

        if maps:
            st.link_button(
                "Open in Google Maps",
                maps,
                use_container_width=True,
            )


# ==========================================================
# REPORTS
# ==========================================================

with tab_reports:
    from core.compliance_reports import (
        build_inspector_html,
        build_route_html,
        get_application_report,
    )

    st.header(
        "Reports"
    )

    (
        route_report_tab,
        inspector_report_tab,
    ) = st.tabs(
        [
            "Daily Route",
            "Licensing Inspector",
        ]
    )

    with route_report_tab:
        st.subheader(
            "Current Daily Route"
        )

        current_route = dispatch.get(
            "route",
            [],
        )

        route_summary_data = (
            dispatch.get(
                "summary",
                {},
            )
        )

        route_report_date = (
            st.date_input(
                "Route Date",
                value=date.today(),
                key="route_report_date",
            )
        )

        route_report_html = (
            build_route_html(
                current_route,
                route_summary_data,
                route_report_date,
            )
        )

        report_route_df = (
            dispatch.get(
                "dataframe",
                pd.DataFrame(),
            )
        )

        if report_route_df.empty:
            st.info(
                "No current route is available."
            )
        else:
            st.dataframe(
                report_route_df,
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

    with inspector_report_tab:
        st.subheader(
            "Pesticide Application Report"
        )

        today = date.today()

        default_start = (
            today.replace(
                day=1
            )
        )

        range_col1, range_col2 = (
            st.columns(
                2
            )
        )

        report_start = (
            range_col1.date_input(
                "Start Application Date",
                value=default_start,
                key="inspector_start_date",
            )
        )

        report_end = (
            range_col2.date_input(
                "End Application Date",
                value=today,
                key="inspector_end_date",
            )
        )

        if report_start > report_end:
            st.error(
                "Start date must be before the end date."
            )
        else:
            inspector_report = (
                get_application_report(
                    report_start,
                    report_end,
                )
            )

            if inspector_report.empty:
                st.info(
                    "No chemical applications were recorded during this period."
                )
            else:
                report_1, report_2 = (
                    st.columns(
                        2
                    )
                )

                report_1.metric(
                    "Applications",
                    inspector_report[
                        "Application ID"
                    ].nunique(),
                )

                report_2.metric(
                    "Chemical Records",
                    len(
                        inspector_report
                    ),
                )

                st.dataframe(
                    inspector_report,
                    use_container_width=True,
                    hide_index=True,
                )

            inspector_html = (
                build_inspector_html(
                    inspector_report,
                    report_start,
                    report_end,
                )
            )

            st.subheader(
                "Printable Report Preview"
            )

            components.html(
                inspector_html,
                height=750,
                scrolling=True,
            )

            csv_data = (
                inspector_report.to_csv(
                    index=False
                )
            )

            report_download_1, report_download_2 = (
                st.columns(
                    2
                )
            )

            report_download_1.download_button(
                "Download Printable Report",
                data=(
                    inspector_html
                ),
                file_name=(
                    "pesticide_application_report_"
                    f"{report_start}_{report_end}.html"
                ),
                mime="text/html",
                use_container_width=True,
            )

            report_download_2.download_button(
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
# IMPORT
# ==========================================================

with tab_import:
    render_import_data()


# ==========================================================
# SETTINGS
# ==========================================================

with tab_settings:
    st.header(
        "Settings"
    )

    st.subheader(
        "Database"
    )

    st.success(
        "Connected to persistent Supabase PostgreSQL storage."
    )

    st.caption(
        "CRM records are retained independently of Streamlit "
        "restarts, sign-outs, sleeps, and deployments."
    )

    st.divider()

    st.subheader(
        "Invoicing"
    )

    with st.form(
        "invoice_email_settings_form"
    ):
        global_auto_send_invoices = (
            st.checkbox(
                "Automatically send invoices when jobs are completed",
                value=load_bool_setting(
                    "auto_send_invoices",
                    False,
                ),
                help=(
                    "When ON, completed-job invoices are emailed "
                    "automatically unless that customer has opted out. "
                    "When OFF, invoices are still created as Drafts."
                ),
            )
        )

        save_invoice_email_settings = (
            st.form_submit_button(
                "Save Invoice Email Settings",
                type="primary",
                use_container_width=True,
            )
        )

        if save_invoice_email_settings:
            set_setting(
                "auto_send_invoices",
                (
                    "1"
                    if global_auto_send_invoices
                    else "0"
                ),
            )
            st.success(
                "Invoice email settings saved."
            )
            st.rerun()

    st.caption(
        "Individual customers can opt out under "
        "Customers → Edit Customer → Automatically Email Invoices."
    )

    st.divider()

    st.subheader(
        "Depot"
    )

    depot = get_depot()

    with st.form(
        "depot_form"
    ):
        depot_name = (
            st.text_input(
                "Depot Name",
                value=safe_text(
                    depot.get(
                        "name"
                    )
                ),
            )
        )

        depot_address = (
            st.text_input(
                "Depot Address",
                value=safe_text(
                    depot.get(
                        "address"
                    )
                ),
            )
        )

        depot_lat = (
            st.number_input(
                "Latitude",
                value=safe_float(
                    depot.get(
                        "lat"
                    ),
                    32.2737,
                ),
                format="%.6f",
            )
        )

        depot_lng = (
            st.number_input(
                "Longitude",
                value=safe_float(
                    depot.get(
                        "lng"
                    ),
                    -89.9865,
                ),
                format="%.6f",
            )
        )

        save_depot = (
            st.form_submit_button(
                "Save Depot Settings",
                type="primary",
                use_container_width=True,
            )
        )

        if save_depot:
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
        "Crews"
    )

    crew_df = get_crews(
        active_only=False
    )

    if (
        crew_df is not None
        and not crew_df.empty
    ):
        st.dataframe(
            crew_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": None,
                "crew_name": "Crew",
                "email": "Email",
                "phone": "Phone",
                "active": "Active",
                "notes": "Notes",
            },
        )

    crew_edit_tab, crew_add_tab = (
        st.tabs(
            [
                "Edit Crew",
                "Add Crew",
            ]
        )
    )

    with crew_edit_tab:
        if (
            crew_df is None
            or crew_df.empty
        ):
            st.info(
                "No crews have been created."
            )
        else:
            crew_labels = {
                int(
                    row[
                        "id"
                    ]
                ): safe_text(
                    row.get(
                        "crew_name"
                    )
                )
                for _, row
                in crew_df.iterrows()
            }

            edit_crew_id = (
                st.selectbox(
                    "Crew",
                    options=list(
                        crew_labels
                    ),
                    format_func=lambda value: (
                        crew_labels[
                            value
                        ]
                    ),
                    key="settings_edit_crew",
                )
            )

            selected_crew = (
                crew_df[
                    crew_df[
                        "id"
                    ]
                    .astype(
                        int
                    )
                    == int(
                        edit_crew_id
                    )
                ]
                .iloc[0]
            )

            with st.form(
                "edit_crew_form"
            ):
                edit_crew_name = (
                    st.text_input(
                        "Crew Name",
                        value=safe_text(
                            selected_crew.get(
                                "crew_name"
                            )
                        ),
                    )
                )

                edit_crew_email = (
                    st.text_input(
                        "Crew Email",
                        value=safe_text(
                            selected_crew.get(
                                "email"
                            )
                        ),
                    )
                )

                edit_crew_phone = (
                    st.text_input(
                        "Crew Phone",
                        value=safe_text(
                            selected_crew.get(
                                "phone"
                            )
                        ),
                    )
                )

                edit_crew_notes = (
                    st.text_area(
                        "Notes",
                        value=safe_text(
                            selected_crew.get(
                                "notes"
                            )
                        ),
                    )
                )

                edit_crew_active = (
                    st.checkbox(
                        "Active Crew",
                        value=bool(
                            selected_crew.get(
                                "active",
                                1,
                            )
                        ),
                    )
                )

                save_crew = (
                    st.form_submit_button(
                        "Save Crew",
                        type="primary",
                        use_container_width=True,
                    )
                )

                if save_crew:
                    update_crew(
                        int(
                            edit_crew_id
                        ),
                        crew_name=(
                            edit_crew_name.strip()
                        ),
                        email=(
                            edit_crew_email.strip()
                            or None
                        ),
                        phone=(
                            edit_crew_phone.strip()
                            or None
                        ),
                        notes=(
                            edit_crew_notes.strip()
                            or None
                        ),
                        active=(
                            edit_crew_active
                        ),
                    )

                    st.success(
                        "Crew updated."
                    )

                    st.rerun()

    with crew_add_tab:
        with st.form(
            "add_crew_form"
        ):
            new_crew_name = (
                st.text_input(
                    "Crew Name"
                )
            )

            new_crew_email = (
                st.text_input(
                    "Crew Email"
                )
            )

            new_crew_phone = (
                st.text_input(
                    "Crew Phone"
                )
            )

            new_crew_notes = (
                st.text_area(
                    "Notes"
                )
            )

            add_crew_button = (
                st.form_submit_button(
                    "Add Crew",
                    type="primary",
                    use_container_width=True,
                )
            )

            if add_crew_button:
                if not new_crew_name.strip():
                    st.error(
                        "Crew name is required."
                    )
                else:
                    try:
                        create_crew(
                            crew_name=(
                                new_crew_name.strip()
                            ),
                            email=(
                                new_crew_email.strip()
                                or None
                            ),
                            phone=(
                                new_crew_phone.strip()
                                or None
                            ),
                            notes=(
                                new_crew_notes.strip()
                                or None
                            ),
                            active=True,
                        )
                    except Exception as exc:
                        st.error(
                            f"Crew could not be added: {exc}"
                        )
                    else:
                        st.success(
                            "Crew added."
                        )
                        st.rerun()

    st.divider()

    st.subheader(
        "Spray and Tank Defaults"
    )

    with st.form(
        "spray_defaults_form"
    ):
        settings_col1, settings_col2 = (
            st.columns(
                2
            )
        )

        default_water_gpa = (
            settings_col1.number_input(
                "Default Water Gallons Per Acre",
                min_value=0.1,
                value=load_float_setting(
                    "water_gallons_per_acre",
                    20.0,
                ),
                step=1.0,
            )
        )

        default_large_tank = (
            settings_col2.number_input(
                "Large Broadcast Tank Gallons",
                min_value=1.0,
                value=load_float_setting(
                    "large_tank_gallons",
                    200.0,
                ),
                step=5.0,
            )
        )

        settings_col3, settings_col4 = (
            st.columns(
                2
            )
        )

        default_small_tank = (
            settings_col3.number_input(
                "Small Broadcast Tank Gallons",
                min_value=1.0,
                value=load_float_setting(
                    "small_tank_gallons",
                    30.0,
                ),
                step=1.0,
            )
        )

        default_spot_tank = (
            settings_col4.number_input(
                "Spot Treatment Batch Gallons",
                min_value=0.1,
                value=load_float_setting(
                    "spot_tank_gallons",
                    1.0,
                ),
                step=0.25,
            )
        )

        default_max_stops = (
            st.number_input(
                "Default Maximum Stops per Crew Route",
                min_value=1,
                max_value=50,
                value=int(
                    load_float_setting(
                        "max_stops_per_route",
                        10,
                    )
                ),
                step=1,
            )
        )

        save_spray_defaults = (
            st.form_submit_button(
                "Save Operational Defaults",
                type="primary",
                use_container_width=True,
            )
        )

        if save_spray_defaults:
            set_setting(
                "water_gallons_per_acre",
                str(
                    float(
                        default_water_gpa
                    )
                ),
            )

            set_setting(
                "large_tank_gallons",
                str(
                    float(
                        default_large_tank
                    )
                ),
            )

            set_setting(
                "small_tank_gallons",
                str(
                    float(
                        default_small_tank
                    )
                ),
            )

            set_setting(
                "spot_tank_gallons",
                str(
                    float(
                        default_spot_tank
                    )
                ),
            )

            set_setting(
                "max_stops_per_route",
                str(
                    int(
                        default_max_stops
                    )
                ),
            )

            st.session_state[
                "reload_spray_defaults"
            ] = True

            st.success(
                "Operational defaults saved."
            )

            st.rerun()

    st.caption(
        "Liquid Broadcast treatments use lawn acreage and water gallons "
        "per acre. Spot treatments use a saved liquid batch. Granular "
        "Broadcast treatments use acreage without water."
    )
