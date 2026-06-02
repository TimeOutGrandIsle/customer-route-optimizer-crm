import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import json
import os
import re

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from urllib.parse import quote
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, sqrt, atan2


# =========================================================
# CONFIG
# =========================================================
st.set_page_config(
    page_title="Production Route Optimizer",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 Production Lawn Route Optimizer")
st.markdown(
    """
Free production-grade routing with:
- Stable geocoding
- Address cleanup
- Retry handling
- Geocode caching
- Route optimization
- Google Maps export
"""
)

SERVICE_TIME_MIN = 30
CACHE_FILE = "geocode_cache.json"


# =========================================================
# CACHE
# =========================================================
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f:
            GEO_CACHE = json.load(f)
    except:
        GEO_CACHE = {}
else:
    GEO_CACHE = {}


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(GEO_CACHE, f)


# =========================================================
# ADDRESS CLEANUP
# =========================================================
def clean_address(addr):

    if pd.isna(addr):
        return ""

    addr = str(addr).strip()

    # Remove extra spaces
    addr = re.sub(r"\s+", " ", addr)

    # Replace line breaks
    addr = addr.replace("\n", " ")

    # Common cleanup
    addr = addr.replace(" ,", ",")
    addr = addr.replace(" , ", ", ")

    return addr


# =========================================================
# GEOCODER
# =========================================================
def safe_geocode(geolocator, address, retries=3):

    address = clean_address(address)

    if not address:
        return None

    # CACHE HIT
    if address in GEO_CACHE:
        return GEO_CACHE[address]

    for attempt in range(retries):

        try:
            loc = geolocator.geocode(
                address,
                timeout=15,
                exactly_one=True
            )

            if loc:

                result = {
                    "lat": loc.latitude,
                    "lon": loc.longitude
                }

                GEO_CACHE[address] = result
                save_cache()

                return result

        except (GeocoderTimedOut, GeocoderUnavailable):
            time.sleep(2)

        except Exception:
            time.sleep(1)

    return None


# =========================================================
# DISTANCE FALLBACK
# =========================================================
def haversine_distance(loc1, loc2):

    R = 6371.0

    lat1 = radians(loc1["lat"])
    lon1 = radians(loc1["lon"])

    lat2 = radians(loc2["lat"])
    lon2 = radians(loc2["lon"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


# =========================================================
# ROUTING
# =========================================================
def solve_route(locations, time_matrix):

    n = len(locations)

    if n < 2:
        return None

    depot = 0

    manager = pywrapcp.RoutingIndexManager(n, 1, depot)

    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):

        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        return int(time_matrix[from_node][to_node])

    transit_callback_index = routing.RegisterTransitCallback(
        distance_callback
    )

    routing.SetArcCostEvaluatorOfAllVehicles(
        transit_callback_index
    )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()

    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    search_parameters.time_limit.FromSeconds(10)

    try:
        solution = routing.SolveWithParameters(search_parameters)

    except Exception:
        return None

    if not solution:
        return None

    index = routing.Start(0)

    route = []
    total_time = 0

    while not routing.IsEnd(index):

        node = manager.IndexToNode(index)

        route.append(node)

        previous_index = index

        index = solution.Value(routing.NextVar(index))

        total_time += time_matrix[
            manager.IndexToNode(previous_index)
        ][
            manager.IndexToNode(index)
        ]

    route.append(manager.IndexToNode(index))

    return {
        "route": route,
        "total_time": total_time
    }


# =========================================================
# GOOGLE MAPS URL
# =========================================================
def create_google_maps_url(addresses):

    if len(addresses) < 2:
        return None

    origin = quote(addresses[0])
    destination = quote(addresses[-1])

    waypoints = "|".join(
        quote(a) for a in addresses[1:-1]
    )

    url = (
        f"https://www.google.com/maps/dir/"
        f"?api=1"
        f"&origin={origin}"
        f"&destination={destination}"
    )

    if waypoints:
        url += f"&waypoints={waypoints}"

    url += "&travelmode=driving"

    return url


# =========================================================
# MAP
# =========================================================
def create_map(route_locs):

    m = folium.Map(
        location=[
            route_locs[0]["lat"],
            route_locs[0]["lon"]
        ],
        zoom_start=11
    )

    for i, loc in enumerate(route_locs):

        color = "red" if i == 0 else "blue"

        folium.Marker(
            [loc["lat"], loc["lon"]],
            popup=f"{i+1}. {loc['address']}",
            icon=folium.Icon(color=color)
        ).add_to(m)

    points = [
        [loc["lat"], loc["lon"]]
        for loc in route_locs
    ]

    folium.PolyLine(
        points,
        weight=4
    ).add_to(m)

    return m


# =========================================================
# UI
# =========================================================
uploaded_file = st.file_uploader(
    "Upload Excel File",
    type=["xlsx", "xls"]
)

if uploaded_file:

    try:
        df = pd.read_excel(uploaded_file)

    except Exception as e:
        st.error(f"Failed to read Excel file: {e}")
        st.stop()

    st.success(f"Loaded {len(df)} rows")

    st.dataframe(df.head())

    address_col = st.selectbox(
        "Select Address Column",
        df.columns
    )

    depot_address = st.text_input(
        "Depot Address (optional)"
    )

    run = st.button("🚀 Generate Optimized Route")

    if run:

        geolocator = Nominatim(
            user_agent="production_route_optimizer"
        )

        locations = []
        failed = []

        progress = st.progress(0)

        st.info("Geocoding addresses...")

        # =================================================
        # DEPOT
        # =================================================
        if depot_address.strip():

            depot_geo = safe_geocode(
                geolocator,
                depot_address
            )

            if depot_geo:

                locations.append({
                    "address": depot_address,
                    "lat": depot_geo["lat"],
                    "lon": depot_geo["lon"],
                    "is_depot": True
                })

            else:
                failed.append(depot_address)

        # =================================================
        # CUSTOMERS
        # =================================================
        total_rows = len(df)

        for idx, row in enumerate(df.iterrows()):

            _, row_data = row

            addr = clean_address(
                row_data[address_col]
            )

            geo = safe_geocode(
                geolocator,
                addr
            )

            if geo:

                locations.append({
                    "address": addr,
                    "lat": geo["lat"],
                    "lon": geo["lon"],
                    "is_depot": False
                })

            else:
                failed.append(addr)

            progress.progress(
                int((idx + 1) / total_rows * 100)
            )

            # Respect free Nominatim rate limits
            time.sleep(1)

        # =================================================
        # RESULTS
        # =================================================
        st.success(
            f"Successfully geocoded {len(locations)} locations"
        )

        if failed:

            st.warning(
                f"{len(failed)} addresses failed geocoding"
            )

            failed_df = pd.DataFrame(
                failed,
                columns=["Failed Address"]
            )

            with st.expander("View Failed Addresses"):
                st.dataframe(failed_df)

            st.download_button(
                "Download Failed Addresses CSV",
                failed_df.to_csv(index=False),
                "failed_addresses.csv",
                "text/csv"
            )

        if len(locations) < 2:
            st.error(
                "Need at least 2 valid geocoded locations."
            )
            st.stop()

        # =================================================
        # BUILD MATRIX
        # =================================================
        st.info("Building travel matrix...")

        n = len(locations)

        time_matrix = np.zeros(
            (n, n),
            dtype=int
        )

        for i in range(n):

            for j in range(n):

                if i == j:
                    continue

                try:

                    url = (
                        f"http://router.project-osrm.org/"
                        f"route/v1/driving/"
                        f"{locations[i]['lon']},"
                        f"{locations[i]['lat']};"
                        f"{locations[j]['lon']},"
                        f"{locations[j]['lat']}"
                        f"?overview=false"
                    )

                    response = requests.get(
                        url,
                        timeout=8
                    ).json()

                    duration_min = (
                        response["routes"][0]["duration"]
                        / 60
                    )

                    time_matrix[i][j] = (
                        int(duration_min)
                        + SERVICE_TIME_MIN
                    )

                except Exception:

                    dist = haversine_distance(
                        locations[i],
                        locations[j]
                    )

                    time_matrix[i][j] = (
                        int(dist * 2)
                        + SERVICE_TIME_MIN
                    )

        # =================================================
        # SOLVE
        # =================================================
        st.info("Optimizing route...")

        solution = solve_route(
            locations,
            time_matrix
        )

        # =================================================
        # FALLBACK
        # =================================================
        if not solution:

            st.warning(
                "Optimization failed. Using fallback route."
            )

            route = list(range(len(locations)))
            total_time = 0

        else:

            route = solution["route"]
            total_time = solution["total_time"]

        # =================================================
        # OUTPUT
        # =================================================
        route_df = pd.DataFrame([
            {
                "Stop": i + 1,
                "Address": locations[idx]["address"]
            }
            for i, idx in enumerate(route)
        ])

        st.subheader("📍 Optimized Route")

        st.dataframe(
            route_df,
            use_container_width=True
        )

        st.metric(
            "Estimated Total Minutes",
            total_time
        )

        # =================================================
        # GOOGLE MAPS
        # =================================================
        addresses = [
            locations[i]["address"]
            for i in route
        ]

        maps_url = create_google_maps_url(
            addresses
        )

        st.subheader("🚗 Google Maps Export")

        if maps_url:

            st.markdown(
                f"[Open Route in Google Maps]({maps_url})"
            )

            st.code(maps_url)

        else:

            st.warning(
                "Google Maps link could not be generated."
            )

        # =================================================
        # MAP
        # =================================================
        st.subheader("🗺️ Route Map")

        st_folium(
            create_map(
                [locations[i] for i in route]
            ),
            width=1200,
            height=700
        )

        # =================================================
        # DOWNLOAD
        # =================================================
        st.download_button(
            "📥 Download Route CSV",
            route_df.to_csv(index=False),
            "optimized_route.csv",
            "text/csv"
        )
