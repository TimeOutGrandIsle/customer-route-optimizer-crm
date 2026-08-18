from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core.treatment_manager import (
    add_customer_treatment,
    calculate_mixture,
    complete_treatment_event,
    generate_standard_events,
    get_treatment_definitions,
    get_treatment_events,
    get_treatment_products,
    replace_treatment_products,
    reschedule_treatment_event,
    save_product_definition,
    save_treatment_definition,
    shift_pending_treatments,
)
from data.database import (
    get_customers,
    get_products,
    get_setting,
)


# ==========================================================
# HELPERS
# ==========================================================

APPLICATION_METHOD_LABELS = {
    "broadcast": "Liquid Broadcast",
    "spot": "Spot Treatment",
    "granular": "Granular Broadcast",
}


def _label_lookup(
    df: pd.DataFrame,
    label_column: str,
) -> dict[int, str]:
    if df is None or df.empty:
        return {}

    return {
        int(row["id"]): str(row[label_column])
        for _, row in df.iterrows()
    }


def _safe_text(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    return str(value)


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _method_label(
    method: Any,
) -> str:
    key = _safe_text(
        method,
        "broadcast",
    ).strip().lower()

    return APPLICATION_METHOD_LABELS.get(
        key,
        "Liquid Broadcast",
    )


def _filtered_definitions(
    definitions: pd.DataFrame,
    search_text: str = "",
    status_filter: str = "All",
) -> pd.DataFrame:
    """
    Filter Treatment Builder choices without changing scheduling behavior.
    """
    if definitions is None or definitions.empty:
        return pd.DataFrame(
            columns=(
                definitions.columns
                if definitions is not None
                else []
            )
        )

    result = definitions.copy()

    search = str(
        search_text or ""
    ).strip()

    if search:
        mask = pd.Series(
            False,
            index=result.index,
        )

        for column in (
            "name",
            "description",
            "notes",
            "products",
        ):
            if column not in result.columns:
                continue

            mask = (
                mask
                | result[column]
                .fillna("")
                .astype(str)
                .str.contains(
                    search,
                    case=False,
                    regex=False,
                )
            )

        result = result[
            mask
        ].copy()

    if (
        status_filter == "Active"
        and "active" in result.columns
    ):
        result = result[
            pd.to_numeric(
                result["active"],
                errors="coerce",
            )
            .fillna(0)
            .eq(1)
        ].copy()

    elif (
        status_filter == "Inactive"
        and "active" in result.columns
    ):
        result = result[
            pd.to_numeric(
                result["active"],
                errors="coerce",
            )
            .fillna(0)
            .eq(0)
        ].copy()

    return result.reset_index(
        drop=True
    )


def _definition_metrics(
    definitions: pd.DataFrame,
) -> dict[str, int]:
    if definitions is None or definitions.empty:
        return {
            "total": 0,
            "active": 0,
            "inactive": 0,
            "standard": 0,
        }

    if "active" in definitions.columns:
        active_values = (
            pd.to_numeric(
                definitions["active"],
                errors="coerce",
            )
            .fillna(0)
        )
    else:
        active_values = pd.Series(
            1,
            index=definitions.index,
        )

    if "standard" in definitions.columns:
        standard_values = (
            pd.to_numeric(
                definitions["standard"],
                errors="coerce",
            )
            .fillna(0)
        )
    else:
        standard_values = pd.Series(
            0,
            index=definitions.index,
        )

    return {
        "total": len(definitions),
        "active": int(
            active_values.eq(1).sum()
        ),
        "inactive": int(
            active_values.eq(0).sum()
        ),
        "standard": int(
            standard_values.eq(1).sum()
        ),
    }


# ==========================================================
# MAIN TAB
# ==========================================================

def render() -> None:
    st.header("Treatments")

    st.caption(
        "Build seasonal treatments, assign customer add-ons, "
        "adjust schedules for weather, and calculate mixtures."
    )

    definitions = get_treatment_definitions()
    customers = get_customers(
        active_only=True
    )
    products = get_products()

    (
        due_tab,
        builder_tab,
        chemical_tab,
        addon_tab,
        calculator_tab,
        history_tab,
    ) = st.tabs(
        [
            "Due Treatments",
            "Treatment Builder",
            "Chemical Library",
            "Customer Add-ons",
            "Mixture Calculator",
            "History",
        ]
    )

    # ======================================================
    # DUE TREATMENTS
    # ======================================================

    with due_tab:
        st.subheader(
            "Seasonal Schedule"
        )

        year_col, generate_col = (
            st.columns(
                [2, 1]
            )
        )

        schedule_year = (
            year_col.number_input(
                "Schedule Year",
                min_value=2020,
                max_value=2100,
                value=date.today().year,
                step=1,
            )
        )

        if generate_col.button(
            "Generate Standard Schedule",
            use_container_width=True,
        ):
            result = (
                generate_standard_events(
                    int(
                        schedule_year
                    )
                )
            )

            st.success(
                f"Created {result['created']} treatment visits. "
                f"Skipped {result['skipped']} existing visits."
            )

            st.rerun()

        events = (
            get_treatment_events()
        )

        if events.empty:
            st.info(
                "No planned treatments. Create treatment types, "
                "then generate the standard schedule."
            )

        else:
            today = pd.Timestamp(
                date.today()
            )

            events[
                "due_date"
            ] = pd.to_datetime(
                events[
                    "due_date"
                ],
                errors="coerce",
            )

            events[
                "days_from_today"
            ] = (
                events[
                    "due_date"
                ]
                - today
            ).dt.days

            def timing_text(
                value: Any,
            ) -> str:
                if pd.isna(value):
                    return ""

                number = int(
                    value
                )

                if number < 0:
                    return (
                        f"{abs(number)} "
                        "days overdue"
                    )

                if number == 0:
                    return "Due today"

                return (
                    f"Due in "
                    f"{number} days"
                )

            events[
                "timing"
            ] = events[
                "days_from_today"
            ].apply(
                timing_text
            )

            display_columns = [
                column
                for column
                in (
                    "id",
                    "customer",
                    "treatment",
                    "due_date",
                    "timing",
                    "event_type",
                    "override_reason",
                )
                if column
                in events.columns
            ]

            display = events[
                display_columns
            ].copy()

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "customer": "Customer",
                    "treatment": "Treatment",
                    "due_date": (
                        st.column_config.DateColumn(
                            "Due Date"
                        )
                    ),
                    "timing": "Timing",
                    "event_type": "Type",
                    "override_reason": (
                        "Weather/Override"
                    ),
                },
            )

            st.divider()

            st.subheader(
                "Manage Planned Treatment"
            )

            event_labels = {
                int(
                    row["id"]
                ): (
                    f"{row['customer']} — "
                    f"{row['treatment']} — "
                    f"{pd.to_datetime(row['due_date']).date()}"
                )
                for _, row
                in events.iterrows()
            }

            selected_event_id = (
                st.selectbox(
                    "Treatment Visit",
                    options=list(
                        event_labels
                    ),
                    format_func=lambda value: (
                        event_labels[
                            value
                        ]
                    ),
                )
            )

            selected_event = (
                events[
                    events[
                        "id"
                    ].astype(
                        int
                    )
                    == int(
                        selected_event_id
                    )
                ]
                .iloc[0]
            )

            action_col1, action_col2 = (
                st.columns(
                    2
                )
            )

            with action_col1:
                with st.form(
                    "reschedule_treatment_form"
                ):
                    new_due_date = (
                        st.date_input(
                            "New Due Date",
                            value=pd.to_datetime(
                                selected_event[
                                    "due_date"
                                ]
                            ).date(),
                        )
                    )

                    reschedule_reason = (
                        st.text_input(
                            "Reason",
                            placeholder=(
                                "Rainfall, drought, temperature, "
                                "customer request..."
                            ),
                        )
                    )

                    reschedule = (
                        st.form_submit_button(
                            "Reschedule Treatment",
                            use_container_width=True,
                        )
                    )

                    if reschedule:
                        reschedule_treatment_event(
                            selected_event_id,
                            new_due_date,
                            reschedule_reason,
                        )

                        st.success(
                            "Treatment rescheduled."
                        )

                        st.rerun()

            with action_col2:
                treatment_chemicals = (
                    get_treatment_products(
                        int(
                            selected_event[
                                "treatment_id"
                            ]
                        )
                    )
                )

                property_square_feet = (
                    _safe_float(
                        selected_event.get(
                            "square_feet"
                        ),
                        0.0,
                    )
                )

                property_acres = (
                    property_square_feet
                    / 43560.0
                )

                application_method = (
                    _safe_text(
                        selected_event.get(
                            "application_method"
                        ),
                        "broadcast",
                    )
                    .strip()
                    .lower()
                )

                is_spot_completion = (
                    application_method
                    == "spot"
                )

                try:
                    spot_batch_gallons = (
                        float(
                            get_setting(
                                "spot_tank_gallons",
                                "1.0",
                            )
                            or 1.0
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    spot_batch_gallons = 1.0

                completion_rate_label = (
                    "Rate Per Gallon"
                    if is_spot_completion
                    else "Rate Per Acre"
                )

                rate_basis_quantity = (
                    max(
                        spot_batch_gallons,
                        0.1,
                    )
                    if is_spot_completion
                    else property_acres
                )

                actual_rows = []

                for _, chemical in (
                    treatment_chemicals.iterrows()
                ):
                    calculated_total = (
                        _safe_float(
                            chemical.get(
                                "rate_per_acre"
                            ),
                            0.0,
                        )
                        * rate_basis_quantity
                    )

                    actual_rows.append(
                        {
                            "product_id": int(
                                chemical[
                                    "product_id"
                                ]
                            ),
                            "Chemical": (
                                chemical[
                                    "product_name"
                                ]
                            ),
                            "EPA Number": (
                                chemical.get(
                                    "epa_number",
                                    "",
                                )
                            ),
                            completion_rate_label: (
                                _safe_float(
                                    chemical.get(
                                        "rate_per_acre"
                                    ),
                                    0.0,
                                )
                            ),
                            "Unit": (
                                chemical.get(
                                    "rate_unit",
                                    "",
                                )
                            ),
                            "Calculated Total": (
                                round(
                                    calculated_total,
                                    4,
                                )
                            ),
                            "Actual Total": (
                                round(
                                    calculated_total,
                                    4,
                                )
                            ),
                        }
                    )

                with st.form(
                    "complete_treatment_form"
                ):
                    application_date = (
                        st.date_input(
                            "Application Date",
                            value=date.today(),
                        )
                    )

                    if actual_rows:
                        actual_chemicals = (
                            st.data_editor(
                                pd.DataFrame(
                                    actual_rows
                                ),
                                use_container_width=True,
                                hide_index=True,
                                disabled=[
                                    "product_id",
                                    "Chemical",
                                    "EPA Number",
                                    completion_rate_label,
                                    "Unit",
                                    "Calculated Total",
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
                            )
                        )

                    else:
                        actual_chemicals = (
                            pd.DataFrame()
                        )

                        st.warning(
                            "This treatment has no "
                            "chemicals assigned."
                        )

                    completion_notes = (
                        st.text_area(
                            "Completion Notes",
                            placeholder=(
                                "Weather, turf conditions, "
                                "observations..."
                            ),
                        )
                    )

                    complete = (
                        st.form_submit_button(
                            "Mark Treatment Complete",
                            type="primary",
                            use_container_width=True,
                        )
                    )

                    if complete:
                        actual_amounts = {
                            int(
                                row[
                                    "product_id"
                                ]
                            ): float(
                                row[
                                    "Actual Total"
                                ]
                            )
                            for _, row
                            in actual_chemicals.iterrows()
                        }

                        complete_treatment_event(
                            selected_event_id,
                            notes=(
                                completion_notes
                            ),
                            application_date=(
                                application_date
                            ),
                            actual_amounts=(
                                actual_amounts
                            ),
                        )

                        st.success(
                            "Treatment and chemical "
                            "application record saved."
                        )

                        st.rerun()

    # ======================================================
    # TREATMENT BUILDER
    # ======================================================

    with builder_tab:
        st.subheader(
            "Treatment Types"
        )

        metrics = (
            _definition_metrics(
                definitions
            )
        )

        m1, m2, m3, m4 = (
            st.columns(
                4
            )
        )

        m1.metric(
            "Treatment Types",
            metrics[
                "total"
            ],
        )

        m2.metric(
            "Active",
            metrics[
                "active"
            ],
        )

        m3.metric(
            "Inactive",
            metrics[
                "inactive"
            ],
        )

        m4.metric(
            "Standard Schedule",
            metrics[
                "standard"
            ],
        )

        st.caption(
            "Treatment types are unlimited. "
            "Inactive treatments remain available for history "
            "but are excluded from active scheduling."
        )

        search_col, status_col = (
            st.columns(
                [2, 1]
            )
        )

        builder_search = (
            search_col.text_input(
                "Search Treatments",
                placeholder=(
                    "Search name, description, products, or notes..."
                ),
                key="treatment_builder_search",
            )
        )

        builder_status = (
            status_col.selectbox(
                "Status",
                [
                    "All",
                    "Active",
                    "Inactive",
                ],
                key="treatment_builder_status",
            )
        )

        filtered_definitions = (
            _filtered_definitions(
                definitions,
                builder_search,
                builder_status,
            )
        )

        choices = [
            "Create New Treatment"
        ]

        if not filtered_definitions.empty:
            choices.extend(
                filtered_definitions[
                    "name"
                ].tolist()
            )

        selected_definition_name = (
            st.selectbox(
                "Treatment",
                choices,
                key=(
                    "treatment_builder_selection"
                ),
            )
        )

        if (
            selected_definition_name
            == "Create New Treatment"
        ):
            selected_definition = None

        else:
            selected_rows = (
                definitions[
                    definitions[
                        "name"
                    ]
                    == selected_definition_name
                ]
            )

            selected_definition = (
                None
                if selected_rows.empty
                else selected_rows.iloc[0]
            )

        if (
            selected_definition is None
        ):
            default_name = ""
            default_description = ""
            default_start = "01-01"
            default_end = "12-31"
            default_month = 1
            default_day = 1
            default_standard = True
            default_application_method = (
                "broadcast"
            )
            default_active = True
            default_notes = ""

        else:
            default_name = _safe_text(
                selected_definition.get(
                    "name"
                )
            )

            default_description = (
                _safe_text(
                    selected_definition.get(
                        "description"
                    )
                )
            )

            default_start = (
                _safe_text(
                    selected_definition.get(
                        "window_start"
                    ),
                    "01-01",
                )
            )

            default_end = (
                _safe_text(
                    selected_definition.get(
                        "window_end"
                    ),
                    "12-31",
                )
            )

            default_month = int(
                _safe_float(
                    selected_definition.get(
                        "target_month"
                    ),
                    1,
                )
            )

            default_day = int(
                _safe_float(
                    selected_definition.get(
                        "target_day"
                    ),
                    1,
                )
            )

            default_standard = bool(
                selected_definition.get(
                    "standard"
                )
            )

            default_application_method = (
                _safe_text(
                    selected_definition.get(
                        "application_method"
                    ),
                    "broadcast",
                )
                .strip()
                .lower()
            )

            if (
                default_application_method
                not in APPLICATION_METHOD_LABELS
            ):
                default_application_method = (
                    "broadcast"
                )

            default_active = bool(
                selected_definition.get(
                    "active"
                )
            )

            default_notes = _safe_text(
                selected_definition.get(
                    "notes"
                )
            )

        with st.form(
            "treatment_definition_form"
        ):
            treatment_name = (
                st.text_input(
                    "Treatment Name",
                    value=default_name,
                    placeholder=(
                        "Example: Early Spring "
                        "Pre-Emergent"
                    ),
                )
            )

            treatment_description = (
                st.text_area(
                    "Description",
                    value=default_description,
                )
            )

            date_col1, date_col2 = (
                st.columns(
                    2
                )
            )

            window_start = (
                date_col1.text_input(
                    "Season Window Start",
                    value=default_start,
                    help="Enter as MM-DD.",
                )
            )

            window_end = (
                date_col2.text_input(
                    "Season Window End",
                    value=default_end,
                    help="Enter as MM-DD.",
                )
            )

            target_col1, target_col2 = (
                st.columns(
                    2
                )
            )

            target_month = (
                target_col1.number_input(
                    "Target Month",
                    min_value=1,
                    max_value=12,
                    value=default_month,
                    step=1,
                )
            )

            target_day = (
                target_col2.number_input(
                    "Target Day",
                    min_value=1,
                    max_value=28,
                    value=default_day,
                    step=1,
                )
            )

            standard_treatment = (
                st.checkbox(
                    "Include in standard customer schedule",
                    value=default_standard,
                )
            )

            application_methods = list(
                APPLICATION_METHOD_LABELS
            )

            application_method = (
                st.selectbox(
                    "Application Method",
                    options=(
                        application_methods
                    ),
                    index=(
                        application_methods.index(
                            default_application_method
                        )
                    ),
                    format_func=lambda value: (
                        APPLICATION_METHOD_LABELS[
                            value
                        ]
                    ),
                    help=(
                        "Liquid Broadcast uses acreage and water GPA. "
                        "Spot Treatment uses a saved liquid batch. "
                        "Granular Broadcast uses acreage without water "
                        "or tanks."
                    ),
                )
            )

            active_treatment = (
                st.checkbox(
                    "Treatment is active",
                    value=default_active,
                )
            )

            treatment_notes = (
                st.text_area(
                    "Internal Notes",
                    value=default_notes,
                )
            )

            save_definition = (
                st.form_submit_button(
                    "Save Treatment",
                    type="primary",
                    use_container_width=True,
                )
            )

            if save_definition:
                treatment_id = (
                    None
                    if selected_definition
                    is None
                    else int(
                        selected_definition[
                            "id"
                        ]
                    )
                )

                try:
                    saved_id = (
                        save_treatment_definition(
                            name=(
                                treatment_name
                            ),
                            description=(
                                treatment_description
                            ),
                            standard=(
                                standard_treatment
                            ),
                            window_start=(
                                window_start
                            ),
                            window_end=(
                                window_end
                            ),
                            target_month=int(
                                target_month
                            ),
                            target_day=int(
                                target_day
                            ),
                            application_method=(
                                application_method
                            ),
                            active=(
                                active_treatment
                            ),
                            notes=(
                                treatment_notes
                            ),
                            treatment_id=(
                                treatment_id
                            ),
                        )
                    )

                except ValueError as exc:
                    st.error(
                        str(
                            exc
                        )
                    )

                else:
                    st.success(
                        f"Treatment saved with ID "
                        f"{saved_id}."
                    )

                    st.rerun()

        st.divider()

        st.subheader(
            "Treatment Chemicals and Rates"
        )

        definitions = (
            get_treatment_definitions()
        )

        products = get_products()

        if definitions.empty:
            st.info(
                "Save a treatment before adding chemicals."
            )

        elif products.empty:
            st.warning(
                "No products were imported from Herbicide_Data."
            )

        else:
            treatment_labels = (
                _label_lookup(
                    definitions,
                    "name",
                )
            )

            chemical_treatment_id = (
                st.selectbox(
                    "Treatment",
                    options=list(
                        treatment_labels
                    ),
                    format_func=lambda value: (
                        treatment_labels[
                            value
                        ]
                    ),
                    key=(
                        "chemical_treatment_selection"
                    ),
                )
            )

            chemical_definition = (
                definitions[
                    definitions[
                        "id"
                    ].astype(
                        int
                    )
                    == int(
                        chemical_treatment_id
                    )
                ]
                .iloc[0]
            )

            chemical_application_method = (
                _safe_text(
                    chemical_definition.get(
                        "application_method"
                    ),
                    "broadcast",
                )
                .strip()
                .lower()
            )

            is_spot_treatment = (
                chemical_application_method
                == "spot"
            )

            is_granular_treatment = (
                chemical_application_method
                == "granular"
            )

            rate_column_label = (
                "Rate Per Gallon"
                if is_spot_treatment
                else "Rate Per Acre"
            )

            if is_spot_treatment:
                st.caption(
                    "Enter each chemical amount per gallon "
                    "of finished spot-treatment mixture."
                )

            elif is_granular_treatment:
                st.caption(
                    "Enter each granular product amount "
                    "applied per treated acre, such as "
                    "pounds per acre."
                )

            else:
                st.caption(
                    "Enter each chemical amount applied "
                    "per treated acre."
                )

            assigned = (
                get_treatment_products(
                    chemical_treatment_id
                )
            )

            existing_product_ids = (
                assigned[
                    "product_id"
                ].astype(
                    int
                ).tolist()
                if not assigned.empty
                else []
            )

            product_labels = (
                _label_lookup(
                    products,
                    "product_name",
                )
            )

            selected_product_ids = (
                st.multiselect(
                    "Products",
                    options=list(
                        product_labels
                    ),
                    default=(
                        existing_product_ids
                    ),
                    format_func=lambda value: (
                        product_labels[
                            value
                        ]
                    ),
                    key=(
                        "treatment_products_"
                        f"{chemical_treatment_id}"
                    ),
                )
            )

            product_defaults = {}

            for _, product in (
                products.iterrows()
            ):
                product_id = int(
                    product[
                        "id"
                    ]
                )

                default_rate = (
                    pd.to_numeric(
                        product.get(
                            "default_rate",
                            0,
                        ),
                        errors="coerce",
                    )
                )

                if pd.isna(
                    default_rate
                ):
                    default_rate = 0.0

                default_unit = (
                    product.get(
                        "rate_unit",
                        "",
                    )
                )

                if pd.isna(
                    default_unit
                ):
                    default_unit = ""

                product_defaults[
                    product_id
                ] = {
                    "rate": float(
                        default_rate
                    ),
                    "unit": (
                        str(
                            default_unit
                        ).strip()
                        or "oz"
                    ),
                }

            existing_rates = {}

            if not assigned.empty:
                for _, row in (
                    assigned.iterrows()
                ):
                    product_id = int(
                        row[
                            "product_id"
                        ]
                    )

                    library_default = (
                        product_defaults.get(
                            product_id,
                            {
                                "rate": 0.0,
                                "unit": "oz",
                            },
                        )
                    )

                    assigned_rate = (
                        pd.to_numeric(
                            row.get(
                                "rate_per_acre",
                                0,
                            ),
                            errors="coerce",
                        )
                    )

                    if (
                        pd.isna(
                            assigned_rate
                        )
                        or float(
                            assigned_rate
                        )
                        == 0
                    ):
                        assigned_rate = (
                            library_default[
                                "rate"
                            ]
                        )

                    assigned_unit = (
                        row.get(
                            "rate_unit",
                            "",
                        )
                    )

                    if pd.isna(
                        assigned_unit
                    ):
                        assigned_unit = ""

                    existing_rates[
                        product_id
                    ] = {
                        "rate": float(
                            assigned_rate
                        ),
                        "unit": (
                            str(
                                assigned_unit
                            ).strip()
                            or library_default[
                                "unit"
                            ]
                        ),
                    }

            rate_rows = []

            for product_id in (
                selected_product_ids
            ):
                defaults = (
                    existing_rates.get(
                        int(
                            product_id
                        ),
                        product_defaults.get(
                            int(
                                product_id
                            ),
                            {
                                "rate": 0.0,
                                "unit": "oz",
                            },
                        ),
                    )
                )

                rate_rows.append(
                    {
                        "product_id": int(
                            product_id
                        ),
                        "Product": (
                            product_labels[
                                product_id
                            ]
                        ),
                        rate_column_label: (
                            defaults[
                                "rate"
                            ]
                        ),
                        "Unit": (
                            defaults[
                                "unit"
                            ]
                        ),
                    }
                )

            rates_df = pd.DataFrame(
                rate_rows
            )

            if not rates_df.empty:
                edited_rates = (
                    st.data_editor(
                        rates_df,
                        use_container_width=True,
                        hide_index=True,
                        disabled=[
                            "product_id",
                            "Product",
                        ],
                        column_config={
                            "product_id": None,
                            rate_column_label: (
                                st.column_config.NumberColumn(
                                    rate_column_label,
                                    min_value=0.0,
                                    format="%.4f",
                                )
                            ),
                            "Unit": (
                                st.column_config.TextColumn(
                                    "Unit",
                                    help=(
                                        "Examples: oz, lb, gal, qt"
                                    ),
                                )
                            ),
                        },
                        key=(
                            "treatment_rates_"
                            f"{chemical_treatment_id}_"
                            f"{chemical_application_method}"
                        ),
                    )
                )

            else:
                edited_rates = (
                    pd.DataFrame()
                )

                st.info(
                    "Select one or more products."
                )

            if st.button(
                "Save Chemicals and Rates",
                type="primary",
                use_container_width=True,
                key=(
                    "save_treatment_chemicals_"
                    f"{chemical_treatment_id}"
                ),
            ):
                product_assignments = []

                for _, row in (
                    edited_rates.iterrows()
                ):
                    product_assignments.append(
                        {
                            "product_id": int(
                                row[
                                    "product_id"
                                ]
                            ),
                            "rate_per_acre": float(
                                row[
                                    rate_column_label
                                ]
                            ),
                            "rate_unit": str(
                                row[
                                    "Unit"
                                ]
                            ),
                        }
                    )

                replace_treatment_products(
                    chemical_treatment_id,
                    product_assignments,
                )

                st.success(
                    "Treatment chemicals and rates saved."
                )

                st.rerun()

    # ======================================================
    # CHEMICAL LIBRARY
    # ======================================================

    with chemical_tab:
        st.subheader(
            "Chemical Library"
        )

        st.caption(
            "Add chemicals or edit products already "
            "imported from Herbicide_Data."
        )

        products = get_products()

        if not products.empty:
            st.dataframe(
                products,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "product_name": "Chemical",
                    "product_type": "Type",
                    "manufacturer": "Manufacturer",
                    "epa_number": "EPA Number",
                    "active_ingredient": (
                        "Active Ingredient"
                    ),
                    "default_rate": (
                        "Default Rate"
                    ),
                    "rate_unit": "Rate Unit",
                    "notes": "Notes",
                },
            )

        chemical_choices = [
            "Add New Chemical"
        ]

        if not products.empty:
            chemical_choices.extend(
                products[
                    "product_name"
                ].tolist()
            )

        selected_chemical_name = (
            st.selectbox(
                "Chemical to Edit",
                chemical_choices,
                key=(
                    "chemical_library_selection"
                ),
            )
        )

        selected_chemical = None

        if (
            selected_chemical_name
            != "Add New Chemical"
        ):
            selected_rows = (
                products[
                    products[
                        "product_name"
                    ]
                    == selected_chemical_name
                ]
            )

            if not selected_rows.empty:
                selected_chemical = (
                    selected_rows.iloc[0]
                )

        def chemical_value(
            column: str,
            default: Any = "",
        ) -> Any:
            if selected_chemical is None:
                return default

            value = (
                selected_chemical.get(
                    column,
                    default,
                )
            )

            try:
                if pd.isna(
                    value
                ):
                    return default
            except Exception:
                pass

            return value

        with st.form(
            "chemical_library_form"
        ):
            chemical_name = (
                st.text_input(
                    "Chemical Name",
                    value=str(
                        chemical_value(
                            "product_name"
                        )
                    ),
                )
            )

            chemical_type = (
                st.text_input(
                    "Product Type",
                    value=str(
                        chemical_value(
                            "product_type"
                        )
                    ),
                    placeholder=(
                        "Herbicide, fertilizer, fungicide, "
                        "insecticide..."
                    ),
                )
            )

            manufacturer = (
                st.text_input(
                    "Manufacturer",
                    value=str(
                        chemical_value(
                            "manufacturer"
                        )
                    ),
                )
            )

            epa_number = (
                st.text_input(
                    "EPA Registration Number",
                    value=str(
                        chemical_value(
                            "epa_number"
                        )
                    ),
                )
            )

            active_ingredient = (
                st.text_area(
                    "Active Ingredient",
                    value=str(
                        chemical_value(
                            "active_ingredient"
                        )
                    ),
                )
            )

            rate_col, unit_col = (
                st.columns(
                    2
                )
            )

            default_rate = (
                rate_col.number_input(
                    "Default Rate",
                    min_value=0.0,
                    value=_safe_float(
                        chemical_value(
                            "default_rate",
                            0.0,
                        )
                    ),
                    step=0.01,
                    format="%.4f",
                )
            )

            rate_unit = (
                unit_col.text_input(
                    "Rate Unit",
                    value=str(
                        chemical_value(
                            "rate_unit"
                        )
                    ),
                    placeholder=(
                        "oz/acre, lb/acre, "
                        "oz/1000 sq ft"
                    ),
                )
            )

            chemical_notes = (
                st.text_area(
                    "Notes",
                    value=str(
                        chemical_value(
                            "notes"
                        )
                    ),
                )
            )

            save_chemical = (
                st.form_submit_button(
                    "Save Chemical",
                    type="primary",
                    use_container_width=True,
                )
            )

            if save_chemical:
                product_id = (
                    None
                    if selected_chemical
                    is None
                    else int(
                        selected_chemical[
                            "id"
                        ]
                    )
                )

                try:
                    saved_product_id = (
                        save_product_definition(
                            product_name=(
                                chemical_name
                            ),
                            product_type=(
                                chemical_type
                            ),
                            manufacturer=(
                                manufacturer
                            ),
                            epa_number=(
                                epa_number
                            ),
                            active_ingredient=(
                                active_ingredient
                            ),
                            default_rate=(
                                default_rate
                            ),
                            rate_unit=(
                                rate_unit
                            ),
                            notes=(
                                chemical_notes
                            ),
                            product_id=(
                                product_id
                            ),
                        )
                    )

                except ValueError as exc:
                    st.error(
                        str(
                            exc
                        )
                    )

                else:
                    st.success(
                        f"Chemical saved with ID "
                        f"{saved_product_id}."
                    )

                    st.rerun()

    # ======================================================
    # CUSTOMER ADD-ONS
    # ======================================================

    with addon_tab:
        st.subheader(
            "Customer-Specific Treatment"
        )

        definitions = (
            get_treatment_definitions(
                active_only=True
            )
        )

        customers = get_customers(
            active_only=True
        )

        if (
            customers.empty
            or definitions.empty
        ):
            st.info(
                "Customers and active treatment "
                "definitions are required."
            )

        else:
            customer_labels = (
                _label_lookup(
                    customers,
                    "name",
                )
            )

            treatment_labels = (
                _label_lookup(
                    definitions,
                    "name",
                )
            )

            with st.form(
                "customer_addon_form"
            ):
                addon_customer_id = (
                    st.selectbox(
                        "Customer",
                        options=list(
                            customer_labels
                        ),
                        format_func=lambda value: (
                            customer_labels[
                                value
                            ]
                        ),
                    )
                )

                addon_treatment_id = (
                    st.selectbox(
                        "Additional Treatment",
                        options=list(
                            treatment_labels
                        ),
                        format_func=lambda value: (
                            treatment_labels[
                                value
                            ]
                        ),
                    )
                )

                addon_due_date = (
                    st.date_input(
                        "Due Date",
                        value=date.today(),
                    )
                )

                addon_notes = (
                    st.text_area(
                        "Reason or Notes",
                        placeholder=(
                            "Disease pressure, weeds, insects, "
                            "customer request..."
                        ),
                    )
                )

                add_treatment = (
                    st.form_submit_button(
                        "Add Customer Treatment",
                        type="primary",
                        use_container_width=True,
                    )
                )

                if add_treatment:
                    add_customer_treatment(
                        addon_customer_id,
                        addon_treatment_id,
                        addon_due_date,
                        addon_notes,
                    )

                    st.success(
                        "Customer treatment added."
                    )

                    st.rerun()

    # ======================================================
    # MIXTURE CALCULATOR
    # ======================================================

    with calculator_tab:
        st.subheader(
            "Chemical Mixture Calculator"
        )

        definitions = (
            get_treatment_definitions(
                active_only=True
            )
        )

        if definitions.empty:
            st.info(
                "Create an active treatment "
                "before calculating mixtures."
            )

        else:
            treatment_labels = (
                _label_lookup(
                    definitions,
                    "name",
                )
            )

            mixture_treatment_id = (
                st.selectbox(
                    "Treatment",
                    options=list(
                        treatment_labels
                    ),
                    format_func=lambda value: (
                        treatment_labels[
                            value
                        ]
                    ),
                    key=(
                        "mixture_treatment"
                    ),
                )
            )

            mixture_definition = (
                definitions[
                    definitions[
                        "id"
                    ].astype(
                        int
                    )
                    == int(
                        mixture_treatment_id
                    )
                ]
                .iloc[0]
            )

            mixture_method = (
                _safe_text(
                    mixture_definition.get(
                        "application_method"
                    ),
                    "broadcast",
                )
                .strip()
                .lower()
            )

            st.caption(
                f"Application Method: "
                f"{_method_label(mixture_method)}"
            )

            if mixture_method == "spot":
                try:
                    default_spot_batch = (
                        float(
                            get_setting(
                                "spot_tank_gallons",
                                "1.0",
                            )
                            or 1.0
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    default_spot_batch = 1.0

                tank_gallons = (
                    st.number_input(
                        "Spot Treatment Batch Gallons",
                        min_value=0.1,
                        value=(
                            default_spot_batch
                        ),
                        step=0.25,
                    )
                )

                square_feet = 0.0
                acres = 0.0
                gallons_per_acre = 1.0

                st.metric(
                    "Finished Spot Mixture",
                    f"{tank_gallons:g} gallons",
                )

            elif mixture_method == "granular":
                square_feet = (
                    st.number_input(
                        "Property Square Feet",
                        min_value=0.0,
                        value=43560.0,
                        step=1000.0,
                    )
                )

                acres = (
                    square_feet
                    / 43560.0
                )

                gallons_per_acre = 0.0
                tank_gallons = 0.0

                st.metric(
                    "Calculated Acres",
                    round(
                        acres,
                        4,
                    ),
                )

                st.caption(
                    "Granular product totals are calculated "
                    "by acreage without water or tank loads."
                )

            else:
                (
                    property_col,
                    spray_col,
                    tank_col,
                ) = st.columns(
                    3
                )

                square_feet = (
                    property_col.number_input(
                        "Property Square Feet",
                        min_value=0.0,
                        value=43560.0,
                        step=1000.0,
                    )
                )

                gallons_per_acre = (
                    spray_col.number_input(
                        "Spray Gallons Per Acre",
                        min_value=0.01,
                        value=20.0,
                        step=1.0,
                    )
                )

                tank_gallons = (
                    tank_col.number_input(
                        "Sprayer Tank Gallons",
                        min_value=0.01,
                        value=25.0,
                        step=1.0,
                    )
                )

                acres = (
                    square_feet
                    / 43560.0
                )

                st.metric(
                    "Calculated Acres",
                    round(
                        acres,
                        4,
                    ),
                )

            mixture = (
                calculate_mixture(
                    treatment_id=(
                        mixture_treatment_id
                    ),
                    acres=acres,
                    gallons_per_acre=(
                        gallons_per_acre
                    ),
                    tank_gallons=(
                        tank_gallons
                    ),
                )
            )

            if mixture.empty:
                st.warning(
                    "No chemicals have been assigned "
                    "to this treatment."
                )

            else:
                st.dataframe(
                    mixture,
                    use_container_width=True,
                    hide_index=True,
                )

    # ======================================================
    # HISTORY
    # ======================================================

    with history_tab:
        st.subheader(
            "Treatment History"
        )

        history = (
            get_treatment_events(
                include_completed=True
            )
        )

        if history.empty:
            st.info(
                "No treatment history is available."
            )

        else:
            history_search = (
                st.text_input(
                    "Search History",
                    placeholder=(
                        "Customer, treatment, notes..."
                    ),
                    key=(
                        "treatment_history_search"
                    ),
                )
            )

            display_history = (
                history.copy()
            )

            search = str(
                history_search
                or ""
            ).strip()

            if search:
                mask = pd.Series(
                    False,
                    index=(
                        display_history.index
                    ),
                )

                for column in (
                    "customer",
                    "treatment",
                    "event_type",
                    "override_reason",
                    "notes",
                ):
                    if (
                        column
                        not in display_history.columns
                    ):
                        continue

                    mask = (
                        mask
                        | display_history[
                            column
                        ]
                        .fillna("")
                        .astype(str)
                        .str.contains(
                            search,
                            case=False,
                            regex=False,
                        )
                    )

                display_history = (
                    display_history[
                        mask
                    ].copy()
                )

            st.dataframe(
                display_history,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "customer_id": None,
                    "treatment_id": None,
                },
            )


__all__ = [
    "render",
]
