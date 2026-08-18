"""
services/routing.py

Routing engine for Time Out Lawncare CRM.

This module intentionally contains no Streamlit UI. It provides routing,
distance, route-splitting, Google Maps navigation, and multi-crew helpers for
the CRM, Dispatch, and Field views.

Compatibility:
- build_distance_matrix()
- solve_route()
- split_routes()
- build_navigation_url()
- build_route()
- build_dispatch_route()

New architecture:
- Customer Type never affects route optimization.
- Any selected/queued job can be routed regardless of scheduled date.
- Routes can be split across any number of crews.
- Each crew route is optimized independently.
- Navigation links can use the crew phone's current location.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote_plus, urlencode

import pandas as pd

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
except Exception:  # Allows the rest of the app to import without OR-Tools.
    pywrapcp = None
    routing_enums_pb2 = None


EARTH_RADIUS_MILES = 3958.7613
DEFAULT_MAX_STOPS = 10
DEFAULT_SERVICE_MINUTES = 20
GOOGLE_MAPS_DIRECTIONS_URL = "https://www.google.com/maps/dir/"


@dataclass(frozen=True)
class RoutePoint:
    """Normalized route point used internally by the routing engine."""

    id: Any
    name: str
    address: str
    lat: float
    lng: float
    payload: Mapping[str, Any]


def _value(record: Any, *keys: str, default: Any = None) -> Any:
    """Read the first available field from a mapping, Series, or object."""
    for key in keys:
        if isinstance(record, Mapping) and key in record:
            value = record.get(key)
            if value is not None:
                return value

        if isinstance(record, pd.Series) and key in record.index:
            value = record.get(key)
            if value is not None:
                return value

        if hasattr(record, key):
            value = getattr(record, key)
            if value is not None:
                return value

    return default


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_coordinates(lat: Any, lng: Any) -> bool:
    lat_value = _float_or_none(lat)
    lng_value = _float_or_none(lng)

    if lat_value is None or lng_value is None:
        return False

    return (
        -90.0 <= lat_value <= 90.0
        and -180.0 <= lng_value <= 180.0
    )


def full_address(record: Any) -> str:
    """Build a display/navigation address from a customer/job record."""
    explicit = _value(record, "full_address")
    if explicit:
        return str(explicit).strip()

    street = _value(
        record,
        "street_address",
        "address",
        default="",
    )
    city = _value(record, "city", default="")
    state = _value(record, "state", default="")
    zip_code = _value(record, "zip", "zip_code", default="")

    street = "" if street is None else str(street).strip()
    city = "" if city is None else str(city).strip()
    state = "" if state is None else str(state).strip()
    zip_code = "" if zip_code is None else str(zip_code).strip()

    locality = ", ".join(part for part in (city, state) if part)
    if zip_code:
        locality = f"{locality} {zip_code}".strip()

    return ", ".join(part for part in (street, locality) if part)


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance in miles between two coordinates."""
    lat1_r = radians(float(lat1))
    lon1_r = radians(float(lon1))
    lat2_r = radians(float(lat2))
    lon2_r = radians(float(lon2))

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (
        sin(dlat / 2.0) ** 2
        + cos(lat1_r)
        * cos(lat2_r)
        * sin(dlon / 2.0) ** 2
    )

    c = 2.0 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_MILES * c


def build_distance_matrix(
    route_data: Any,
    *,
    scale: int = 1000,
) -> list[list[int]]:
    """
    Build a symmetric integer distance matrix from route coordinates.

    route_data may be:
    - pandas DataFrame with lat + lng/lon
    - list of dictionaries
    - list of RoutePoint objects

    Values are scaled miles. OR-Tools only requires relative integer costs.
    """
    if isinstance(route_data, pd.DataFrame):
        records = route_data.to_dict("records")
    else:
        records = list(route_data)

    coordinates: list[tuple[float, float]] = []

    for record in records:
        lat = _value(record, "lat", "latitude")
        lng = _value(record, "lng", "lon", "longitude")

        if not _valid_coordinates(lat, lng):
            raise ValueError(
                "Every route stop must have valid latitude/longitude."
            )

        coordinates.append((float(lat), float(lng)))

    size = len(coordinates)
    matrix = [[0 for _ in range(size)] for _ in range(size)]

    for i in range(size):
        for j in range(i + 1, size):
            miles = haversine_distance(
                coordinates[i][0],
                coordinates[i][1],
                coordinates[j][0],
                coordinates[j][1],
            )
            cost = max(1, int(round(miles * scale)))
            matrix[i][j] = cost
            matrix[j][i] = cost

    return matrix


