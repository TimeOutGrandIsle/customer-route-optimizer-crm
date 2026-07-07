"""
Time Out Lawncare CRM

Route Scoring Engine

The optimizer uses business intelligence,
not just shortest distance.
"""

from __future__ import annotations

import pandas as pd

from services.production_learning import (
    calculate_production_scores,
)


# ----------------------------------------------------------
# DEFAULT WEIGHTS
# ----------------------------------------------------------

DEFAULT_WEIGHTS = {

    "production": 0.35,

    "drive": 0.20,

    "service": 0.15,

    "revenue": 0.15,

    "priority": 0.10,

    "technician": 0.05,

}


# ----------------------------------------------------------
# NORMALIZE
# ----------------------------------------------------------

def normalize(series):

    if series.empty:

        return series

    minimum = series.min()

    maximum = series.max()

    if maximum == minimum:

        return pd.Series(

            [1.0] * len(series),

            index=series.index,

        )

    return (

        series - minimum

    ) / (

        maximum - minimum

    )


# ----------------------------------------------------------
# ROUTE SCORE
# ----------------------------------------------------------

def score_routes(

    weights=None,

):

    if weights is None:

        weights = DEFAULT_WEIGHTS

    df = calculate_production_scores()

    if df.empty:

        return df

    df = df.copy()

    #
    # Normalize
    #

    df["production_n"] = normalize(

        df["production_score"]

    )

    df["revenue_n"] = normalize(

        df["avg_revenue"]

    )

    #
    # Smaller is better
    #

    df["drive_n"] = 1 - normalize(

        df["avg_drive"]

    )

    df["service_n"] = 1 - normalize(

        df["avg_service"]

    )

    #
    # Placeholder values
    #

    df["priority_n"] = 1.0

    df["technician_n"] = 1.0

    #
    # Final Score
    #

    df["route_score"] = (

        df["production_n"]

        * weights["production"]

        +

        df["drive_n"]

        * weights["drive"]

        +

        df["service_n"]

        * weights["service"]

        +

        df["revenue_n"]

        * weights["revenue"]

        +

        df["priority_n"]

        * weights["priority"]

        +

        df["technician_n"]

        * weights["technician"]

    )

    return df.sort_values(

        "route_score",

        ascending=False,

    )