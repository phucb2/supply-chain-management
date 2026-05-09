"""
Supply Chain Demo — guided walkthrough of the redesigned order lifecycle with ML predictions.
Entry point for the Streamlit multi-page app.
"""

import asyncio
from datetime import date
import os
import time

import asyncpg
import streamlit as st

import api_client as api
from sidebar_ui import (
    inject_sidebar_styles,
    sidebar_api_status,
    sidebar_brand,
    sidebar_connection_hint,
    sidebar_section_actions,
    sidebar_section_backend,
)

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://supplychain:supplychain_secret@postgresql:5432/supplychain",
)
API_BASE_DEFAULT = os.getenv("API_BASE_URL", "http://api:8000")

st.set_page_config(page_title="Supply Chain Demo", page_icon=":package:", layout="wide")
inject_sidebar_styles()


def _run_query(sql, *args):
    async def _q():
        conn = await asyncpg.connect(DB_DSN)
        rows = await conn.fetch(sql, *args)
        await conn.close()
        return rows

    return asyncio.new_event_loop().run_until_complete(_q())


_DEMO_INIT = {
    "step": 1,
    "order_id": None,
    "order": None,
    "order_request": None,
    "shipment_id": None,
    "shipment": None,
    "prediction": None,
    "tracking": [],
    "actual_eta": None,
    "delivery_index": 0,
}
if "demo" not in st.session_state:
    st.session_state.demo = dict(_DEMO_INIT)
if "api_base" not in st.session_state:
    st.session_state.api_base = API_BASE_DEFAULT

with st.sidebar:
    sidebar_brand(page_title="Order lifecycle demo", tag="Supply chain · console")
    sidebar_section_backend()
    sidebar_connection_hint()
    st.text_input("API base URL", key="api_base", placeholder="http://localhost:8000")
    base = st.session_state.api_base
    health_status, _ = api.health_check(base)
    sidebar_api_status(connected=health_status == 200)
    sidebar_section_actions()
    if st.button("Reset demo", use_container_width=True, help="Clear order, shipment, and step state"):
        st.session_state.demo = dict(_DEMO_INIT)
        st.rerun()

demo = st.session_state.demo
ORDER_PIPELINE = ["pending", "confirmed", "allocated", "in_transit", "delivered"]
DELIVERY_STEPS = [("picked_up", "Warehouse Floor 3"), ("in_transit", "Highway I-95"), ("out_for_delivery", "Local Depot"), ("delivered", "Front Door")]

st.title(":package: Supply Chain Demo")
st.caption("Guided walkthrough: Order → Pipeline → Shipment + ETA → Delivery → ML Feedback")

if demo["step"] == 1:
    st.subheader("Step 1 — Create Order")
    source = st.selectbox("Source", ["shopify", "amazon", "manual"])
    num_items = st.number_input("Items", 1, 5, 2)
    if st.button(":rocket: Create Order", type="primary", use_container_width=True):
        ts = int(time.time())
        payload = {
            "external_order_id": f"DEMO-{ts}",
            "source": source,
            "customer_category": "b2c",
            "customer_name": "Demo User",
            "customer_email": "demo@example.com",
            "shipping_address": "123 Demo Street, Test City",
            "req_delivery_date": date.today().isoformat(),
            "destination": "Test City",
            "items": [
                {
                    "sku": f"DEMO-{i + 1}",
                    "product_name": f"Demo Product {i + 1}",
                    "quantity": i + 1,
                    "unit_price": round(10 + i * 5.5, 2),
                    "weight_per_unit_kg": round(0.5 + i * 0.2, 2),
                }
                for i in range(int(num_items))
            ],
        }
        resp_status, order = api.create_order(base, payload)
        if resp_status == 201:
            demo["order_id"] = order["sale_order_id"]
            demo["order"] = order
            demo["order_request"] = payload
            demo["step"] = 2
            st.rerun()
        else:
            st.error(f"Order creation failed ({resp_status})")

