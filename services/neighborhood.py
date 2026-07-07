#
# Time Out Lawncare CRM
#
# Neighborhood Intelligence
#

from __future__ import annotations

from math import radians
from math import sin
from math import cos
from math import sqrt
from math import atan2

import pandas as pd

from data.database import (
    get_connection,
    get_customers,
)


# ==========================================================
# CONFIGURATION
# ==========================================================

#
# Maximum distance (miles)
# between customers in the same
# neighborhood.
#

DEFAULT_CLUSTER_RADIUS = 0.35


# ==========================================================
# DISTANCE
# ==========================================================

def haversine_miles(

    lat1,

    lon1,

    lat2,

    lon2,

):

    """
    Great-circle distance.
    """

    if None in (

        lat1,

        lon1,

        lat2,

        lon2,

    ):

        return 999999

    R = 3958.8

    dlat = radians(lat2 - lat1)

    dlon = radians(lon2 - lon1)

    a = (

        sin(dlat / 2) ** 2

        + cos(radians(lat1))

        * cos(radians(lat2))

        * sin(dlon / 2) ** 2

    )

    c = 2 * atan2(

        sqrt(a),

        sqrt(1 - a),

    )

    return R * c


# ==========================================================
# LOAD
# ==========================================================

def customer_locations():

    """
    Returns only customers
    having coordinates.
    """

    df = get_customers()

    if df.empty:

        return df

    if "lat" not in df.columns:

        return pd.DataFrame()

    if "lng" not in df.columns:

        return pd.DataFrame()

    df = df.dropna(

        subset=[

            "lat",

            "lng",

        ]

    )

    return df.reset_index(

        drop=True

    )
    
# ==========================================================
# BUILD CLUSTERS
# ==========================================================

def build_clusters(

    radius=DEFAULT_CLUSTER_RADIUS,

):
    """
    Groups customers into geographic
    neighborhoods based strictly on
    distance.

    Returns a dataframe with

        cluster_id

        neighborhood

        distance_from_cluster
    """

    df = customer_locations()

    if df.empty:

        return df

    cluster_id = 0

    assigned = set()

    clusters = []

    for idx, row in df.iterrows():

        if idx in assigned:

            continue

        cluster_id += 1

        members = [idx]

        assigned.add(idx)

        changed = True

        while changed:

            changed = False

            for other_idx, other in df.iterrows():

                if other_idx in assigned:

                    continue

                for member in members:

                    distance = haversine_miles(

                        df.loc[member, "lat"],

                        df.loc[member, "lng"],

                        other["lat"],

                        other["lng"],

                    )

                    if distance <= radius:

                        assigned.add(other_idx)

                        members.append(other_idx)

                        changed = True

                        break

        center_lat = (

            df.loc[members, "lat"]

            .mean()

        )

        center_lng = (

            df.loc[members, "lng"]

            .mean()

        )

        neighborhood = (

            f"Cluster {cluster_id}"

        )

        for member in members:

            distance = haversine_miles(

                df.loc[member, "lat"],

                df.loc[member, "lng"],

                center_lat,

                center_lng,

            )

            clusters.append(

                {

                    "id": df.loc[member, "id"],

                    "cluster_id": cluster_id,

                    "neighborhood": neighborhood,

                    "distance_from_cluster": round(

                        distance,

                        3,

                    ),

                }

            )

    return pd.DataFrame(

        clusters

    )


# ==========================================================
# SAVE CLUSTERS
# ==========================================================

def save_clusters(

    radius=DEFAULT_CLUSTER_RADIUS,

):
    """
    Writes neighborhood information
    back into the customer table.
    """

    clusters = build_clusters(

        radius

    )

    if clusters.empty:

        return 0

    conn = get_connection()

    cur = conn.cursor()

    for _, row in clusters.iterrows():

        cur.execute(

            """
            UPDATE customers

            SET

                neighborhood=?,

                cluster_id=?,

                distance_from_cluster=?

            WHERE id=?

            """,

            (

                row["neighborhood"],

                row["cluster_id"],

                row["distance_from_cluster"],

                row["id"],

            ),

        )

    conn.commit()

    conn.close()

    return len(clusters)
    
# ==========================================================
# NEIGHBORHOOD INTELLIGENCE
# ==========================================================

#
# These are seed neighborhoods.
# The CRM will eventually allow these
# to be edited from the Settings screen.
#

KNOWN_NEIGHBORHOODS = {

    "Bridgewater": (
        32.4094,
        -90.1035,
    ),

    "Castlewoods": (
        32.3524,
        -90.0748,
    ),

    "Crossgates": (
        32.2884,
        -90.0183,
    ),

    "Reunion": (
        32.5037,
        -90.1090,
    ),

    "Reservoir": (
        32.4314,
        -90.1058,
    ),

    "Madison": (
        32.4618,
        -90.1150,
    ),

    "Brandon": (
        32.2737,
        -89.9865,
    ),

    "Flowood": (
        32.3090,
        -90.1384,
    ),

    "Pearl": (
        32.2740,
        -90.1320,
    ),

}


# ==========================================================
# FIND NEAREST NEIGHBORHOOD
# ==========================================================

def nearest_known_neighborhood(

    lat,

    lng,

):

    """
    Returns the closest known
    neighborhood center.
    """

    best_name = None

    best_distance = 999999

    for name, coords in KNOWN_NEIGHBORHOODS.items():

        distance = haversine_miles(

            lat,

            lng,

            coords[0],

            coords[1],

        )

        if distance < best_distance:

            best_distance = distance

            best_name = name

    return (

        best_name,

        round(best_distance, 2),

    )
    
from data.database import (
    save_neighborhood,
)

# ==========================================================
# BUILD KNOWLEDGE BASE
# ==========================================================

def build_neighborhood_database():

    customers = customer_locations()

    if customers.empty:

        return

    if "neighborhood" not in customers.columns:

        return

    for neighborhood in sorted(

        customers["neighborhood"]

        .dropna()

        .unique()

    ):

        area = customers[

            customers["neighborhood"]

            == neighborhood

        ]

        save_neighborhood(

            name=neighborhood,

            center_lat=area["lat"].mean(),

            center_lng=area["lng"].mean(),

            customer_count=len(area),

            average_square_feet=area.get(

                "square_feet",

                0,

            ).mean(),

            average_service_time=18,

            average_drive_time=4,

            preferred_day=None,

            preferred_crew=None,

            average_revenue=0,

            production_score=0,

            efficiency_score=0,

        )
        
