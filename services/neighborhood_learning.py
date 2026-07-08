
# Time Out Lawncare CRM
#
# Neighborhood Learning Engine

from __future__ import annotations

from datetime import datetime

import pandas as pd

from data.database import (
    dataframe,
    get_connection,
)


# ==========================================================
# LOAD COMPLETED WORK
# ==========================================================

def completed_jobs():

    """
    Returns every completed job
    with neighborhood information.
    """

    return dataframe(
        """
        SELECT

            sh.id,

            sh.customer_id,

            sh.service_date,

            sh.service_type,

            c.name,

            c.neighborhood,

            c.square_feet

        FROM service_history sh

        JOIN customers c

            ON sh.customer_id = c.id

        ORDER BY sh.service_date
        """
    )
    
# ==========================================================
# NEIGHBORHOOD METRICS
# ==========================================================

def neighborhood_statistics():

    jobs = completed_jobs()

    if jobs.empty:

        return pd.DataFrame()

    rows = []

    for neighborhood in sorted(

        jobs["neighborhood"]

        .dropna()

        .unique()

    ):

        area = jobs[
            jobs["neighborhood"]
            == neighborhood
        ]

        rows.append(

            {

                "Neighborhood": neighborhood,

                "Customers":

                    area["customer_id"]

                    .nunique(),

                "Applications":

                    len(area),

                "Average Lawn":

                    area["square_feet"]

                    .mean(),

            }

        )

    return pd.DataFrame(rows)
    
# ==========================================================
# UPDATE KNOWLEDGE BASE
# ==========================================================

def update_learning_database():

    stats = neighborhood_statistics()

    if stats.empty:

        return 0

    conn = get_connection()

    cur = conn.cursor()

    updated = 0

    for _, row in stats.iterrows():

        cur.execute(

            """
            UPDATE neighborhoods

            SET

                customer_count=?,

                average_square_feet=?,

                last_updated=CURRENT_TIMESTAMP

            WHERE name=?

            """,

            (

                int(row["Customers"]),

                float(row["Average Lawn"]),

                row["Neighborhood"],

            ),

        )

        updated += 1

    conn.commit()

    conn.close()

    return updated
    
