import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import re

from urllib.parse import quote
from math import radians, sin, cos, sqrt, atan2

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Field Ops Dispatch", page_icon="🚚", layout="wide")
st.title("🚚 Field Operations Dispatch System (Stable)")

SERVICE_TIME_MIN = 30


# =========================================================
# SESSION STATE INIT
# =========================================================
if "ordered" not in st.session_state:
    st.session_state.ordered = None

if "completed" not in st.session_state:
    st.session_state.completed = set()


# =========================================================
# GOOGLE KEY
# =========================================================
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")


# =========================================================
# CLEAN ADDRESS
# =========================================================
def clean(addr):
    if addr is None:
        return ""
    addr = str(addr)
    addr = re.sub(r"\s+", " ", addr)
    return addr.strip()


# =========================================================
# GEOCODING
# =========================================================
def google_geocode(address):

    if not GOOGLE_API_KEY:
        return None

    try:
        url = (
            "https://maps.googleapis.com/maps/api/geocode/json"
            f"?address={quote(address)}&key={GOOGLE_API_KEY}"
        )

        r = requests.get(url, timeout=10).json()

        if r.get("status") == "OK" and r.get("results"):
            loc = r["results"][0]["geometry"]["location"]
            return {"lat": loc["lat"], "lon": loc["lng"]}

    except:
        pass

    return None


def osm_geocode(address):

    try:
        url = (
            "https://nominatim.openstreetmap.org/search"
            f"?q={quote(address + ', USA')}&format=json&limit=1"
        )

        headers = {"User-Agent": "field-ops"}

        r = requests.get(url, headers=headers, timeout=10).json()

        if r:
            return {
                "lat": float(r[0]["lat"]),
                "lon": float(r[0]["lon"])
            }

    except:
        pass

    return None


def geocode(address):

    address = clean(address)

    g = google_geocode(address)
    if g:
        return g

    return osm_geocode(address)


# =========================================================
# DISTANCE
# =========================================================
def haversine(a, b):

    R = 6371

    lat1 = radians(a["lat"])
    lon1 = radians(a["lon"])
    lat2 = radians(b["lat"])
    lon2 = radians(b["lon"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    x = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2

    return 2 * R * atan2(sqrt(x), sqrt(1-x))


# =========================================================
# ROUTE SOLVER
# =========================================================
def solve_route(locations, matrix):

    n = len(locations)

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cb(i, j):
        return int(matrix[
            manager.IndexToNode(i)
        ][
            manager.IndexToNode(j)
        ])

    transit = routing.RegisterTransitCallback(cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.FromSeconds(20)

    sol = routing.SolveWithParameters(params)

    if not sol:
        return None

    route = []
    total = 0

    index = routing.Start(0)

    while not routing.IsEnd(index):

        node = manager.IndexToNode(index)
        route.append(node)

        prev = index
        index = sol.Value(routing.NextVar(index))

        total += matrix[
            manager.IndexToNode(prev)
        ][
            manager.IndexToNode(index)
        ]

    route.append(manager.IndexToNode(index))

    return route, total


# =========================================================
# NAV LINK
# =========================================================
def nav(address):
    return "https://www.google.com/maps/search/?api=1&query=" + quote(address)


# =========================================================
# UPLOAD
# =========================================================
uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])

df = None

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.success(f"Loaded {len(df)} jobs")
    st.dataframe(df.head())


# =========================================================
# MAIN APP
# =========================================================
if df is not None:

    col = st.selectbox("Address Column", df.columns)
    depot = st.text_input("Depot Address (optional)")

    if st.button("🚀 Generate Dispatch"):

        locations = []
        failed = []

        st.info("Geocoding...")

        # DEPOT
        if depot:
            g = geocode(depot)
            if g:
                locations.append({"address": depot, **g})

        # STOPS
        for _, r in df.iterrows():

            addr = clean(r[col])
            g = geocode(addr)

            if g:
                locations.append({"address": addr, **g})
            else:
                failed.append(addr)

            time.sleep(0.2)

        st.write("Valid:", len(locations))
        st.write("Failed:", len(failed))

        if len(locations) < 2:
            st.error("Not enough valid locations")
            st.stop()

        # =====================================================
        # MATRIX
        # =====================================================
        n = len(locations)
        matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = haversine(locations[i], locations[j]) * 2

        # =====================================================
        # ROUTE
        # =====================================================
        result = solve_route(locations, matrix)

        if not result:
            st.error("Routing failed")
            st.stop()

        route, total = result
        ordered = [locations[i] for i in route]

        # =====================================================
        # SAVE TO SESSION STATE (CRITICAL FIX)
        # =====================================================
        st.session_state.ordered = ordered
        st.session_state.completed = set()

        # =====================================================
        # FAILED LIST
        # =====================================================
        if failed:
            st.subheader("⚠️ Failed Addresses")
            st.dataframe(pd.DataFrame(failed, columns=["Address"]))

        # =====================================================
        # DISPATCH BOARD
        # =====================================================
        st.subheader("🚚 Dispatch Board")

        board = []

        for i, stop in enumerate(ordered):

            board.append({
                "Stop": i + 1,
                "Address": stop["address"],
                "Navigate": nav(stop["address"]),
                "Completed": False
            })

        df_board = pd.DataFrame(board)

        st.dataframe(df_board, use_container_width=True)

        st.download_button(
            "📥 Download Dispatch CSV",
            df_board.to_csv(index=False),
            "dispatch.csv",
            "text/csv"
        )


# =========================================================
# PERSISTED VIEW (IMPORTANT)
# =========================================================
if st.session_state.ordered:

    ordered = st.session_state.ordered

    st.subheader("📍 Live Field View")

    remaining = []

    for i, stop in enumerate(ordered):

        done = i in st.session_state.completed

        if done:
            continue

        remaining.append((i, stop))

        st.checkbox(
            f"Stop {i+1}: {stop['address']}",
            key=f"chk_{i}",
            value=False
        )

    # sync checkbox state
    for i, stop in enumerate(ordered):

        if st.session_state.get(f"chk_{i}", False):
            st.session_state.completed.add(i)
        else:
            if i in st.session_state.completed:
                st.session_state.completed.remove(i)

    # NEXT STOP
    if remaining:

        idx, nxt = remaining[0]

        st.subheader("➡️ Next Stop")

        st.markdown(f"**{nxt['address']}**")
        st.markdown(f"[Navigate]({nav(nxt['address'])})")

    else:
        st.success("🎉 All stops completed!")
