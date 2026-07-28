# Time Out Lawncare CRM
# Import Data Tab
#
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from services.import_wizard import (
    open_workbook,
    validate_workbook,
    load_all_sheets,
    workbook_summary,
    preview_sheet,
)

# ==========================================================
# TAB ENTRY POINT
# ==========================================================

def render():
    
    st.header("Import Data")

    st.write(
        """
Import your Time Out Lawncare Excel workbook.

Supported worksheets:

• Customer_Data
• Applications
• Herbicide_Data
• Services & Prices
• Treatment Plans
• Chemical costs
"""
    )

    uploaded_file = st.file_uploader(

        "Select Workbook",

        type=["xlsx", "xlsm", "xls"],

        accept_multiple_files=False,

    )

    if uploaded_file is None:

        st.info("Choose an Excel workbook to begin.")

        return

    temp_path = Path("temp_import.xlsx")

    with open(temp_path, "wb") as f:

        f.write(uploaded_file.getbuffer())

    try:

        session = open_workbook(temp_path)

        valid = validate_workbook(session)

        load_all_sheets(session)
        

    except Exception as ex:

        st.exception(ex)

        return
        

# ==========================================================
# VALIDATION
# ==========================================================

    if valid:

        st.success(
            "Workbook validation passed."
        )

    else:

        st.error(
            "Workbook validation failed."
        )

        if session.errors:

            for err in session.errors:

                st.error(err)

        return

# ==========================================================
# WORKBOOK SUMMARY
# ==========================================================

    st.subheader("Workbook Summary")

    summary = workbook_summary(session)

    st.dataframe(

        summary,

        use_container_width=True,

        hide_index=True,

    )
    

    st.subheader("Worksheet Preview")

    # st.write("Reached Preview")

    # st.write(summary)

    # st.write(summary.columns.tolist())

    # st.write(summary["Worksheet"].tolist())

    
    
# ==========================================================
# IMPORT CONTROLS
# ==========================================================

  
    st.divider()

    st.subheader("Import Workbook")

    progress = st.progress(0)

    status = st.empty()

    def update_progress(percent, message):

        progress.progress(percent)

        status.info(message)

    col1, col2 = st.columns(2)

    with col1:

        start_import = st.button(

            "Import Workbook",

            type="primary",

            use_container_width=True,

        )

    with col2:

        st.button(

            "Cancel",

            disabled=True,

            use_container_width=True,

        )

# ==========================================================
# RUN IMPORT
# ==========================================================

    if start_import:

        try:

            from services.import_wizard import (
                run_workbook_import,
            )

          
            report = run_workbook_import(

                temp_path,

                progress_callback=update_progress,

            )

            progress.progress(100)

            status.success(

                "Workbook imported successfully."

            )

        except Exception as ex:

            progress.empty()

            status.empty()

            st.exception(ex)

            return

# ==========================================================
# IMPORT SUMMARY
# ==========================================================

        st.divider()

        st.header("Import Summary")

        st.metric(

            "Records Imported",

            report["total_imported"],

        )

        st.metric(

            "Duplicates",

            report["total_duplicates"],

        )

        st.metric(

            "Errors",

            report["total_errors"],

        )

        st.dataframe(

            report["summary"],

            use_container_width=True,

            hide_index=True,

        )

# ==========================================================
# WARNINGS
# ==========================================================

        warnings = report.get(

            "warnings",

            [],

        )

        if warnings:

            st.divider()

            st.subheader(

                "Warnings"

            )

            for warning in warnings:

                st.warning(

                    warning

                )

# ==========================================================
# ERRORS
# ==========================================================

        errors = report.get(

            "errors",

            [],

        )

        if errors:

            st.divider()

            st.subheader(

                "Errors"

            )

            for error in errors:

                st.error(

                    error

                )

# ==========================================================
# SUCCESS MESSAGE
# ==========================================================

        if (

            report["total_errors"] == 0

            and

            report["total_imported"] > 0

        ):

            st.success(

                "Your CRM database has been populated successfully."

            )

            st.balloons()

            