def _nearest_neighbor_route(
    distance_matrix: Sequence[Sequence[int]],
    start_index: int = 0,
) -> list[int]:
    """Dependency-free fallback route solver."""
    size = len(distance_matrix)

    if size == 0:
        return []

    if not 0 <= start_index < size:
        raise ValueError("start_index is outside the distance matrix.")

    remaining = set(range(size))
    remaining.remove(start_index)

    route = [start_index]
    current = start_index

    while remaining:
        next_node = min(
            remaining,
            key=lambda node: distance_matrix[current][node],
        )
        route.append(next_node)
        remaining.remove(next_node)
        current = next_node

    return route


def solve_route(
    distance_matrix: Sequence[Sequence[int]],
    start_index: int = 0,
    *,
    time_limit_seconds: int = 5,
) -> Optional[list[int]]:
    """
    Solve a single-vehicle route beginning at start_index.

    The returned route includes the start node once and does not append the
    depot again at the end. Dispatch code may still display "return to depot"
    and Google Maps links can explicitly use the depot as destination.

    If OR-Tools is unavailable, a nearest-neighbor fallback is used.
    """
    size = len(distance_matrix)

    if size == 0:
        return []

    if size == 1:
        return [0]

    if any(len(row) != size for row in distance_matrix):
        raise ValueError("distance_matrix must be square.")

    if pywrapcp is None or routing_enums_pb2 is None:
        return _nearest_neighbor_route(
            distance_matrix,
            start_index=start_index,
        )

    try:
        manager = pywrapcp.RoutingIndexManager(
            size,
            1,
            start_index,
        )
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(
            from_index: int,
            to_index: int,
        ) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(distance_matrix[from_node][to_node])

        transit_index = routing.RegisterTransitCallback(
            distance_callback
        )
        routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

        search = pywrapcp.DefaultRoutingSearchParameters()
        search.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search.time_limit.seconds = max(
            1,
            int(time_limit_seconds),
        )

        solution = routing.SolveWithParameters(search)

        if solution is None:
            return None

        route: list[int] = []
        index = routing.Start(0)

        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))

        return route

    except Exception:
        # A routing failure should not blank Dispatch. Fall back to a simple,
        # deterministic route rather than surfacing a UI-breaking exception.
        return _nearest_neighbor_route(
            distance_matrix,
            start_index=start_index,
        )


def split_routes(
    route: Any,
    max_stops: int = DEFAULT_MAX_STOPS,
) -> list[Any]:
    """
    Split a route into chunks.

    For a DataFrame, returns DataFrame chunks.
    For a list/tuple, returns list chunks.

    There is no limit on the number of resulting routes/crews.
    """
    max_stops = int(max_stops)
    if max_stops < 1:
        raise ValueError("max_stops must be at least 1.")

    if isinstance(route, pd.DataFrame):
        return [
            route.iloc[start:start + max_stops].reset_index(drop=True)
            for start in range(0, len(route), max_stops)
        ]

    values = list(route)
    return [
        values[start:start + max_stops]
        for start in range(0, len(values), max_stops)
    ]


def _navigation_location(stop: Any) -> str:
    lat = _value(stop, "lat", "latitude")
    lng = _value(stop, "lng", "lon", "longitude")

    if _valid_coordinates(lat, lng):
        return f"{float(lat):.7f},{float(lng):.7f}"

    return full_address(stop)


