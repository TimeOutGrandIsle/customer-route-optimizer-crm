"""
ui/field_view.py

Time Out Lawncare CRM
Crew / Field Mobile View
Version 3.0

Purpose:
- Give a crew one simple mobile-friendly dispatch list.
- Show only the crew's assigned dispatch when a dispatch token is supplied.
- Provide one-tap Google Maps directions from the phone's current location.
- Record Arrived and Completed timestamps immediately in the shared database.
- Automatically identify the next unfinished stop.
- Keep the office Dispatch screen synchronized with field activity.

The public entry point is:
    render()

This matches the existing app.py Field Mode integration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

from data.database import (
    get_dispatch,
    get_dispatch_by_token,
    get_dispatch_jobs_for_manifest,
    get_dispatches,
    mark_job_arrived,
    mark_job_completed,
)

from services.routing import build_navigation_url

from ui.dispatch import (
    get_driver_route_view,
    get_saved_dispatch_manifest,
    next_stop,
    remaining_stops,
)


# ==========================================================
# CONSTANTS
# ==========================================================

FIELD_PAGE_TITLE = "Time Out Lawncare — Crew Dispatch"

ACTIVE_STATUSES = {
    "queued",
    "dispatched",
    "in_progress",
}

COMPLETED_STATUSES = {
    "completed",
}

CANCELLED_STATUSES = {
    "cancelled",
    "canceled",
}


# ==========================================================
# BASIC HELPERS
# ==========================================================

def _text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()


def _status(value: Any) -> str:
    return _text(value).lower()


def _job_id(stop: Mapping[str, Any]) -> Optional[int]:
    for key in (
        "job_id",
        "dispatch_job_id",
        "id",
    ):
        value = stop.get(key)

        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except Exception:
            pass

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return None


def _stop_number(
    stop: Mapping[str, Any],
    fallback: int,
) -> int:
    value = stop.get(
        "stop_number",
        stop.get(
            "stop",
            fallback,
        ),
    )

    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _customer_name(stop: Mapping[str, Any]) -> str:
    return (
        _text(
            stop.get(
                "name"
            )
        )
        or _text(
            stop.get(
                "customer_name"
            )
        )
        or _text(
            stop.get(
                "customer"
            )
        )
        or "Customer"
    )


def _service(stop: Mapping[str, Any]) -> str:
    return (
        _text(
            stop.get(
                "service"
            )
        )
        or _text(
            stop.get(
                "treatment_name"
            )
        )
        or _text(
            stop.get(
                "treatment"
            )
        )
        or "Service"
    )


def _address(stop: Mapping[str, Any]) -> str:
    explicit = _text(
        stop.get(
            "address"
        )
    )

    if explicit:
        return explicit

    street = _text(
        stop.get(
            "street_address"
        )
    )
    city = _text(
        stop.get(
            "city"
        )
    )
    state = _text(
        stop.get(
            "state"
        )
    )
    zip_code = _text(
        stop.get(
            "zip"
        )
    )

    locality = ", ".join(
        part
        for part
        in (
            city,
            state,
        )
        if part
    )

    if zip_code:
        locality = (
            f"{locality} {zip_code}"
        ).strip()

    return ", ".join(
        part
        for part
        in (
            street,
            locality,
        )
        if part
    )


def _notes(stop: Mapping[str, Any]) -> str:
    parts: List[str] = []

    special = _text(
        stop.get(
            "special_instructions"
        )
    )

    notes = _text(
        stop.get(
            "notes"
        )
    )

    if special:
        parts.append(
            special
        )

    if notes and notes not in parts:
        parts.append(
            notes
        )

    return "\n\n".join(
        parts
    )


def _navigation_url(
    stop: Mapping[str, Any],
) -> str:
    existing = _text(
        stop.get(
            "navigation_url"
        )
    )

    if existing:
        return existing

    return build_navigation_url(
        stop
    )


# ==========================================================
# QUERY PARAMETER HELPERS
# ==========================================================

def get_dispatch_token_from_url() -> str:
    """
    Read ?dispatch=<token> from the current Streamlit URL.
    """
    try:
        value = st.query_params.get(
            "dispatch",
            "",
        )
    except Exception:
        return ""

    if isinstance(
        value,
        list,
    ):
        value = (
            value[0]
            if value
            else ""
        )

    return _text(
        value
    )


def set_dispatch_token_in_url(
    token: str,
) -> None:
    """
    Update the current Streamlit URL with the selected dispatch token.
    """
    if not token:
        return

    try:
        st.query_params[
            "dispatch"
        ] = token
    except Exception:
        pass


def clear_dispatch_token_from_url() -> None:
    try:
        if (
            "dispatch"
            in st.query_params
        ):
            del st.query_params[
                "dispatch"
            ]
    except Exception:
        pass


# ==========================================================
# DISPATCH LOADERS
# ==========================================================

def load_dispatch_by_token(
    token: str,
) -> Optional[Dict[str, Any]]:
    """
    Load one persistent crew dispatch by private dispatch token.
    """
    token = _text(
        token
    )

    if not token:
        return None

    try:
        dispatch = (
            get_dispatch_by_token(
                token
            )
        )
    except Exception:
        return None

    if not dispatch:
        return None

    return dict(
        dispatch
    )


def load_dispatch_manifest(
    dispatch_id: int,
) -> List[Dict[str, Any]]:
    """
    Load the persisted stop list for one dispatch.
    """
    try:
        df = (
            get_dispatch_jobs_for_manifest(
                int(
                    dispatch_id
                )
            )
        )
    except Exception:
        return []

    if (
        df is None
        or df.empty
    ):
        return []

    records = (
        df.to_dict(
            "records"
        )
    )

    for index, stop in enumerate(
        records,
        start=1,
    ):
        stop[
            "stop_number"
        ] = _stop_number(
            stop,
            index,
        )

        stop[
            "navigation_url"
        ] = _navigation_url(
            stop
        )

    return sorted(
        records,
        key=lambda stop: (
            _stop_number(
                stop,
                9999,
            )
        ),
    )


def active_dispatches() -> pd.DataFrame:
    """
    Load persistent dispatches available to authenticated Field Mode users.

    A crew-specific token remains the preferred access method. This list is a
    compatibility/fallback selector for office testing and authorized field
    accounts.
    """
    try:
        df = get_dispatches()
    except Exception:
        return pd.DataFrame()

    if (
        df is None
        or df.empty
    ):
        return pd.DataFrame()

    result = df.copy()

    if (
        "status"
        in result.columns
    ):
        statuses = (
            result[
                "status"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        result = result[
            ~statuses.isin(
                {
                    "cancelled",
                    "canceled",
                }
            )
        ].copy()

    return result


# ==========================================================
# FALLBACK LIVE FIELD VIEW
# ==========================================================

def load_live_route() -> List[Dict[str, Any]]:
    """
    Backward-compatible fallback when no saved dispatch/token exists.

    This preserves the old Field Mode behavior while the office side is
    transitioning to persistent multi-crew dispatches.
    """
    try:
        route = (
            get_driver_route_view()
        )
    except Exception:
        route = []

    return list(
        route
        or []
    )


# ==========================================================
# FIELD ACTIONS
# ==========================================================

def mark_arrived(
    job_id: int,
) -> None:
    """
    Record crew arrival for a stop.
    """
    mark_job_arrived(
        int(
            job_id
        )
    )


def mark_completed(
    job_id: int,
) -> None:
    """
    Record service completion for a stop.
    """
    mark_job_completed(
        int(
            job_id
        )
    )


# ==========================================================
# PRESENTATION HELPERS
# ==========================================================

def _status_label(
    stop: Mapping[str, Any],
) -> str:
    status = _status(
        stop.get(
            "status"
        )
    )

    if status == "completed":
        return "✅ Completed"

    if status == "in_progress":
        return "📍 On Site"

    if status == "dispatched":
        return "🚚 Dispatched"

    if status == "queued":
        return "⏳ Ready"

    if status in CANCELLED_STATUSES:
        return "🚫 Cancelled"

    return (
        _text(
            stop.get(
                "status"
            )
        )
        or "Ready"
    )


def _display_time(
    value: Any,
) -> str:
    text = _text(
        value
    )

    if not text:
        return ""

    try:
        parsed = pd.to_datetime(
            text
        )

        return parsed.strftime(
            "%I:%M %p"
        ).lstrip(
            "0"
        )
    except Exception:
        return text


def route_progress(
    route: List[Dict[str, Any]],
) -> Dict[str, int]:
    total = len(
        route
    )

    completed = sum(
        1
        for stop in route
        if _status(
            stop.get(
                "status"
            )
        )
        == "completed"
    )

    in_progress = sum(
        1
        for stop in route
        if _status(
            stop.get(
                "status"
            )
        )
        == "in_progress"
    )

    remaining = max(
        0,
        total - completed,
    )

    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "remaining": remaining,
    }


def render_progress(
    route: List[Dict[str, Any]],
) -> None:
    progress = route_progress(
        route
    )

    c1, c2, c3 = st.columns(
        3
    )

    with c1:
        st.metric(
            "Stops",
            progress[
                "total"
            ],
        )

    with c2:
        st.metric(
            "Completed",
            progress[
                "completed"
            ],
        )

    with c3:
        st.metric(
            "Remaining",
            progress[
                "remaining"
            ],
        )

    if progress[
        "total"
    ] > 0:
        fraction = (
            progress[
                "completed"
            ]
            / progress[
                "total"
            ]
        )
    else:
        fraction = 0.0

    st.progress(
        min(
            1.0,
            max(
                0.0,
                fraction,
            ),
        )
    )


def render_next_stop_card(
    route: List[Dict[str, Any]],
) -> None:
    stop = next_stop(
        route
    )

    if not stop:
        st.success(
            "🎉 All stops are complete."
        )
        return

    stop_number = _stop_number(
        stop,
        1,
    )

    customer = (
        _customer_name(
            stop
        )
    )

    service = _service(
        stop
    )

    address = _address(
        stop
    )

    st.subheader(
        f"Next Stop #{stop_number}"
    )

    st.markdown(
        f"### {customer}"
    )

    account_name = _text(
        stop.get(
            "account_name"
        )
    )

    customer_type = _text(
        stop.get(
            "customer_type"
        )
    )

    if account_name:
        st.caption(
            account_name
        )

    if customer_type:
        st.caption(
            customer_type
        )

    if address:
        st.write(
            f"📍 {address}"
        )

    st.write(
        f"**Service:** {service}"
    )

    instructions = _notes(
        stop
    )

    if instructions:
        st.info(
            instructions
        )

    nav_url = _navigation_url(
        stop
    )

    if nav_url:
        st.link_button(
            "🧭 Navigate to Next Stop",
            nav_url,
            type="primary",
            use_container_width=True,
        )


def render_stop_card(
    stop: Dict[str, Any],
    fallback_stop_number: int,
    *,
    expanded: bool = False,
) -> None:
    """
    Render one mobile-friendly stop with workflow controls.
    """
    stop_number = (
        _stop_number(
            stop,
            fallback_stop_number,
        )
    )

    customer = (
        _customer_name(
            stop
        )
    )

    status = _status(
        stop.get(
            "status"
        )
    )

    header = (
        f"#{stop_number} — "
        f"{customer} — "
        f"{_status_label(stop)}"
    )

    with st.expander(
        header,
        expanded=expanded,
    ):
        account_name = _text(
            stop.get(
                "account_name"
            )
        )

        customer_type = _text(
            stop.get(
                "customer_type"
            )
        )

        if account_name:
            st.markdown(
                f"**Account:** {account_name}"
            )

        if customer_type:
            st.caption(
                customer_type
            )

        address = _address(
            stop
        )

        if address:
            st.write(
                f"📍 {address}"
            )

        service = _service(
            stop
        )

        st.write(
            f"**Service:** {service}"
        )

        scheduled = _text(
            stop.get(
                "scheduled_date"
            )
        )

        if scheduled:
            st.write(
                f"**Scheduled:** {scheduled}"
            )

        instructions = _notes(
            stop
        )

        if instructions:
            st.info(
                instructions
            )

        arrived = _display_time(
            stop.get(
                "arrived_time"
            )
        )

        completed = _display_time(
            stop.get(
                "completed_time"
            )
        )

        if arrived:
            st.caption(
                f"Arrived: {arrived}"
            )

        if completed:
            st.caption(
                f"Completed: {completed}"
            )

        nav_url = _navigation_url(
            stop
        )

        job_id = _job_id(
            stop
        )

        nav_col, action_col = (
            st.columns(
                2
            )
        )

        with nav_col:
            if nav_url:
                st.link_button(
                    "🧭 Navigate",
                    nav_url,
                    use_container_width=True,
                )
            else:
                st.button(
                    "🧭 Navigate",
                    disabled=True,
                    key=(
                        f"no_nav_"
                        f"{job_id}_"
                        f"{stop_number}"
                    ),
                    use_container_width=True,
                )

        with action_col:
            if status in COMPLETED_STATUSES:
                st.button(
                    "✅ Completed",
                    disabled=True,
                    key=(
                        f"done_"
                        f"{job_id}_"
                        f"{stop_number}"
                    ),
                    use_container_width=True,
                )

            elif status == "in_progress":
                if st.button(
                    "✅ Complete",
                    type="primary",
                    key=(
                        f"complete_"
                        f"{job_id}_"
                        f"{stop_number}"
                    ),
                    use_container_width=True,
                ):
                    if job_id is None:
                        st.error(
                            "This stop has no dispatch job ID."
                        )
                    else:
                        try:
                            mark_completed(
                                job_id
                            )
                            st.success(
                                f"{customer} completed."
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(
                                "Unable to complete this stop."
                            )
                            st.exception(
                                exc
                            )

            elif status in CANCELLED_STATUSES:
                st.button(
                    "🚫 Cancelled",
                    disabled=True,
                    key=(
                        f"cancelled_"
                        f"{job_id}_"
                        f"{stop_number}"
                    ),
                    use_container_width=True,
                )

            else:
                if st.button(
                    "📍 Arrived",
                    type="primary",
                    key=(
                        f"arrived_"
                        f"{job_id}_"
                        f"{stop_number}"
                    ),
                    use_container_width=True,
                ):
                    if job_id is None:
                        st.error(
                            "This stop has no dispatch job ID."
                        )
                    else:
                        try:
                            mark_arrived(
                                job_id
                            )
                            st.success(
                                f"Arrival recorded for {customer}."
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(
                                "Unable to record arrival."
                            )
                            st.exception(
                                exc
                            )


def render_route_list(
    route: List[Dict[str, Any]],
) -> None:
    """
    Render active stops first and completed stops in a separate section.
    """
    if not route:
        st.info(
            "No stops are assigned to this dispatch."
        )
        return

    active: List[
        Dict[str, Any]
    ] = []

    completed: List[
        Dict[str, Any]
    ] = []

    cancelled: List[
        Dict[str, Any]
    ] = []

    for stop in route:
        status = _status(
            stop.get(
                "status"
            )
        )

        if status in COMPLETED_STATUSES:
            completed.append(
                stop
            )
        elif status in CANCELLED_STATUSES:
            cancelled.append(
                stop
            )
        else:
            active.append(
                stop
            )

    if active:
        st.subheader(
            "Route Stops"
        )

        next_item = next_stop(
            route
        )

        next_id = (
            _job_id(
                next_item
            )
            if next_item
            else None
        )

        for index, stop in enumerate(
            active,
            start=1,
        ):
            render_stop_card(
                stop,
                index,
                expanded=(
                    next_id
                    is not None
                    and _job_id(
                        stop
                    )
                    == next_id
                ),
            )

    if completed:
        st.divider()
        st.subheader(
            f"Completed ({len(completed)})"
        )

        for index, stop in enumerate(
            completed,
            start=1,
        ):
            render_stop_card(
                stop,
                index,
                expanded=False,
            )

    if cancelled:
        st.divider()
        st.subheader(
            f"Cancelled ({len(cancelled)})"
        )

        for index, stop in enumerate(
            cancelled,
            start=1,
        ):
            render_stop_card(
                stop,
                index,
                expanded=False,
            )


# ==========================================================
# DISPATCH SELECTOR FALLBACK
# ==========================================================

def render_dispatch_selector() -> Optional[int]:
    """
    Allow authorized Field Mode users to pick a saved dispatch when no token
    was supplied.

    This is especially useful during setup/testing. Once email/text dispatch
    links are in use, crews should normally enter through their tokenized link.
    """
    df = active_dispatches()

    if df.empty:
        return None

    display = df.copy()

    if (
        "crew_name"
        not in display.columns
    ):
        display[
            "crew_name"
        ] = ""

    if (
        "dispatch_date"
        not in display.columns
    ):
        display[
            "dispatch_date"
        ] = ""

    if (
        "route_number"
        not in display.columns
    ):
        display[
            "route_number"
        ] = ""

    display[
        "_label"
    ] = display.apply(
        lambda row: (
            f"{_text(row.get('dispatch_date'))}"
            f" — "
            f"{_text(row.get('crew_name')) or 'Unassigned Crew'}"
            f" — Route "
            f"{_text(row.get('route_number')) or '?'}"
        ),
        axis=1,
    )

    options = (
        display[
            "_label"
        ].tolist()
    )

    selected = st.selectbox(
        "Select Crew Dispatch",
        options=options,
        key="field_dispatch_selector",
    )

    row = display[
        display[
            "_label"
        ]
        == selected
    ]

    if row.empty:
        return None

    dispatch_id = row.iloc[
        0
    ].get(
        "id"
    )

    try:
        return int(
            dispatch_id
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


# ==========================================================
# PAGE HEADER
# ==========================================================

def render_dispatch_header(
    dispatch: Optional[
        Mapping[str, Any]
    ],
    route: List[Dict[str, Any]],
) -> None:
    st.title(
        "🌱 Time Out Lawncare"
    )

    st.subheader(
        "Crew Dispatch"
    )

    if dispatch:
        crew_name = (
            _text(
                dispatch.get(
                    "crew_name"
                )
            )
            or "Crew"
        )

        dispatch_date = _text(
            dispatch.get(
                "dispatch_date"
            )
        )

        route_number = _text(
            dispatch.get(
                "route_number"
            )
        )

        st.markdown(
            f"### {crew_name}"
        )

        details: List[str] = []

        if dispatch_date:
            details.append(
                dispatch_date
            )

        if route_number:
            details.append(
                f"Route {route_number}"
            )

        if details:
            st.caption(
                " • ".join(
                    details
                )
            )

    render_progress(
        route
    )


# ==========================================================
# MAIN ENTRY POINT
# ==========================================================

def render() -> None:
    """
    Render the Field Mode page.

    Entry scenarios:

    1. ?dispatch=<private token>
       -> load only that crew's saved manifest.

    2. No token, authenticated field/office user
       -> offer saved-dispatch selector.

    3. No saved dispatches yet
       -> fall back to the existing live route view so Field Mode remains
          useful during migration.
    """
    st.markdown(
        """
        <style>
        .stButton > button,
        .stLinkButton > a {
            min-height: 3rem;
            font-size: 1rem;
        }

        div[data-testid="stExpander"] details summary p {
            font-size: 1rem;
            font-weight: 600;
        }

        @media (max-width: 768px) {
            .block-container {
                padding-top: 1rem;
                padding-left: 0.8rem;
                padding-right: 0.8rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    token = (
        get_dispatch_token_from_url()
    )

    dispatch: Optional[
        Dict[str, Any]
    ] = None

    route: List[
        Dict[str, Any]
    ] = []

    if token:
        dispatch = (
            load_dispatch_by_token(
                token
            )
        )

        if not dispatch:
            st.error(
                "This dispatch link is invalid or no longer available."
            )

            if st.button(
                "Open Field Mode",
                use_container_width=True,
            ):
                clear_dispatch_token_from_url()
                st.rerun()

            return

        dispatch_id = (
            dispatch.get(
                "id"
            )
        )

        if dispatch_id is not None:
            route = load_dispatch_manifest(
                int(
                    dispatch_id
                )
            )

    else:
        selected_dispatch_id = (
            render_dispatch_selector()
        )

        if selected_dispatch_id is not None:
            try:
                dispatch = get_dispatch(
                    int(
                        selected_dispatch_id
                    )
                )
            except Exception:
                dispatch = None

            route = load_dispatch_manifest(
                int(
                    selected_dispatch_id
                )
            )

        else:
            route = load_live_route()

    render_dispatch_header(
        dispatch,
        route,
    )

    if not route:
        st.info(
            "No active route is available."
        )
        return

    st.divider()

    render_next_stop_card(
        route
    )

    st.divider()

    render_route_list(
        route
    )

    st.divider()

    remaining = remaining_stops(
        route
    )

    if remaining:
        st.caption(
            f"{len(remaining)} stop"
            f"{'' if len(remaining) == 1 else 's'} remaining."
        )
    else:
        st.success(
            "Dispatch complete."
        )

    if st.button(
        "🔄 Refresh Dispatch",
        use_container_width=True,
        key="field_refresh_dispatch",
    ):
        st.rerun()


__all__ = [
    "active_dispatches",
    "clear_dispatch_token_from_url",
    "get_dispatch_token_from_url",
    "load_dispatch_by_token",
    "load_dispatch_manifest",
    "load_live_route",
    "mark_arrived",
    "mark_completed",
    "render",
    "render_dispatch_header",
    "render_dispatch_selector",
    "render_next_stop_card",
    "render_progress",
    "render_route_list",
    "render_stop_card",
    "route_progress",
    "set_dispatch_token_in_url",
]
