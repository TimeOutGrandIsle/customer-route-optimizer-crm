from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.treatment_manager import (
    MAX_TREATMENTS,
    add_customer_treatment,
    save_product_definition,
    calculate_mixture,
    complete_treatment_event,
    generate_standard_events,
    get_treatment_definitions,
    get_treatment_events,
    get_treatment_products,
    replace_treatment_products,
    reschedule_treatment_event,
    save_treatment_definition,
    shift_pending_treatments,
)
from data.database import (
    get_customers,
    get_products,
)


def _label_lookup(df, label_column):
    return {
        int(row["id"]): str(row[label_column])
        for _, row in df.iterrows()
    }


def render():
    st.header("Treatments")

    st.caption(
        "Build seasonal treatments, assign customer add-ons, "
        "adjust schedules for weather, and calculate mixtures."
    )

    definitions = get_treatment_definitions()
    customers = get_customers(active_only=True)
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

        st.subheader("Seasonal Schedule")

        year_col, generate_col = st.columns([2, 1])

        schedule_year = year_col.number_input(
            "Schedule Year",
            min_value=2020,
            max_value=2100,
            value=date.today().year,
            step=1,
        )

        if generate_col.button(
            "Generate Standard Schedule",
            use_container_width=True,
        ):
            result = generate_standard_events(
                int(schedule_year)
            )

            st.success(
                f"Created {result['created']} treatment visits. "
                f"Skipped {result['skipped']} existing visits."
            )

            st.rerun()

        events = get_treatment_events()

        if events.empty:

            st.info(
                "No planned treatments. Create treatment types, "
                "then generate the standard schedule."
            )

        else:

            today = pd.Timestamp(date.today())

            events["due_date"] = pd.to_datetime(
                events["due_date"],
                errors="coerce",
            )

            events["days_from_today"] = (
                events["due_date"] - today
            ).dt.days

            events["timing"] = events[
                "days_from_today"
            ].apply(
                lambda value: (
                    f"{abs(int(value))} days overdue"
                    if value < 0
                    else (
                        "Due today"
                        if value == 0
                        else f"Due in {int(value)} days"
                    )
                )
            )

            display = events[
                [
                    "id",
                    "customer",
                    "treatment",
                    "due_date",
                    "timing",
                    "event_type",
                    "override_reason",
                ]
            ].copy()

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "customer": "Customer",
                    "treatment": "Treatment",
                    "due_date": st.column_config.DateColumn(
                        "Due Date"
                    ),
                    "timing": "Timing",
                    "event_type": "Type",
                    "override_reason": "Weather/Override",
                },
            )

            st.divider()
            st.subheader("Manage Planned Treatment")

            event_labels = {
                int(row["id"]): (
                    f"{row['customer']} — "
                    f"{row['treatment']} — "
                    f"{pd.to_datetime(row['due_date']).date()}"
                )
                for _, row in events.iterrows()
            }

            selected_event_id = st.selectbox(
                "Treatment Visit",
                options=list(event_labels),
                format_func=lambda value: event_labels[value],
            )

            selected_event = events[
                events["id"] == selected_event_id
            ].iloc[0]

            action_col1, action_col2 = st.columns(2)

            with action_col1:

                with st.form("reschedule_treatment_form"):

                    new_due_date = st.date_input(
                        "New Due Date",
                        value=pd.to_datetime(
                            selected_event["due_date"]
                        ).date(),
                    )

                    reschedule_reason = st.text_input(
                        "Reason",
                        placeholder=(
                            "Rainfall, drought, temperature, "
                            "customer request..."
                        ),
                    )

                    reschedule = st.form_submit_button(
                        "Reschedule Treatment",
                        use_container_width=True,
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

                treatment_chemicals = get_treatment_products(
                    int(selected_event["treatment_id"])
                )

                property_square_feet = float(
                    selected_event["square_feet"] or 0
                )

                property_acres = (
                    property_square_feet / 43560.0
                )

                actual_rows = []

                for _, chemical in treatment_chemicals.iterrows():

                    calculated_total = (
                        float(
                            chemical["rate_per_acre"] or 0
                        )
                        * property_acres
                    )

                    actual_rows.append(
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
                            "Rate Per Acre": float(
                                chemical[
                                    "rate_per_acre"
                                ]
                                or 0
                            ),
                            "Unit": chemical[
                                "rate_unit"
                            ],
                            "Calculated Total": round(
                                calculated_total,
                                4,
                            ),
                            "Actual Total": round(
                                calculated_total,
                                4,
                            ),
                        }
                    )

                with st.form("complete_treatment_form"):

                    application_date = st.date_input(
                        "Application Date",
                        value=date.today(),
                    )

                    if actual_rows:

                        actual_chemicals = st.data_editor(
                            pd.DataFrame(actual_rows),
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
                                    st.column_config.NumberColumn(
                                        "Actual Total",
                                        min_value=0.0,
                                        format="%.4f",
                                    )
                                ),
                            },
                        )

                    else:

                        actual_chemicals = pd.DataFrame()

                        st.warning(
                            "This treatment has no chemicals assigned."
                        )

                    completion_notes = st.text_area(
                        "Completion Notes",
                        placeholder=(
                            "Weather, turf conditions, "
                            "observations..."
                        ),
                    )

                    complete = st.form_submit_button(
                        "Mark Treatment Complete",
                        type="primary",
                        use_container_width=True,
                    )

                    if complete:

                        actual_amounts = {
                            int(row["product_id"]): float(
                                row["Actual Total"]
                            )
                            for _, row
                            in actual_chemicals.iterrows()
                        }

                        complete_treatment_event(
                            selected_event_id,
                            notes=completion_notes,
                            application_date=application_date,
                            actual_amounts=actual_amounts,
                        )

                        st.success(
                            "Treatment and chemical application "
                            "record saved."
                        )

                        st.rerun()

    # ======================================================
    # TREATMENT BUILDER
    # ======================================================

    with builder_tab:

        st.subheader("Treatment Types")

        st.metric(
            "Treatment Types",
            f"{len(definitions)} of {MAX_TREATMENTS}",
        )

        choices = ["Create New Treatment"]

        if not definitions.empty:
            choices.extend(
                definitions["name"].tolist()
            )

        selected_definition_name = st.selectbox(
            "Treatment",
            choices,
            key="treatment_builder_selection",
        )

        selected_definition = None

        if selected_definition_name != "Create New Treatment":

            selected_definition = definitions[
                definitions["name"]
                == selected_definition_name
            ].iloc[0]

        default_name = (
            ""
            if selected_definition is None
            else str(selected_definition["name"])
        )

        default_description = (
            ""
            if selected_definition is None
            else str(
                selected_definition["description"] or ""
            )
        )

        default_start = (
            "01-01"
            if selected_definition is None
            else str(selected_definition["window_start"])
        )

        default_end = (
            "12-31"
            if selected_definition is None
            else str(selected_definition["window_end"])
        )

        default_month = (
            1
            if selected_definition is None
            else int(selected_definition["target_month"])
        )

        default_day = (
            1
            if selected_definition is None
            else int(selected_definition["target_day"])
        )

        default_standard = (
            True
            if selected_definition is None
            else bool(selected_definition["standard"])
        )

        default_active = (
            True
            if selected_definition is None
            else bool(selected_definition["active"])
        )

        default_notes = (
            ""
            if selected_definition is None
            else str(selected_definition["notes"] or "")
        )

        with st.form("treatment_definition_form"):

            treatment_name = st.text_input(
                "Treatment Name",
                value=default_name,
                placeholder="Example: Early Spring Pre-Emergent",
            )

            treatment_description = st.text_area(
                "Description",
                value=default_description,
            )

            date_col1, date_col2 = st.columns(2)

            window_start = date_col1.text_input(
                "Season Window Start",
                value=default_start,
                help="Enter as MM-DD.",
            )

            window_end = date_col2.text_input(
                "Season Window End",
                value=default_end,
                help="Enter as MM-DD.",
            )

            target_col1, target_col2 = st.columns(2)

            target_month = target_col1.number_input(
                "Target Month",
                min_value=1,
                max_value=12,
                value=default_month,
                step=1,
            )

            target_day = target_col2.number_input(
                "Target Day",
                min_value=1,
                max_value=28,
                value=default_day,
                step=1,
            )

            standard_treatment = st.checkbox(
                "Include in standard customer schedule",
                value=default_standard,
            )

            active_treatment = st.checkbox(
                "Treatment is active",
                value=default_active,
            )

            treatment_notes = st.text_area(
                "Internal Notes",
                value=default_notes,
            )

            save_definition = st.form_submit_button(
                "Save Treatment",
                type="primary",
                use_container_width=True,
            )

            if save_definition:

                treatment_id = (
                    None
                    if selected_definition is None
                    else int(selected_definition["id"])
                )

                saved_id = save_treatment_definition(
                    name=treatment_name,
                    description=treatment_description,
                    standard=standard_treatment,
                    window_start=window_start,
                    window_end=window_end,
                    target_month=int(target_month),
                    target_day=int(target_day),
                    active=active_treatment,
                    notes=treatment_notes,
                    treatment_id=treatment_id,
                )

                st.success(
                    f"Treatment saved with ID {saved_id}."
                )

                st.rerun()

        st.divider()
        st.subheader("Treatment Chemicals and Rates")

        definitions = get_treatment_definitions()

        if definitions.empty:

            st.info(
                "Save a treatment before adding chemicals."
            )

        elif products.empty:

            st.warning(
                "No products were imported from Herbicide_Data."
            )

        else:

            treatment_labels = _label_lookup(
                definitions,
                "name",
            )

            chemical_treatment_id = st.selectbox(
                "Treatment",
                options=list(treatment_labels),
                format_func=lambda value: (
                    treatment_labels[value]
                ),
                key="chemical_treatment_selection",
            )

            assigned = get_treatment_products(
                chemical_treatment_id
            )

            existing_product_ids = (
                assigned["product_id"].astype(int).tolist()
                if not assigned.empty
                else []
            )

            product_labels = _label_lookup(
                products,
                "product_name",
            )

            selected_product_ids = st.multiselect(
                "Products",
                options=list(product_labels),
                default=existing_product_ids,
                format_func=lambda value: (
                    product_labels[value]
                ),
            )

            existing_rates = {}

            if not assigned.empty:

                existing_rates = {
                    int(row["product_id"]): {
                        "rate": float(row["rate_per_acre"]),
                        "unit": str(row["rate_unit"]),
                    }
                    for _, row in assigned.iterrows()
                }

            rate_rows = []

            for product_id in selected_product_ids:

                defaults = existing_rates.get(
                    int(product_id),
                    {
                        "rate": 0.0,
                        "unit": "oz",
                    },
                )

                rate_rows.append(
                    {
                        "product_id": int(product_id),
                        "Product": product_labels[product_id],
                        "Rate Per Acre": defaults["rate"],
                        "Unit": defaults["unit"],
                    }
                )

            rates_df = pd.DataFrame(rate_rows)

            if not rates_df.empty:

                edited_rates = st.data_editor(
                    rates_df,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[
                        "product_id",
                        "Product",
                    ],
                    column_config={
                        "product_id": None,
                        "Rate Per Acre": (
                            st.column_config.NumberColumn(
                                "Rate Per Acre",
                                min_value=0.0,
                                format="%.4f",
                            )
                        ),
                        "Unit": st.column_config.TextColumn(
                            "Unit",
                            help="Examples: oz, lb, gal, qt",
                        ),
                    },
                    key=(
                        "treatment_rates_"
                        f"{chemical_treatment_id}"
                    ),
                )

            else:

                edited_rates = pd.DataFrame()

                st.info(
                    "Select one or more products."
                )

            if st.button(
                "Save Chemicals and Rates",
                type="primary",
                use_container_width=True,
            ):

                product_assignments = []

                for _, row in edited_rates.iterrows():

                    product_assignments.append(
                        {
                            "product_id": int(
                                row["product_id"]
                            ),
                            "rate_per_acre": float(
                                row["Rate Per Acre"]
                            ),
                            "rate_unit": str(
                                row["Unit"]
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

        st.subheader("Chemical Library")

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
                    "active_ingredient": "Active Ingredient",
                    "default_rate": "Default Rate",
                    "rate_unit": "Rate Unit",
                    "notes": "Notes",
                },
            )

        chemical_choices = ["Add New Chemical"]

        if not products.empty:
            chemical_choices.extend(
                products["product_name"].tolist()
            )

        selected_chemical_name = st.selectbox(
            "Chemical to Edit",
            chemical_choices,
            key="chemical_library_selection",
        )

        selected_chemical = None

        if selected_chemical_name != "Add New Chemical":
            selected_chemical = products[
                products["product_name"]
                == selected_chemical_name
            ].iloc[0]

        def chemical_value(column, default=""):
            if selected_chemical is None:
                return default

            value = selected_chemical[column]

            if pd.isna(value):
                return default

            return value

        with st.form("chemical_library_form"):

            chemical_name = st.text_input(
                "Chemical Name",
                value=str(
                    chemical_value(
                        "product_name"
                    )
                ),
            )

            chemical_type = st.text_input(
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

            manufacturer = st.text_input(
                "Manufacturer",
                value=str(
                    chemical_value(
                        "manufacturer"
                    )
                ),
            )

            epa_number = st.text_input(
                "EPA Registration Number",
                value=str(
                    chemical_value(
                        "epa_number"
                    )
                ),
            )

            active_ingredient = st.text_area(
                "Active Ingredient",
                value=str(
                    chemical_value(
                        "active_ingredient"
                    )
                ),
            )

            rate_col, unit_col = st.columns(2)

            default_rate = rate_col.number_input(
                "Default Rate",
                min_value=0.0,
                value=float(
                    chemical_value(
                        "default_rate",
                        0.0,
                    )
                ),
                step=0.01,
                format="%.4f",
            )

            rate_unit = unit_col.text_input(
                "Rate Unit",
                value=str(
                    chemical_value(
                        "rate_unit"
                    )
                ),
                placeholder="oz/acre, lb/acre, oz/1000 sq ft",
            )

            chemical_notes = st.text_area(
                "Notes",
                value=str(
                    chemical_value(
                        "notes"
                    )
                ),
            )

            save_chemical = st.form_submit_button(
                "Save Chemical",
                type="primary",
                use_container_width=True,
            )

            if save_chemical:

                product_id = (
                    None
                    if selected_chemical is None
                    else int(selected_chemical["id"])
                )

                saved_product_id = save_product_definition(
                    product_name=chemical_name,
                    product_type=chemical_type,
                    manufacturer=manufacturer,
                    epa_number=epa_number,
                    active_ingredient=active_ingredient,
                    default_rate=default_rate,
                    rate_unit=rate_unit,
                    notes=chemical_notes,
                    product_id=product_id,
                )

                st.success(
                    f"Chemical saved with ID "
                    f"{saved_product_id}."
                )

                st.rerun()

    # ======================================================
    # CUSTOMER ADD-ONS
    # ======================================================

    with addon_tab:

        st.subheader("Customer-Specific Treatment")

        if customers.empty or definitions.empty:

            st.info(
                "Customers and treatment definitions are required."
            )

        else:

            customer_labels = _label_lookup(
                customers,
                "name",
            )

            treatment_labels = _label_lookup(
                definitions,
                "name",
            )

            with st.form("customer_addon_form"):

                addon_customer_id = st.selectbox(
                    "Customer",
                    options=list(customer_labels),
                    format_func=lambda value: (
                        customer_labels[value]
                    ),
                )

                addon_treatment_id = st.selectbox(
                    "Additional Treatment",
                    options=list(treatment_labels),
                    format_func=lambda value: (
                        treatment_labels[value]
                    ),
                )

                addon_due_date = st.date_input(
                    "Due Date",
                    value=date.today(),
                )

                addon_notes = st.text_area(
                    "Reason or Notes",
                    placeholder=(
                        "Disease pressure, weeds, insects, "
                        "customer request..."
                    ),
                )

                add_treatment = st.form_submit_button(
                    "Add Customer Treatment",
                    type="primary",
                    use_container_width=True,
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

        st.subheader("Chemical Mixture Calculator")

        if definitions.empty:

            st.info(
                "Create a treatment before calculating mixtures."
            )

        else:

            treatment_labels = _label_lookup(
                definitions,
                "name",
            )

            mixture_treatment_id = st.selectbox(
                "Treatment",
                options=list(treatment_labels),
                format_func=lambda value: (
                    treatment_labels[value]
                ),
                key="mixture_treatment",
            )

            property_col, spray_col, tank_col = st.columns(3)

            square_feet = property_col.number_input(
                "Property Square Feet",
                min_value=0.0,
                value=43560.0,
                step=1000.0,
            )

            gallons_per_acre = spray_col.number_input(
                "Spray Gallons Per Acre",
                min_value=0.01,
                value=20.0,
                step=1.0,
            )

            tank_gallons = tank_col.number_input(
                "Sprayer Tank Gallons",
                min_value=0.01,
                value=25.0,
                step=1.0,
            )

            acres = square_feet / 43560.0

            st.metric(
                "Calculated Acres",
                round(acres, 4),
            )

            mixture = calculate_mixture(
                treatment_id=mixture_treatment_id,
                acres=acres,
                gallons_per_acre=gallons_per_acre,
                tank_gallons=tank_gallons,
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

        st.subheader("Treatment History")

        history = get_treatment_events(
            include_completed=True
        )

        if history.empty:

            st.info(
                "No treatment history is available."
            )

        else:

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "customer_id": None,
                    "treatment_id": None,
                },
            )