def build_navigation_url(
    destination: Any,
    origin: Any = None,
    *,
    travelmode: str = "driving",
) -> str:
    """
    Build a Google Maps directions link.

    If origin is omitted, Google Maps uses the phone/browser's current
    location. This is the preferred link for the crew's "Navigate" button.
    """
    destination_text = (
        destination
        if isinstance(destination, str)
        else _navigation_location(destination)
    )

    destination_text = str(destination_text or "").strip()
    if not destination_text:
        return ""

    params = {
        "api": "1",
        "destination": destination_text,
        "travelmode": travelmode,
    }

    if origin is not None:
        origin_text = (
            origin
            if isinstance(origin, str)
            else _navigation_location(origin)
        )
        origin_text = str(origin_text or "").strip()
        if origin_text:
            params["origin"] = origin_text

    return "https://www.google.com/maps/dir/?" + urlencode(params)


def build_google_maps_route_url(
    stops: Sequence[Any],
    *,
    origin: Any = None,
    destination: Any = None,
    return_to_origin: bool = False,
    travelmode: str = "driving",
) -> str:
    """
    Build one Google Maps multi-stop route URL.

    Google Maps imposes waypoint limits depending on platform/account. The CRM
    therefore uses this per crew route rather than trying to put an unlimited
    number of daily stops into one Maps link.
    """
    stop_list = list(stops)

    if not stop_list and destination is None:
        return ""

    locations = [
        _navigation_location(stop)
        for stop in stop_list
        if _navigation_location(stop)
    ]

    if destination is None:
        if not locations:
            return ""
        destination_text = locations[-1]
        waypoint_locations = locations[:-1]
    else:
        destination_text = (
            destination
            if isinstance(destination, str)
            else _navigation_location(destination)
        )
        waypoint_locations = locations

    params: dict[str, str] = {
        "api": "1",
        "destination": str(destination_text),
        "travelmode": travelmode,
    }

    if origin is not None:
        origin_text = (
            origin
            if isinstance(origin, str)
            else _navigation_location(origin)
        )
        if origin_text:
            params["origin"] = str(origin_text)

    if return_to_origin and origin is not None:
        if destination is None:
            waypoint_locations = locations
        destination_text = (
            origin
            if isinstance(origin, str)
            else _navigation_location(origin)
        )
        params["destination"] = str(destination_text)

    if waypoint_locations:
        params["waypoints"] = "|".join(waypoint_locations)

    return "https://www.google.com/maps/dir/?" + urlencode(
        params,
        safe="|,",
    )


def _normalize_records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []

    if isinstance(data, pd.DataFrame):
        return data.to_dict("records")

    if isinstance(data, Mapping):
        return [dict(data)]

    result: list[dict[str, Any]] = []

    for item in data:
        if isinstance(item, pd.Series):
            result.append(item.to_dict())
        elif isinstance(item, Mapping):
            result.append(dict(item))
        else:
            result.append(dict(vars(item)))

    return result


def _routeable_records(data: Any) -> list[dict[str, Any]]:
    """Keep records with usable coordinates; do not filter by Customer Type."""
    records = _normalize_records(data)
    result: list[dict[str, Any]] = []

    for record in records:
        lat = _value(record, "lat", "latitude")
        lng = _value(record, "lng", "lon", "longitude")

        if _valid_coordinates(lat, lng):
            normalized = dict(record)
            normalized["lat"] = float(lat)
            normalized["lng"] = float(lng)
            normalized["lon"] = float(lng)
            normalized["full_address"] = full_address(record)
            result.append(normalized)

    return result


def _depot_record(depot: Mapping[str, Any]) -> dict[str, Any]:
    lat = _value(depot, "lat", "latitude")
    lng = _value(depot, "lng", "lon", "longitude")

    if not _valid_coordinates(lat, lng):
        raise ValueError(
            "Depot must have valid lat/lng coordinates before routing."
        )

    return {
        **dict(depot),
        "id": _value(depot, "id", default=0),
        "name": _value(
            depot,
            "name",
            "customer_name",
            default="Depot",
        ),
        "customer_name": _value(
            depot,
            "customer_name",
            "name",
            default="Depot",
        ),
        "lat": float(lat),
        "lng": float(lng),
        "lon": float(lng),
        "full_address": full_address(depot)
        or str(_value(depot, "address", default="")),
        "_is_depot": True,
    }


