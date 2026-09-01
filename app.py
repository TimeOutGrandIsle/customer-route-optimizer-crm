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

import traceback
from datetime import date, datetime
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
    create_multi_crew_dispatch,
    dispatch_dashboard,
    get_saved_dispatches,
    mark_job_in_progress,
)


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

header_1, header_2, header_3, header_4 = (
    st.columns(
        4
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
    "Completed",
    stats.get(
        "completed_jobs",
        0,
    ),
)

header_4.metric(
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

    dash_1, dash_2, dash_3, dash_4 = (
        st.columns(
            4
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
        "Dispatched",
        dashboard_stats.get(
            "dispatched",
            0,
        ),
    )

    dash_3.metric(
        "In Progress",
        dashboard_stats.get(
            "in_progress",
            0,
        ),
    )

    dash_4.metric(
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
        "Current Route Summary"
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

            current_standard_schedule = (
                selected_customer.get(
                    "standard_schedule",
                    1,
                )
            )

            if pd.isna(
                current_standard_schedule
            ):
                current_standard_schedule = 1

            current_standard_schedule = bool(
                int(
                    current_standard_schedule
                )
            )

            # Older/newly-created customers may have only the combined
            # `address` field populated. Build edit-form defaults from that
            # combined address when the structured address columns are blank.
            edit_street_address = safe_text(
                selected_customer.get(
                    "street_address"
                )
            )
            edit_city = safe_text(
                selected_customer.get(
                    "city"
                )
            )
            edit_state = safe_text(
                selected_customer.get(
                    "state"
                )
            )
            edit_zip = safe_text(
                selected_customer.get(
                    "zip"
                )
            )

            full_saved_address = safe_text(
                selected_customer.get(
                    "address"
                )
            )

            if (
                full_saved_address
                and not (
                    edit_street_address
                    or edit_city
                    or edit_state
                    or edit_zip
                )
            ):
                address_parts = [
                    part.strip()
                    for part in full_saved_address.split(
                        ","
                    )
                    if part.strip()
                ]

                if len(address_parts) >= 3:
                    edit_street_address = (
                        address_parts[0]
                    )
                    edit_city = (
                        address_parts[1]
                    )

                    state_zip_part = (
                        " ".join(
                            address_parts[2:]
                        ).strip()
                    )
                    state_zip_tokens = (
                        state_zip_part.split()
                    )

                    if state_zip_tokens:
                        edit_state = (
                            state_zip_tokens[0]
                        )

                    if len(
                        state_zip_tokens
                    ) > 1:
                        edit_zip = (
                            " ".join(
                                state_zip_tokens[1:]
                            )
                        )

                elif len(address_parts) == 2:
                    edit_street_address = (
                        address_parts[0]
                    )
                    edit_city = (
                        address_parts[1]
                    )

                else:
                    edit_street_address = (
                        full_saved_address
                    )

            with st.form(
                f"edit_customer_form_{int(edit_customer_id)}"
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

                street_address = (
                    st.text_input(
                        "Street Address",
                        value=edit_street_address,
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
                        value=edit_city,
                    )
                )

                state = (
                    state_col.text_input(
                        "State",
                        value=edit_state,
                    )
                )

                zipcode = (
                    zip_col.text_input(
                        "ZIP",
                        value=edit_zip,
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

                status_col, schedule_col = (
                    st.columns(
                        2
                    )
                )

                active = (
                    status_col.checkbox(
                        "Active Customer",
                        value=bool(
                            selected_customer.get(
                                "active",
                                1,
                            )
                        ),
                        help=(
                            "Inactive customers do not receive new "
                            "Standard Schedule events."
                        ),
                    )
                )

                standard_schedule = (
                    schedule_col.checkbox(
                        "Standard Schedule",
                        value=(
                            current_standard_schedule
                        ),
                        help=(
                            "When enabled, the CRM automatically creates "
                            "future Standard Schedule treatments for this "
                            "active customer. Past treatments are not "
                            "backfilled."
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
                                standard_schedule=int(
                                    standard_schedule
                                ),
                            )

                        except Exception as exc:
                            st.error(
                                "Customer could not be updated: "
                                f"{exc}"
                            )
                        else:
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

            new_standard_schedule = (
                st.checkbox(
                    "Standard Schedule",
                    value=True,
                    help=(
                        "Recommended for regular customers. The CRM will "
                        "create only Standard Schedule treatments occurring "
                        "after today; earlier treatments are not backfilled."
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
                    create_customer(
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
                        standard_schedule=(
                            new_standard_schedule
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

    saved_dispatches = (
        get_saved_dispatches()
    )

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
            if column
            in saved_df.columns
        ]

        st.dataframe(
            saved_df[
                saved_columns
            ],
            use_container_width=True,
            hide_index=True,
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
        candidates
    )

    queued_count = sum(
        bool(
            item.get(
                "already_queued"
            )
        )
        for item in candidates
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
        "Automatic Invoicing"
    )

    auto_send_value = str(
        get_setting(
            "auto_send_invoices",
            "false",
        )
        or "false"
    ).strip().lower()

    auto_send_enabled = (
        auto_send_value
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )

    new_auto_send_enabled = (
        st.toggle(
            "Automatically send invoices when jobs are completed",
            value=auto_send_enabled,
            help=(
                "When enabled, completing a dispatch stop creates the "
                "invoice and emails it automatically. If the customer has "
                "no email address or the invoice amount needs review, the "
                "invoice remains Draft and is not sent."
            ),
            key="settings_auto_send_invoices",
        )
    )

    if new_auto_send_enabled != auto_send_enabled:
        set_setting(
            "auto_send_invoices",
            "true" if new_auto_send_enabled else "false",
        )
        st.success(
            "Automatic invoice sending is now "
            + ("ON." if new_auto_send_enabled else "OFF.")
        )

    st.caption(
        "Invoice creation still occurs when a stop is completed. "
        "This switch controls whether eligible invoices are emailed "
        "automatically."
    )

    st.divider()

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
