"""
Production Learning Engine
"""

import pandas as pd

from data.database import dataframe


def production_statistics():

    return dataframe(
        """
        SELECT

            c.neighborhood,

            COUNT(*) jobs,

            AVG(service_minutes) avg_service,

            AVG(drive_minutes) avg_drive,

            AVG(total_minutes) avg_total,

            AVG(revenue) avg_revenue,

            AVG(chemical_cost) avg_chemical_cost,

            SUM(revenue) total_revenue

        FROM service_history sh

        JOIN customers c

            ON sh.customer_id=c.id

        GROUP BY c.neighborhood

        ORDER BY total_revenue DESC
        """
    )
    
# ==========================================================
# PRODUCTION SCORE ENGINE
# ==========================================================

def calculate_production_scores():

    """
    Calculates an overall production score
    for every neighborhood.

    Higher scores indicate neighborhoods
    that produce the greatest revenue with
    the least amount of travel and labor.
    """

    df = production_statistics()

    if df.empty:

        return df

    df = df.copy()

    #
    # Prevent divide-by-zero
    #

    df["avg_service"] = (
        df["avg_service"]
        .fillna(0.0)
        .clip(lower=1)
    )

    df["avg_drive"] = (
        df["avg_drive"]
        .fillna(0.0)
    )

    df["avg_revenue"] = (
        df["avg_revenue"]
        .fillna(0.0)
    )

    df["avg_chemical_cost"] = (
        df["avg_chemical_cost"]
        .fillna(0.0)
    )

    #
    # Profit
    #

    df["profit"] = (

        df["avg_revenue"]

        -

        df["avg_chemical_cost"]

    )

    #
    # Revenue per minute
    #

    df["revenue_per_minute"] = (

        df["avg_revenue"]

        /

        (

            df["avg_service"]

            +

            df["avg_drive"]

        )

    )

    #
    # Profit per minute
    #

    df["profit_per_minute"] = (

        df["profit"]

        /

        (

            df["avg_service"]

            +

            df["avg_drive"]

        )

    )

    #
    # Production Score
    #

    df["production_score"] = (

        df["profit_per_minute"]

        * 100

    ).round(2)

    return df.sort_values(

        "production_score",

        ascending=False,

    )
    
# ==========================================================
# BEST NEIGHBORHOODS
# ==========================================================

def best_neighborhoods(

    limit=10,

):

    df = calculate_production_scores()

    if df.empty:

        return df

    return df.head(limit)
    
