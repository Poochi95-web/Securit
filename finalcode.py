import streamlit as st
import sqlite3
from datetime import datetime, date
import geocoder
import pandas as pd

DB_PATH = "geolocation.db"

# ------------------ CONFIG ------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "12345"

# ------------------ DB helpers ------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        latitude REAL,
        longitude REAL,
        address TEXT,
        checkin_time TEXT,
        checkin_remark TEXT,
        checkin_latitude REAL,
        checkin_longitude REAL,
        checkout_time TEXT,
        checkout_remark TEXT,
        checkout_latitude REAL,
        checkout_longitude REAL
    )
    """)
    conn.commit()
    conn.close()

def migrate_columns():
    conn = get_conn()
    c = conn.cursor()
    c.execute("PRAGMA table_info(attendance)")
    cols = [r[1] for r in c.fetchall()]

    new_cols = {
        "latitude": "REAL",
        "longitude": "REAL",
        "checkin_remark": "TEXT",
        "checkout_remark": "TEXT",
        "checkin_latitude": "REAL",
        "checkin_longitude": "REAL",
        "checkout_latitude": "REAL",
        "checkout_longitude": "REAL",
    }
    for col, col_type in new_cols.items():
        if col not in cols:
            c.execute(f"ALTER TABLE attendance ADD COLUMN {col} {col_type}")
    conn.commit()

    # Migrate data: copy checkin_latitude/longitude into latitude/longitude where latitude/longitude are NULL
    c.execute("""
        UPDATE attendance
        SET latitude = checkin_latitude,
            longitude = checkin_longitude
        WHERE (latitude IS NULL OR longitude IS NULL)
          AND checkin_latitude IS NOT NULL
          AND checkin_longitude IS NOT NULL
    """)
    conn.commit()
    conn.close()

# ------------------ Location helper ------------------
def get_ip_location():
    try:
        g = geocoder.ip("me")
        latlng = g.latlng
        lat, lon = (float(latlng[0]), float(latlng[1])) if latlng else (None, None)
        address = ", ".join(filter(None, [
            getattr(g, "city", None),
            getattr(g, "state", None),
            getattr(g, "country", None)
        ])) or "Unknown"
        return lat, lon, address
    except Exception:
        return None, None, "Unknown"

# Prepare DataFrame for st.map() with renamed lat/lon columns and dropping invalids
def prepare_map_df(df, lat_col, lon_col):
    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df_clean = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)
    return df_clean.rename(columns={lat_col: "lat", lon_col: "lon"})

# ------------------ APP SETUP ------------------
st.set_page_config(page_title="Geolocation Attendance", layout="wide")
st.title("📍 Geolocation Check-In / Check-Out (with Remarks)")

init_db()
migrate_columns()

view_mode = st.sidebar.selectbox("Mode", ["User", "Admin"])
username = st.text_input("Enter your name", max_chars=64) if view_mode == "User" else None

if view_mode == "User":
    st.subheader("🟢 Check-In")
    checkin_remark = st.text_area("Remark for Check-In", placeholder="E.g. On-site visit / Starting shift")
    if st.button("Check-In"):
        if not username.strip():
            st.error("Please enter your name.")
        else:
            lat, lon, address = get_ip_location()
            checkin_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_conn()
            c = conn.cursor()
            c.execute("""
                INSERT INTO attendance 
                (username, latitude, longitude, checkin_latitude, checkin_longitude, address, checkin_time, checkin_remark, checkout_time, checkout_remark, checkout_latitude, checkout_longitude) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (username, lat, lon, lat, lon, address, checkin_time, checkin_remark, None, None, None, None))
            conn.commit()
            conn.close()
            st.success(f"✅ Checked in at {checkin_time}")
            st.write(f"🏠 {address}")

    st.subheader("🔴 Check-Out")
    checkout_remark = st.text_area("Remark for Check-Out", placeholder="E.g. Finished tasks / Leaving")
    if st.button("Check-Out"):
        if not username.strip():
            st.error("Please enter your name.")
        else:
            conn = get_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM attendance WHERE username=? AND checkout_time IS NULL ORDER BY id DESC LIMIT 1", (username,))
            row = c.fetchone()
            if row:
                record_id = row[0]
                lat, lon, _ = get_ip_location()
                checkout_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""
                    UPDATE attendance 
                    SET checkout_time=?, checkout_remark=?, checkout_latitude=?, checkout_longitude=? 
                    WHERE id=?
                    """,
                    (checkout_time, checkout_remark, lat, lon, record_id))
                conn.commit()
                conn.close()
                st.success(f"✅ Checked out at {checkout_time}")
            else:
                st.warning("⚠ No active check-in found.")

    if st.checkbox("Show My Attendance History"):
        if username.strip():
            conn = get_conn()
            df = pd.read_sql_query("SELECT * FROM attendance WHERE username=? ORDER BY id DESC", conn, params=(username,))
            conn.close()
            if not df.empty:
                st.dataframe(df)

                st.write("🟢 Check-In Locations")
                checkin_map_df = prepare_map_df(df, "checkin_latitude", "checkin_longitude")
                if not checkin_map_df.empty:
                    st.map(checkin_map_df)
                else:
                    st.info("No valid check-in location data to show.")

                st.write("🔴 Check-Out Locations")
                checkout_map_df = prepare_map_df(df, "checkout_latitude", "checkout_longitude")
                if not checkout_map_df.empty:
                    st.map(checkout_map_df)
                else:
                    st.info("No valid check-out location data to show.")
            else:
                st.info("No records found.")
        else:
            st.info("Enter your name to view history.")

elif view_mode == "Admin":
    if not st.session_state.get("admin_logged_in", False):
        st.subheader("🔐 Admin Login")
        admin_user = st.text_input("Username", key="admin_user")
        admin_pass = st.text_input("Password", type="password", key="admin_pass")

        if st.button("Login as Admin"):
            if admin_user == ADMIN_USERNAME and admin_pass == ADMIN_PASSWORD:
                st.session_state["admin_logged_in"] = True
                st.success("✅ Logged in as Admin")
                st.experimental_rerun()
            else:
                st.error("Invalid username or password.")
    else:
        st.success("✅ Logged in as Admin")

        if st.button("🚪 Logout"):
            st.session_state["admin_logged_in"] = False
            st.experimental_rerun()

        conn = get_conn()
        all_users = [r[0] for r in conn.execute("SELECT DISTINCT username FROM attendance").fetchall() if r[0]]
        selected_user = st.selectbox("Filter by user", ["All"] + all_users)
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From date", value=date.today().replace(day=1))
        with col2:
            date_to = st.date_input("To date", value=date.today())

        query = "SELECT * FROM attendance WHERE 1=1"
        params = []
        if selected_user != "All":
            query += " AND username=?"
            params.append(selected_user)
        start_str = date_from.strftime("%Y-%m-%d")
        end_str = date_to.strftime("%Y-%m-%d")
        query += " AND substr(checkin_time,1,10) BETWEEN ? AND ?"
        params.extend([start_str, end_str])
        query += " ORDER BY id DESC"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        st.write(f"Showing {len(df)} records")
        st.dataframe(df)

        if not df.empty:
            st.write("🟢 Check-In Locations")
            checkin_map_df = prepare_map_df(df, "checkin_latitude", "checkin_longitude")
            if not checkin_map_df.empty:
                st.map(checkin_map_df)
            else:
                st.info("No valid check-in location data to show.")

            st.write("🔴 Check-Out Locations")
            checkout_map_df = prepare_map_df(df, "checkout_latitude", "checkout_longitude")
            if not checkout_map_df.empty:
                st.map(checkout_map_df)
            else:
                st.info("No valid check-out location data to show.")

            # Now do NOT drop latitude/longitude columns from CSV export
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ Download CSV", data=csv, file_name="attendance_export.csv", mime="text/csv")