if demo["step"] >= 2:
    st.subheader("Step 2 — Watch Pipeline")
    code, fresh = api.get_order(base, demo["order_id"])
    if code == 200 and isinstance(fresh, dict):
        demo["order"] = fresh
        current_status = fresh["status"]
        idx = ORDER_PIPELINE.index(current_status) if current_status in ORDER_PIPELINE else -1
        st.progress((idx + 1) / len(ORDER_PIPELINE) if idx >= 0 else 0.0, text=f"Current status: **{current_status}**")
        if current_status in ("in_transit", "delivered"):
            demo["step"] = max(demo["step"], 3)
        elif current_status in ("exception", "cancelled"):
            st.error(f"Pipeline ended with: **{current_status}**")
        elif demo["step"] == 2:
            time.sleep(2)
            st.rerun()

if demo["step"] >= 3:
    st.subheader("Step 3 — Shipment + ETA Prediction")
    if not demo["shipment_id"]:
        demo["shipment_id"] = demo["order"].get("delivery_order_id")
    if demo["shipment_id"]:
        scode, ship = api.get_shipment(base, demo["shipment_id"])
        if scode == 200:
            demo["shipment"] = ship
        c1, c2, c3 = st.columns(3)
        c1.metric("Delivery Order ID", demo["shipment_id"][:12] + "...")
        c2.metric("Status", (demo["shipment"] or {}).get("status", "---"))
        c3.metric("Request ID", (demo["shipment"] or {}).get("request_id", "---")[:12] + "..." if (demo["shipment"] or {}).get("request_id") else "---")
        if not demo["prediction"]:
            preds = _run_query(
                "SELECT predicted_eta_hours, model_version, input_features, predicted_at "
                "FROM predictions WHERE delivery_order_id = $1 "
                "ORDER BY predicted_at DESC LIMIT 1",
                demo["shipment_id"],
            )
            if preds:
                pred = preds[0]
                demo["prediction"] = {
                    "predicted_eta_hours": float(pred["predicted_eta_hours"]),
                    "model_version": pred["model_version"],
                    "input_features": pred["input_features"],
                    "predicted_at": str(pred["predicted_at"])[:19],
                }
            else:
                st.info("Waiting for ML prediction...")
        if demo["prediction"] and st.button(":truck: Continue to Delivery Simulation", type="primary", use_container_width=True):
            demo["step"] = max(demo["step"], 4)
            st.rerun()

if demo["step"] >= 4 and demo["shipment_id"]:
    st.subheader("Step 4 — Simulate Delivery")
    delivery_idx = demo["delivery_index"]
    if delivery_idx < len(DELIVERY_STEPS):
        next_status, next_loc = DELIVERY_STEPS[delivery_idx]
        if st.button(f":arrow_right: Push **{next_status}** @ {next_loc}", type="primary", use_container_width=True):
            code, _ = api.push_shipment_status(base, demo["shipment_id"], next_status, next_loc)
            if code == 202:
                demo["delivery_index"] += 1
                tc, tracking = api.get_tracking(base, demo["shipment_id"])
                if tc == 200 and isinstance(tracking, list):
                    demo["tracking"] = tracking
                if demo["delivery_index"] >= len(DELIVERY_STEPS):
                    demo["step"] = 5
                st.rerun()

if demo["step"] >= 5:
    st.subheader("Step 5 — ML Feedback Loop")
    if not demo["actual_eta"]:
        actuals = _run_query(
            "SELECT actual_eta_hours, absolute_error, recorded_at "
            "FROM prediction_actuals WHERE sale_order_id = $1 "
            "ORDER BY recorded_at DESC LIMIT 1",
            demo["order_id"],
        )
        if actuals:
            act = actuals[0]
            demo["actual_eta"] = {
                "actual_eta_hours": float(act["actual_eta_hours"]),
                "absolute_error": float(act["absolute_error"]),
                "recorded_at": str(act["recorded_at"])[:19],
            }
    if demo["actual_eta"] and demo["prediction"]:
        st.success("Demo complete. Prediction accuracy is now recorded.")
        st.json({"prediction": demo["prediction"], "actual": demo["actual_eta"]})

st.divider()
with st.expander("System Stats"):
    code_o, orders_list = api.list_orders(base, limit=100)
    if code_o == 200 and isinstance(orders_list, list):
        by_status: dict[str, int] = {}
        for item in orders_list:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Orders", len(orders_list))
        c2.metric("In Transit", by_status.get("in_transit", 0))
        c3.metric("Delivered", by_status.get("delivered", 0))
        c4.metric("Exceptions", by_status.get("exception", 0))