def optimize_stops(
    stops: Any,
    depot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Optimize one group of stops from a depot.

    Customer Type is deliberately ignored.
    """
    routeable = _routeable_records(stops)

    if not routeable:
        return []

    depot_row = _depot_record(depot)
    combined = [depot_row, *routeable]

    matrix = build_distance_matrix(combined)
    order = solve_route(matrix, start_index=0)

    if not order:
        return routeable

    ordered = [
        combined[index]
        for index in order
        if index != 0
    ]

    # A solver should visit every node. If a fallback/edge case did not,
    # append any missing records deterministically.
    visited_ids = {id(record) for record in ordered}
    for record in routeable:
        if id(record) not in visited_ids:
            ordered.append(record)

    return ordered


def route_distance_miles(
    stops: Sequence[Any],
    *,
    depot: Any = None,
    return_to_depot: bool = True,
) -> float:
    """Calculate approximate straight-line route mileage."""
    route = list(stops)
    if not route:
        return 0.0

    points: list[Any] = []

    if depot is not None:
        points.append(depot)

    points.extend(route)

    if return_to_depot and depot is not None:
        points.append(depot)

    total = 0.0

    for first, second in zip(points, points[1:]):
        lat1 = _value(first, "lat", "latitude")
        lng1 = _value(first, "lng", "lon", "longitude")
        lat2 = _value(second, "lat", "latitude")
        lng2 = _value(second, "lng", "lon", "longitude")

        if not (
            _valid_coordinates(lat1, lng1)
            and _valid_coordinates(lat2, lng2)
        ):
            continue

        total += haversine_distance(
            float(lat1),
            float(lng1),
            float(lat2),
            float(lng2),
        )

    return total


def estimate_drive_minutes(
    distance_miles: float,
    *,
    average_mph: float = 30.0,
) -> float:
    """Fallback drive-time estimate when road duration is unavailable."""
    if average_mph <= 0:
        raise ValueError("average_mph must be greater than zero.")

    return (float(distance_miles) / float(average_mph)) * 60.0


def _service_minutes(stop: Any) -> float:
    for key in (
        "service_minutes",
        "estimated_service_minutes",
        "stop_minutes",
        "duration_minutes",
    ):
        value = _value(stop, key)
        if value is not None:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                pass

    return float(DEFAULT_SERVICE_MINUTES)


def summarize_route(
    stops: Sequence[Any],
    *,
    depot: Any = None,
    return_to_depot: bool = True,
) -> dict[str, Any]:
    route = list(stops)
    miles = route_distance_miles(
        route,
        depot=depot,
        return_to_depot=return_to_depot,
    )
    drive_minutes = estimate_drive_minutes(miles)
    service_minutes = sum(_service_minutes(stop) for stop in route)

    return {
        "stops": len(route),
        "distance_miles": miles,
        "drive_minutes": drive_minutes,
        "service_minutes": service_minutes,
        "total_minutes": drive_minutes + service_minutes,
        "google_maps": build_google_maps_route_url(
            route,
            origin=depot,
            return_to_origin=return_to_depot,
        ),
    }


def _decorate_route(
    stops: Sequence[dict[str, Any]],
    *,
    route_number: int,
    crew: Any = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for stop_number, stop in enumerate(stops, start=1):
        item = dict(stop)
        item["route_number"] = route_number
        item["stop_number"] = stop_number

        if crew is not None:
            if isinstance(crew, Mapping):
                item["crew_id"] = _value(crew, "id", "crew_id")
                item["crew_name"] = _value(
                    crew,
                    "crew_name",
                    "name",
                    default=f"Crew {route_number}",
                )
            else:
                item["crew_name"] = str(crew)

        item["navigation_url"] = build_navigation_url(item)
        result.append(item)

    return result


def build_route(
    stops: Any,
    depot: Optional[Mapping[str, Any]] = None,
    *,
    max_stops: Optional[int] = None,
    return_dataframe: bool = False,
) -> Any:
    """
    Build an optimized route.

    This is compatible with core.crm's historical build_route import.

    If max_stops is supplied, route_number/stop_number are assigned across
    chunks. The optimization itself does not inspect Customer Type.
    """
    if depot is None:
        records = _routeable_records(stops)

        if not records:
            return pd.DataFrame() if return_dataframe else []

        # Without a depot, preserve the first stop as the start point.
        first = records[0]
        remaining = records[1:]

        if remaining:
            pseudo_depot = {
                "id": "__route_start__",
                "name": "Route Start",
                "address": first.get("full_address", ""),
                "lat": first["lat"],
                "lng": first["lng"],
            }
            optimized_remaining = optimize_stops(
                remaining,
                pseudo_depot,
            )
            optimized = [first, *optimized_remaining]
        else:
            optimized = records
    else:
        optimized = optimize_stops(stops, depot)

    if max_stops is None:
        decorated = _decorate_route(
            optimized,
            route_number=1,
        )
    else:
        chunks = split_routes(optimized, max_stops=max_stops)
        decorated = []

        for route_number, chunk in enumerate(chunks, start=1):
            decorated.extend(
                _decorate_route(
                    chunk,
                    route_number=route_number,
                )
            )

    if return_dataframe:
        return pd.DataFrame(decorated)

    return decorated


def _balanced_chunks(
    stops: Sequence[dict[str, Any]],
    crew_count: int,
    max_stops: Optional[int] = None,
) -> list[list[dict[str, Any]]]:
    """
    Split stops into approximately balanced crew groups.

    Geographic optimization occurs again inside each crew group.
    """
    if crew_count < 1:
        raise ValueError("At least one crew is required.")

    stop_list = list(stops)

    if not stop_list:
        return [[] for _ in range(crew_count)]

    groups: list[list[dict[str, Any]]] = [
        [] for _ in range(crew_count)
    ]

    # Round-robin distribution from the globally optimized route keeps
    # workloads balanced. Each group is optimized again afterward.
    for index, stop in enumerate(stop_list):
        target = index % crew_count

        if (
            max_stops is not None
            and len(groups[target]) >= max_stops
        ):
            candidates = [
                i
                for i, group in enumerate(groups)
                if len(group) < max_stops
            ]
            if not candidates:
                # All configured crews are full. Add another virtual route;
                # the Dispatch UI can assign it to another/new crew.
                groups.append([])
                target = len(groups) - 1
            else:
                target = min(
                    candidates,
                    key=lambda i: len(groups[i]),
                )

        groups[target].append(stop)

    return groups


def build_dispatch_route(
    jobs: Any,
    depot: Mapping[str, Any],
    *,
    crews: Optional[Sequence[Any]] = None,
    max_stops_per_route: int = DEFAULT_MAX_STOPS,
) -> dict[str, Any]:
    """
    Build the complete dispatch plan.

    With no crews supplied, the optimized route is split by max stops.
    With crews supplied, jobs are distributed across crews and each crew's
    route is optimized independently.

    Scheduled date and Customer Type are not routing constraints. The caller
    decides which jobs are eligible; queued jobs from any scheduled date may
    therefore be passed directly into this function.
    """
    routeable = _routeable_records(jobs)

    if not routeable:
        return {
            "route": [],
            "routes": [],
            "crews": [],
            "manifest": [],
            "summary": {
                "stops": 0,
                "distance_miles": 0.0,
                "drive_minutes": 0.0,
                "service_minutes": 0.0,
                "total_minutes": 0.0,
                "google_maps": "",
            },
            "dataframe": pd.DataFrame(),
            "unroutable_count": len(_normalize_records(jobs)),
        }

    globally_optimized = optimize_stops(routeable, depot)

    crew_list = list(crews or [])
    route_results: list[dict[str, Any]] = []

    if crew_list:
        groups = _balanced_chunks(
            globally_optimized,
            crew_count=len(crew_list),
            max_stops=max_stops_per_route,
        )

        for route_index, group in enumerate(groups, start=1):
            if not group:
                continue

            crew = (
                crew_list[route_index - 1]
                if route_index - 1 < len(crew_list)
                else {
                    "id": None,
                    "crew_name": f"Unassigned Route {route_index}",
                }
            )

            optimized_group = optimize_stops(group, depot)
            decorated = _decorate_route(
                optimized_group,
                route_number=route_index,
                crew=crew,
            )
            summary = summarize_route(
                decorated,
                depot=depot,
            )

            route_results.append(
                {
                    "route_number": route_index,
                    "crew": crew,
                    "stops": decorated,
                    "manifest": decorated,
                    "summary": summary,
                    "google_maps": summary["google_maps"],
                }
            )
    else:
        groups = split_routes(
            globally_optimized,
            max_stops=max_stops_per_route,
        )

        for route_index, group in enumerate(groups, start=1):
            optimized_group = optimize_stops(group, depot)
            decorated = _decorate_route(
                optimized_group,
                route_number=route_index,
            )
            summary = summarize_route(
                decorated,
                depot=depot,
            )

            route_results.append(
                {
                    "route_number": route_index,
                    "crew": None,
                    "stops": decorated,
                    "manifest": decorated,
                    "summary": summary,
                    "google_maps": summary["google_maps"],
                }
            )

    all_stops = [
        stop
        for route in route_results
        for stop in route["stops"]
    ]

    total_summary = {
        "stops": len(all_stops),
        "distance_miles": sum(
            route["summary"]["distance_miles"]
            for route in route_results
        ),
        "drive_minutes": sum(
            route["summary"]["drive_minutes"]
            for route in route_results
        ),
        "service_minutes": sum(
            route["summary"]["service_minutes"]
            for route in route_results
        ),
        "total_minutes": sum(
            route["summary"]["total_minutes"]
            for route in route_results
        ),
        "google_maps": (
            route_results[0]["google_maps"]
            if len(route_results) == 1
            else ""
        ),
    }

    input_count = len(_normalize_records(jobs))

    return {
        "route": all_stops,
        "routes": route_results,
        "crews": route_results,
        "manifest": all_stops,
        "summary": total_summary,
        "dataframe": pd.DataFrame(all_stops),
        "unroutable_count": max(0, input_count - len(routeable)),
    }


def assign_routes_to_crews(
    jobs: Any,
    crews: Sequence[Any],
    depot: Mapping[str, Any],
    *,
    max_stops_per_route: int = DEFAULT_MAX_STOPS,
) -> list[dict[str, Any]]:
    """Convenience wrapper returning only the per-crew route records."""
    dispatch = build_dispatch_route(
        jobs,
        depot,
        crews=crews,
        max_stops_per_route=max_stops_per_route,
    )
    return dispatch["routes"]


def route_dataframe(route: Any) -> pd.DataFrame:
    """Convert a route/dispatch result into a DataFrame."""
    if isinstance(route, pd.DataFrame):
        return route.copy()

    if isinstance(route, Mapping):
        if "dataframe" in route:
            dataframe = route["dataframe"]
            if isinstance(dataframe, pd.DataFrame):
                return dataframe.copy()

        if "route" in route:
            return pd.DataFrame(route["route"])

    return pd.DataFrame(list(route or []))


def next_stop(route: Sequence[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the first unfinished stop."""
    for stop in route:
        status = str(
            _value(stop, "status", "dispatch_stop_status", default="")
        ).strip().casefold()

        if status not in {
            "completed",
            "cancelled",
            "canceled",
        }:
            return dict(stop)

    return None


def remaining_stops(
    route: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return all unfinished route stops."""
    remaining: list[dict[str, Any]] = []

    for stop in route:
        status = str(
            _value(stop, "status", "dispatch_stop_status", default="")
        ).strip().casefold()

        if status not in {
            "completed",
            "cancelled",
            "canceled",
        }:
            remaining.append(dict(stop))

    return remaining


__all__ = [
    "DEFAULT_MAX_STOPS",
    "DEFAULT_SERVICE_MINUTES",
    "RoutePoint",
    "assign_routes_to_crews",
    "build_dispatch_route",
    "build_distance_matrix",
    "build_google_maps_route_url",
    "build_navigation_url",
    "build_route",
    "estimate_drive_minutes",
    "full_address",
    "haversine_distance",
    "next_stop",
    "optimize_stops",
    "remaining_stops",
    "route_dataframe",
    "route_distance_miles",
    "solve_route",
    "split_routes",
    "summarize_route",
]
