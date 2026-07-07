# Time Out Lawncare CRM
# Routing Engine

# Version 3.0

# Google Routes API
# SQLite Route Cache
# Automatic Fallback

from __future__ import annotations

import os
from typing import Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

from services.geocoding import distance_between

from data.database import (
    get_cached_route,
    save_cached_route,
)

try:
    GOOGLE_API_KEY = st.secrets.get(
        "GOOGLE_API_KEY",
        "",
    )
except Exception:
    GOOGLE_API_KEY = os.getenv(
        "GOOGLE_API_KEY",
        "",
    )


DEFAULT_DEPOT = {
    "name": "Time Out Lawncare",
    "address": "Brandon, MS",
    "lat": 32.2737,
    "lng": -89.9865,
}

AVERAGE_SPEED_MPH = 35
SERVICE_TIME_MINUTES = 20


def valid_stop(stop: Dict) -> bool:
    try:
        float(stop["lat"])
        float(stop["lng"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def add_depot(
    jobs: List[Dict],
    depot: Optional[Dict] = None,
) -> List[Dict]:
    if depot is None:
        depot = DEFAULT_DEPOT

    valid_jobs = [
        job.copy()
        for job in jobs
        if valid_stop(job)
    ]

    return [
        depot.copy(),
        *valid_jobs,
    ]


def cached_drive(
    origin: Dict,
    destination: Dict,
):
    origin_address = origin.get("address", "")
    destination_address = destination.get(
        "address",
        "",
    )

    if not origin_address or not destination_address:
        return None

    df = get_cached_route(
        origin_address,
        destination_address,
    )

    if df is None or df.empty:
        return None

    row = df.iloc[0]

    return {
        "distance_meters": float(
            row["distance_meters"]
        ),
        "duration_seconds": float(
            row["duration_seconds"]
        ),
    }


def save_drive(
    origin: Dict,
    destination: Dict,
    distance_meters: float,
    duration_seconds: float,
):
    save_cached_route(
        origin.get("address", ""),
        destination.get("address", ""),
        distance_meters,
        duration_seconds,
        "Google Routes",
    )

# ---------------------------------------------------------
# GOOGLE CONFIGURATION
# ---------------------------------------------------------

# ---------------------------------------------------------
# GOOGLE ROUTES API
# ---------------------------------------------------------

ROUTES_URL = (
    "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
)

HTTP = requests.Session()

REQUEST_TIMEOUT = 8


def google_drive(
    origin: Dict,
    destination: Dict,
):
    """
    Returns driving distance and travel time
    using the Google Routes API.

    Results are cached automatically.
    """

    cached = cached_drive(
        origin,
        destination,
    )

    if cached is not None:
        return cached

    if not GOOGLE_API_KEY:
        return None

    headers = {

        "Content-Type":
            "application/json",

        "X-Goog-Api-Key":
            GOOGLE_API_KEY,

        "X-Goog-FieldMask":
            ",".join([
                "originIndex",
                "destinationIndex",
                "status",
                "distanceMeters",
                "duration",
            ]),

    }

    body = {

        "origins": [

            {

                "waypoint": {

                    "location": {

                        "latLng": {

                            "latitude":
                                float(origin["lat"]),

                            "longitude":
                                float(origin["lng"]),

                        }

                    }

                }

            }

        ],

        "destinations": [

            {

                "waypoint": {

                    "location": {

                        "latLng": {

                            "latitude":
                                float(destination["lat"]),

                            "longitude":
                                float(destination["lng"]),

                        }

                    }

                }

            }

        ],

        "travelMode":
            "DRIVE",

        "routingPreference":
            "TRAFFIC_UNAWARE",

    }

    try:

        response = HTTP.post(

            ROUTES_URL,

            headers=headers,

            json=body,

            timeout=REQUEST_TIMEOUT,

        )

        response.raise_for_status()

        payload = response.json()

        if isinstance(payload, list):
            if not payload:
                return None

            row = payload[0]
        elif isinstance(payload, dict):
            row = payload
        else:
            return None

        if (
            row.get("status")
            and row["status"].get("code", 0) != 0
        ):
            return None

        if "distanceMeters" not in row:
            return None

        distance = float(
            row["distanceMeters"]
        )

        duration = row["duration"]

        seconds = float(
            duration.rstrip("s")
        )

        save_drive(

            origin,

            destination,

            distance,

            seconds,

        )

        return {

            "distance_meters":
                distance,

            "duration_seconds":
                seconds,

        }

    except requests.RequestException:

        return None

    except Exception:

        return None


# ---------------------------------------------------------
# FALLBACK
# ---------------------------------------------------------

def fallback_drive(
    origin: Dict,
    destination: Dict,
):

    miles = distance_between(

        origin["lat"],

        origin["lng"],

        destination["lat"],

        destination["lng"],

    )

    return {

        "distance_meters": miles * 1609.344,

        "duration_seconds":
        (miles / AVERAGE_SPEED_MPH) * 3600,

    }


# ---------------------------------------------------------
# DRIVE LOOKUP
# ---------------------------------------------------------

def drive_info(
    origin: Dict,
    destination: Dict,
):
    """
    Returns drive distance/time.

    Google -> Cache -> Haversine fallback
    """

    result = google_drive(
        origin,
        destination,
    )

    if result:

        return result

    return fallback_drive(
        origin,
        destination,
    )


# ---------------------------------------------------------
# DISTANCE MATRIX
# ---------------------------------------------------------

def build_drive_matrix(
    stops: List[Dict],
):

    matrix = []

    for origin in stops:

        row = []

        for destination in stops:

            drive = drive_info(
                origin,
                destination,
            )

            #
            # OR-Tools works best with integers.
            #
            row.append(
                int(
                    drive["duration_seconds"]
                )
            )

        matrix.append(row)

    return matrix
    
# ---------------------------------------------------------
# OR-TOOLS SUPPORT
# ---------------------------------------------------------

try:

    from ortools.constraint_solver import (
        pywrapcp,
        routing_enums_pb2,
    )

    ORTOOLS_AVAILABLE = True

except Exception:

    ORTOOLS_AVAILABLE = False


# ---------------------------------------------------------
# NEAREST NEIGHBOR FALLBACK
# ---------------------------------------------------------

def nearest_neighbor_route(
    stops: List[Dict],
) -> List[Dict]:
    """
    Simple optimizer used when OR-Tools is unavailable.
    """

    if len(stops) <= 2:
        return stops

    depot = stops[0]

    remaining = stops[1:-1].copy()

    route = [depot]

    current = depot

    while remaining:

        nearest = min(

            remaining,

            key=lambda stop:
                drive_info(
                    current,
                    stop,
                )["duration_seconds"],

        )

        route.append(nearest)

        remaining.remove(nearest)

        current = nearest

    route.append(depot)

    return route


# ---------------------------------------------------------
# OR-TOOLS
# ---------------------------------------------------------

def optimize_route(
    stops: List[Dict],
) -> List[Dict]:

    if not stops:
        return []

    if len(stops) == 1:
        return stops

    if len(stops) == 2:
        return [
            stops[0],
            stops[1],
            stops[0].copy(),
        ]

    if not ORTOOLS_AVAILABLE:
        return nearest_neighbor_route(stops)

    matrix = build_drive_matrix(stops)

    manager = pywrapcp.RoutingIndexManager(

        len(matrix),

        1,

        0,

    )

    routing = pywrapcp.RoutingModel(
        manager
    )

    def transit_callback(
        from_index,
        to_index,
    ):

        from_node = manager.IndexToNode(
            from_index
        )

        to_node = manager.IndexToNode(
            to_index
        )

        return matrix[from_node][to_node]

    callback_index = routing.RegisterTransitCallback(
        transit_callback
    )

    routing.SetArcCostEvaluatorOfAllVehicles(
        callback_index
    )

    search = pywrapcp.DefaultRoutingSearchParameters()

    search.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )

    search.time_limit.seconds = 15

    solution = routing.SolveWithParameters(
        search
    )

    if solution is None:
        return nearest_neighbor_route(stops)

    index = routing.Start(0)

    ordered = []

    while not routing.IsEnd(index):

        node = manager.IndexToNode(index)

        ordered.append(
            stops[node]
        )

        index = solution.Value(
            routing.NextVar(index)
        )

    ordered.append(
        stops[0]
    )

    return ordered


# ---------------------------------------------------------
# ROUTE METRICS
# ---------------------------------------------------------

def calculate_route_metrics(
    route: List[Dict],
):

    total_distance = 0.0

    total_drive = 0.0

    elapsed = 0.0

    for i, stop in enumerate(route):

        stop["stop_number"] = i

        if i == 0:

            stop["distance_miles"] = 0.0

            stop["drive_minutes"] = 0.0

            stop["arrival_minutes"] = 0.0

            continue

        drive = drive_info(
            route[i - 1],
            stop,
        )

        miles = (
            drive["distance_meters"] / 1609.344
        )

        minutes = (
            drive["duration_seconds"] / 60
        )

        total_distance += miles

        total_drive += minutes

        elapsed += minutes

        if i < len(route) - 1:

            elapsed += SERVICE_TIME_MINUTES

        stop["distance_miles"] = round(
            miles,
            2,
        )

        stop["drive_minutes"] = round(
            minutes,
            1,
        )

        stop["arrival_minutes"] = round(
            elapsed,
            1,
        )

    return {

        "total_distance": round(
            total_distance,
            2,
        ),

        "drive_minutes": round(
            total_drive,
            1,
        ),

        "service_minutes":
            max(
                len(route) - 2,
                0,
            ) * SERVICE_TIME_MINUTES,

        "total_minutes": round(
            total_drive
            +
            (
                max(
                    len(route) - 2,
                    0,
                )
                * SERVICE_TIME_MINUTES
            ),
            1,
        ),

    }


# ---------------------------------------------------------
# BUILD ROUTE
# ---------------------------------------------------------

def build_route(
    customers: List[Dict],
    depot: Optional[Dict] = None,
):

    jobs = []

    for customer in customers:

        if valid_stop(customer):

            jobs.append(customer)

    route = add_depot(
        jobs,
        depot,
    )

    route = optimize_route(
        route
    )

    calculate_route_metrics(
        route
    )

    return route


# ---------------------------------------------------------
# BUILD DISPATCH ROUTE
# ---------------------------------------------------------

def build_dispatch_route(
    depot: Dict,
    jobs: List[Dict],
):

    route = add_depot(
        jobs,
        depot,
    )

    route = optimize_route(
        route
    )

    calculate_route_metrics(
        route
    )

    return route
    
# ---------------------------------------------------------
# DRIVER MANIFEST
# ---------------------------------------------------------

from urllib.parse import quote


def google_maps_url(route: List[Dict]) -> str:
    """
    Creates a Google Maps navigation URL.
    """

    if len(route) < 2:
        return ""

    origin = route[0]["address"]

    destination = route[-1]["address"]

    waypoints = [
        stop["address"]
        for stop in route[1:-1]
    ]

    url = (
        "https://www.google.com/maps/dir/?api=1"
    )

    url += "&origin=" + quote(origin)

    url += "&destination=" + quote(destination)

    url += "&travelmode=driving"

    if waypoints:

        url += "&waypoints=" + quote(
            "|".join(waypoints)
        )

    return url


def driver_manifest(
    route: List[Dict],
) -> List[Dict]:
    """
    Produces a printable driver manifest.
    """

    manifest = []

    for stop in route:

        manifest.append({

            "Stop":

                stop.get(
                    "stop_number",
                    0,
                ),

            "Customer":

                stop.get(
                    "name",
                    "",
                ),

            "Address":

                stop.get(
                    "address",
                    "",
                ),

            "Arrival":

                stop.get(
                    "arrival_minutes",
                    0,
                ),

            "Drive":

                stop.get(
                    "drive_minutes",
                    0,
                ),

            "Miles":

                stop.get(
                    "distance_miles",
                    0,
                ),

            "Service":

                stop.get(
                    "service",
                    "",
                ),

            "Notes":

                stop.get(
                    "notes",
                    "",
                ),

        })

    return manifest


# ---------------------------------------------------------
# ROUTE SUMMARY
# ---------------------------------------------------------

def route_summary(
    route: List[Dict],
) -> Dict:

    metrics = calculate_route_metrics(route)

    return {

        "stops":

            max(
                len(route) - 2,
                0,
            ),

        "distance_miles":

            metrics[
                "total_distance"
            ],

        "drive_minutes":

            metrics[
                "drive_minutes"
            ],

        "service_minutes":

            metrics[
                "service_minutes"
            ],

        "total_minutes":

            metrics[
                "total_minutes"
            ],

        "google_maps":

            google_maps_url(
                route
            ),

    }


# ---------------------------------------------------------
# DATAFRAME EXPORT
# ---------------------------------------------------------

def route_dataframe(
    route: List[Dict],
):

    rows = []

    for stop in route:

        rows.append({

            "Stop":

                stop.get(
                    "stop_number",
                    0,
                ),

            "Customer":

                stop.get(
                    "name",
                    "",
                ),

            "Address":

                stop.get(
                    "address",
                    "",
                ),

            "Service":

                stop.get(
                    "service",
                    "",
                ),

            "Miles":

                stop.get(
                    "distance_miles",
                    0,
                ),

            "Drive Minutes":

                stop.get(
                    "drive_minutes",
                    0,
                ),

            "Arrival":

                stop.get(
                    "arrival_minutes",
                    0,
                ),

            "Latitude":

                stop.get(
                    "lat",
                    None,
                ),

            "Longitude":

                stop.get(
                    "lng",
                    None,
                ),

        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------
# MULTI-CREW SPLIT
# ---------------------------------------------------------

def neighborhood_key(job: Dict) -> str:
    """Prefer cluster ID, then neighborhood name."""
    cluster_id = job.get("cluster_id")

    try:
        cluster_number = int(cluster_id or 0)
    except (TypeError, ValueError):
        cluster_number = 0

    if cluster_number > 0:
        return f"cluster:{cluster_number}"

    neighborhood = str(
        job.get("neighborhood") or ""
    ).strip().casefold()

    if neighborhood:
        return f"neighborhood:{neighborhood}"

    customer_id = job.get(
        "customer_id",
        job.get("id", id(job)),
    )

    return f"ungrouped:{customer_id}"


def split_route(
    jobs: List[Dict],
    crews: int,
) -> List[List[Dict]]:
    """
    Keep neighborhoods or clusters together while balancing
    the number of stops assigned to each crew.
    """
    if crews <= 1:
        return [jobs]

    crew_count = min(
        max(1, int(crews)),
        max(1, len(jobs)),
    )

    grouped_jobs: Dict[str, List[Dict]] = {}

    for job in jobs:
        key = neighborhood_key(job)

        grouped_jobs.setdefault(
            key,
            [],
        ).append(job)

    neighborhood_groups = sorted(
        grouped_jobs.values(),
        key=len,
        reverse=True,
    )

    groups = [
        []
        for _ in range(crew_count)
    ]

    for neighborhood_group in neighborhood_groups:
        smallest_crew = min(
            range(crew_count),
            key=lambda index: len(groups[index]),
        )

        groups[smallest_crew].extend(
            neighborhood_group
        )

    return groups


def build_multi_crew_routes(
    depot: Dict,
    jobs: List[Dict],
    crews: int = 2,
):

    routes = []

    groups = split_route(
        jobs,
        crews,
    )

    for crew_number, group in enumerate(groups):

        route = build_dispatch_route(
            depot,
            group,
        )

        routes.append({

            "crew":

                crew_number + 1,

            "summary":

                route_summary(
                    route
                ),

            "route":

                route,

            "manifest":

                driver_manifest(
                    route
                ),

        })

    return routes


# ---------------------------------------------------------
# PUBLIC EXPORTS
# ---------------------------------------------------------

__all__ = [

    "DEFAULT_DEPOT",

    "build_route",

    "build_dispatch_route",

    "build_multi_crew_routes",

    "route_dataframe",

    "route_summary",

    "driver_manifest",

    "google_maps_url",

    "drive_info",

    "calculate_route_metrics",

]

# ---------------------------------------------------------
# ROUTE VALIDATION
# ---------------------------------------------------------

def validate_route(route: List[Dict]) -> List[str]:
    """
    Validate a completed route.
    Returns a list of warnings.
    """

    warnings = []

    if len(route) < 2:
        warnings.append("Route contains no stops.")
        return warnings

    ids = set()

    for stop in route:

        if not valid_stop(stop):
            warnings.append(
                f"Invalid coordinates: {stop.get('name','Unknown')}"
            )

        customer_id = stop.get("id")

        if customer_id is not None:

            if customer_id in ids:
                warnings.append(
                    f"Duplicate customer: {stop.get('name')}"
                )

            ids.add(customer_id)

    return warnings


# ---------------------------------------------------------
# DRIVER SCHEDULE
# ---------------------------------------------------------

def driver_schedule(route):

    schedule = []

    current = 0

    for stop in route:

        current += stop.get(
            "drive_minutes",
            0,
        )

        arrive = current

        depart = arrive

        if stop.get("stop_number", 0) > 0:

            depart += SERVICE_TIME_MINUTES

        schedule.append({

            "stop":

                stop.get(
                    "stop_number",
                    0,
                ),

            "customer":

                stop.get(
                    "name",
                    "",
                ),

            "arrival":

                round(
                    arrive,
                    1,
                ),

            "departure":

                round(
                    depart,
                    1,
                ),

        })

        current = depart

    return schedule


# ---------------------------------------------------------
# CSV EXPORT
# ---------------------------------------------------------

def export_route_csv(
    route,
    filename="route.csv",
):

    df = route_dataframe(
        route
    )

    df.to_csv(
        filename,
        index=False,
    )

    return filename


# ---------------------------------------------------------
# ROUTE REPORT
# ---------------------------------------------------------

def route_report(
    route,
):

    summary = route_summary(
        route
    )

    report = {

        "summary": summary,

        "warnings": validate_route(
            route
        ),

        "manifest": driver_manifest(
            route
        ),

        "schedule": driver_schedule(
            route
        ),

        "maps":

            google_maps_url(
                route
            ),

    }

    return report


# ---------------------------------------------------------
# DISPATCH REPORT
# ---------------------------------------------------------

def dispatch_report(
    depot,
    jobs,
):

    route = build_dispatch_route(
        depot,
        jobs,
    )

    return route_report(
        route
    )


# ---------------------------------------------------------
# ROUTE STATISTICS
# ---------------------------------------------------------

def route_statistics(
    route,
):

    customers = max(
        len(route) - 2,
        0,
    )

    total_distance = sum(

        stop.get(
            "distance_miles",
            0,
        )

        for stop in route

    )

    total_drive = sum(

        stop.get(
            "drive_minutes",
            0,
        )

        for stop in route

    )

    average_drive = 0

    if customers:

        average_drive = (
            total_drive
            / customers
        )

    return {

        "customers":

            customers,

        "total_distance":

            round(
                total_distance,
                2,
            ),

        "total_drive_minutes":

            round(
                total_drive,
                1,
            ),

        "average_drive_minutes":

            round(
                average_drive,
                1,
            ),

    }


# ---------------------------------------------------------
# PUBLIC HEALTH CHECK
# ---------------------------------------------------------

def routing_health():

    return {

        "google_enabled":

            bool(
                GOOGLE_API_KEY
            ),

        "ortools":

            ORTOOLS_AVAILABLE,

        "cache_provider":

            "SQLite",

        "travel_provider":

            (
                "Google Routes"
                if GOOGLE_API_KEY
                else "Haversine"
            ),

    }


# ---------------------------------------------------------
# SELF TEST
# ---------------------------------------------------------

if __name__ == "__main__":

    print()

    print("Routing Engine")

    print("----------------------")

    print(routing_health())

    print()

    print("Ready.")