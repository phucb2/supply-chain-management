"""
Supply Chain Demo — guided walkthrough of the full order lifecycle with ML predictions.
Entry point for the Streamlit multi-page app.
"""

import asyncio
import os
import time
import uuid

import asyncpg
import streamlit as st

import api_client as api

# ── Config ─────────────────────────────────────────────────────────────────────

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://supplychain:supplychain_secret@postgresql:5432/supplychain",
)
API_BASE_DEFAULT = os.getenv("API_BASE_URL", "http://api:8000")

st.set_page_config(
    page_title="Supply Chain Demo",
    page_icon=":package:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB helpers ─────────────────────────────────────────────────────────────────


def _run_query(sql, *args):
    async def _q():
        conn = await asyncpg.connect(DB_DSN)
        rows = await conn.fetch(sql, *args)
        await conn.close()
        return rows

    return asyncio.new_event_loop().run_until_complete(_q())


# ── Demo state ─────────────────────────────────────────────────────────────────

_DEMO_INIT = {
    "step": 1,
    "order_id": None,
    "order": None,
    "shipment_id": None,
    "shipment": None,
    "prediction": None,
    "tracking": [],
    "actual_eta": None,
    "delivery_index": 0,
}

if "demo" not in st.session_state:
    st.session_state.demo = dict(_DEMO_INIT)

# ── Sidebar ────────────────────────────────────────────────────────────────────

if "api_base" not in st.session_state:
    st.session_state.api_base = API_BASE_DEFAULT

with st.sidebar:
    st.session_state.api_base = st.text_input(
        "API Base URL", value=st.session_state.api_base
    )
    base = st.session_state.api_base

    code, _ = api.health_check(base)
    if code == 200:
        st.success("API connected")
    else:
        st.error("API unreachable")

    st.divider()
    if st.button(":arrows_counterclockwise: Reset Demo", use_container_width=True):
        st.session_state.demo = dict(_DEMO_INIT)
        st.rerun()

demo = st.session_state.demo

# ── Constants ──────────────────────────────────────────────────────────────────

ORDER_PIPELINE = ["received", "validated", "erp_synced", "allocated", "shipped"]
DELIVERY_STEPS = [
    ("picked_up", "Warehouse Floor 3"),
    ("in_transit", "Highway I-95"),
    ("out_for_delivery", "Local Depot"),
    ("delivered", "Front Door"),
]
STEP_LABELS = [
    "Create Order",
    "Watch Pipeline",
    "Shipment + ETA",
    "Simulate Delivery",
    "ML Feedback",
]


# ── Stepper ────────────────────────────────────────────────────────────────────


def _render_stepper(current_step: int):
    cols = st.columns(len(STEP_LABELS))
    for i, (col, label) in enumerate(zip(cols, STEP_LABELS), 1):
        if i < current_step:
            col.markdown(f"**:white_check_mark: {i}. {label}**")
        elif i == current_step:
            col.markdown(f"**:arrow_forward: {i}. {label}**")
        else:
            col.markdown(f":white_circle: {i}. {label}")


# ── Pipeline timeline helper ──────────────────────────────────────────────────


def _render_status_timeline(statuses: list[str], current: str):
    cols = st.columns(len(statuses))
    current_idx = statuses.index(current) if current in statuses else -1
    for i, (col, status) in enumerate(zip(cols, statuses)):
        if i < current_idx:
            col.markdown(f":green_circle: ~~{status}~~")
        elif i == current_idx:
            col.markdown(f":large_green_circle: **{status}**")
        else:
            col.markdown(f":white_circle: {status}")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.title(":package: Supply Chain Demo")
st.caption(
    "Guided walkthrough: Order → Pipeline → Shipment + ETA → Delivery → ML Feedback"
)

_render_stepper(demo["step"])
st.divider()


# ── Step 1: Create Order ──────────────────────────────────────────────────────

if demo["step"] > 1:
    with st.expander(
        f":white_check_mark: Step 1 — Order `{demo['order_id']}` "
        f"({demo['order'].get('channel', '')}, {demo['order'].get('customer_name', '')})"
    ):
        st.json(demo["order"])

elif demo["step"] == 1:
    st.subheader("Step 1 — Create Order")

    col_quick, col_form = st.columns([1, 1], gap="large")

    with col_quick:
        st.markdown("**Quick Create** — one click with sensible defaults")
        q1, q2 = st.columns(2)
        channel = q1.selectbox("Channel", ["shopify", "amazon", "manual"])
        num_items = q2.number_input("Items", 1, 5, 2)

        if st.button(
            ":rocket: Create Order", type="primary", use_container_width=True
        ):
            ts = int(time.time())
            items = [
                {
                    "sku": f"DEMO-{i + 1}",
                    "product_name": f"Demo Product {i + 1}",
                    "quantity": i + 1,
                    "unit_price": round(10 + i * 5.5, 2),
                }
                for i in range(int(num_items))
            ]
            payload = {
                "external_order_id": f"DEMO-{ts}",
                "channel": channel,
                "customer_name": "Demo User",
                "shipping_address": "123 Demo Street, Test City",
                "items": items,
            }
            code, order = api.create_order(base, payload)
            if code == 201:
                demo["order_id"] = order["id"]
                demo["order"] = order
                demo["step"] = 2
                st.rerun()
            else:
                st.error(f"Order creation failed ({code})")
                st.json(order)

    with col_form:
        st.markdown("**Custom Order** — fill in your own details")
        with st.form("custom_order"):
            ext_id = st.text_input("External ID", value=f"UI-{int(time.time())}")
            cust = st.text_input("Customer Name", value="Jane Doe")
            addr = st.text_input("Address", value="456 Test Ave, Demo Town")
            ch = st.selectbox("Channel", ["shopify", "amazon", "manual"], key="co_ch")
            sku = st.text_input("SKU", value="CUSTOM-1")
            submitted = st.form_submit_button(
                "Submit", type="primary", use_container_width=True
            )

        if submitted:
            payload = {
                "external_order_id": ext_id,
                "channel": ch,
                "customer_name": cust,
                "shipping_address": addr,
                "items": [
                    {
                        "sku": sku,
                        "product_name": f"Product {sku}",
                        "quantity": 1,
                        "unit_price": 19.99,
                    }
                ],
            }
            code, order = api.create_order(base, payload)
            if code == 201:
                demo["order_id"] = order["id"]
                demo["order"] = order
                demo["step"] = 2
                st.rerun()
            else:
                st.error(f"Order creation failed ({code})")
                st.json(order)


# ── Step 2: Watch Pipeline ────────────────────────────────────────────────────

if demo["step"] >= 2:
    if demo["step"] > 2:
        st.markdown(
            ":white_check_mark: **Step 2 — Pipeline Complete** "
            "(received → validated → erp_synced → allocated → shipped)"
        )
    else:
        st.subheader("Step 2 — Watch Pipeline")
        st.caption(f"Order `{demo['order_id']}` — polling for status changes...")

        code, fresh = api.get_order(base, demo["order_id"])
        if code == 200 and isinstance(fresh, dict):
            demo["order"] = fresh
            current_status = fresh["status"]

            if current_status in ORDER_PIPELINE:
                idx = ORDER_PIPELINE.index(current_status)
                pct = (idx + 1) / len(ORDER_PIPELINE)
            else:
                pct = 0.0

            st.progress(pct, text=f"Current status: **{current_status}**")
            _render_status_timeline(ORDER_PIPELINE, current_status)

            if current_status == "shipped":
                st.success("Pipeline complete — order has been **shipped**.")
                demo["step"] = 3
                time.sleep(1)
                st.rerun()
            elif current_status in ("exception", "cancelled"):
                st.error(f"Pipeline ended with: **{current_status}**")
            else:
                time.sleep(2)
                st.rerun()
        else:
            st.warning("Could not fetch order — retrying...")
            time.sleep(2)
            st.rerun()


# ── Step 3: Shipment + ETA ────────────────────────────────────────────────────

if demo["step"] >= 3:
    if demo["step"] > 3:
        pred = demo["prediction"] or {}
        ship_label = demo["shipment_id"][:8] + "..." if demo["shipment_id"] else "---"
        eta_label = (
            f"{pred['predicted_eta_hours']:.1f}h" if pred else "---"
        )
        with st.expander(
            f":white_check_mark: Step 3 — Shipment `{ship_label}` | ETA: {eta_label}"
        ):
            c1, c2 = st.columns(2)
            c1.markdown("**Shipment**")
            c1.json(demo["shipment"])
            c2.markdown("**Prediction**")
            c2.json(demo["prediction"])
    else:
        st.subheader("Step 3 — Shipment + ETA Prediction")

        if not demo["shipment_id"]:
            shipments = _run_query(
                "SELECT id, carrier, tracking_number, created_at, status "
                "FROM shipments WHERE order_id = $1",
                uuid.UUID(demo["order_id"]),
            )
            if shipments:
                ship = shipments[0]
                demo["shipment_id"] = str(ship["id"])
                demo["shipment"] = {
                    "id": str(ship["id"]),
                    "carrier": ship["carrier"],
                    "tracking_number": ship["tracking_number"],
                    "status": ship["status"],
                    "created_at": str(ship["created_at"]),
                }
                st.rerun()
            else:
                st.info("Waiting for shipment to be created...")
                time.sleep(2)
                st.rerun()

        if demo["shipment_id"]:
            ship = demo["shipment"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Shipment ID", ship["id"][:12] + "...")
            c2.metric("Carrier", ship["carrier"] or "---")
            c3.metric("Tracking #", ship["tracking_number"] or "---")

            if not demo["prediction"]:
                preds = _run_query(
                    "SELECT predicted_eta_hours, model_version, input_features, "
                    "predicted_at FROM predictions WHERE shipment_id = $1 "
                    "ORDER BY predicted_at DESC LIMIT 1",
                    uuid.UUID(demo["shipment_id"]),
                )
                if preds:
                    pred = preds[0]
                    demo["prediction"] = {
                        "predicted_eta_hours": float(pred["predicted_eta_hours"]),
                        "model_version": pred["model_version"],
                        "input_features": pred["input_features"],
                        "predicted_at": str(pred["predicted_at"])[:19],
                    }
                    st.rerun()
                else:
                    st.info(
                        "Waiting for ML prediction... "
                        "(the stream processor needs a moment)"
                    )
                    time.sleep(2)
                    st.rerun()

            if demo["prediction"]:
                st.divider()
                st.markdown("**ML ETA Prediction**")
                pred = demo["prediction"]
                p1, p2, p3 = st.columns(3)
                p1.metric(
                    "Predicted ETA", f"{pred['predicted_eta_hours']:.1f} hours"
                )
                p2.metric("Model Version", pred["model_version"])
                p3.metric("Predicted At", pred["predicted_at"])

                if pred.get("input_features"):
                    with st.expander("Model Input Features"):
                        st.json(pred["input_features"])

                st.markdown("")
                if st.button(
                    ":truck: Continue to Delivery Simulation",
                    type="primary",
                    use_container_width=True,
                ):
                    demo["step"] = 4
                    st.rerun()


# ── Step 4: Simulate Delivery ─────────────────────────────────────────────────

if demo["step"] >= 4:
    if demo["step"] > 4:
        st.markdown(
            ":white_check_mark: **Step 4 — Delivery Complete** "
            "(picked_up → in_transit → out_for_delivery → delivered)"
        )
    else:
        st.subheader("Step 4 — Simulate Delivery")
        st.caption(
            "Push shipment through the delivery lifecycle one step at a time."
        )

        delivery_idx = demo["delivery_index"]

        cols = st.columns(len(DELIVERY_STEPS))
        for i, (col, (status, loc)) in enumerate(zip(cols, DELIVERY_STEPS)):
            if i < delivery_idx:
                col.markdown(f":green_circle: **{status}**")
                col.caption(loc)
            elif i == delivery_idx:
                col.markdown(f":large_blue_circle: **{status}**")
                col.caption(loc)
            else:
                col.markdown(f":white_circle: {status}")
                col.caption(loc)

        if delivery_idx < len(DELIVERY_STEPS):
            next_status, next_loc = DELIVERY_STEPS[delivery_idx]
            if st.button(
                f":arrow_right: Push **{next_status}** @ {next_loc}",
                type="primary",
                use_container_width=True,
            ):
                code, _ = api.push_shipment_status(
                    base, demo["shipment_id"], next_status, next_loc
                )
                if code == 202:
                    demo["delivery_index"] = delivery_idx + 1
                    time.sleep(1)

                    tc, tracking = api.get_tracking(base, demo["shipment_id"])
                    if tc == 200 and isinstance(tracking, list):
                        demo["tracking"] = tracking

                    if delivery_idx + 1 >= len(DELIVERY_STEPS):
                        time.sleep(2)
                        demo["step"] = 5
                    st.rerun()
                else:
                    st.error(f"Push failed ({code})")

        if demo["tracking"]:
            st.divider()
            st.markdown("**Tracking Events**")
            for ev in demo["tracking"]:
                payload = ev.get("payload", {})
                stat = payload.get("status", "---")
                loc = payload.get("location", "---")
                ts = ev.get("created_at", "")[:19]
                icon = (
                    ":white_check_mark:" if stat == "delivered" else ":truck:"
                )
                with st.container(border=True):
                    ec1, ec2, ec3 = st.columns([2, 3, 2])
                    ec1.markdown(f"{icon} **{stat}**")
                    ec2.markdown(loc)
                    ec3.caption(ts)


# ── Step 5: ML Feedback ───────────────────────────────────────────────────────

if demo["step"] >= 5:
    st.subheader("Step 5 — ML Feedback Loop")
    st.caption("Compare the predicted ETA to the actual delivery time.")

    if not demo["actual_eta"]:
        actuals = _run_query(
            "SELECT actual_eta_hours, absolute_error, recorded_at "
            "FROM prediction_actuals WHERE shipment_id = $1 "
            "ORDER BY recorded_at DESC LIMIT 1",
            uuid.UUID(demo["shipment_id"]),
        )
        if actuals:
            act = actuals[0]
            demo["actual_eta"] = {
                "actual_eta_hours": float(act["actual_eta_hours"]),
                "absolute_error": float(act["absolute_error"]),
                "recorded_at": str(act["recorded_at"])[:19],
            }

    pred = demo["prediction"]
    if demo["actual_eta"]:
        act = demo["actual_eta"]

        col_pred, col_vs, col_actual = st.columns([2, 1, 2])
        col_pred.metric("Predicted ETA", f"{pred['predicted_eta_hours']:.1f} h")
        col_vs.markdown(
            "<div style='text-align:center; padding-top:1.5rem;'>"
            "<h2>vs</h2></div>",
            unsafe_allow_html=True,
        )
        col_actual.metric("Actual ETA", f"{act['actual_eta_hours']:.2f} h")

        st.divider()
        e1, e2, e3 = st.columns(3)
        e1.metric("Absolute Error", f"{act['absolute_error']:.2f} h")
        e2.metric("Model Version", pred["model_version"])
        e3.metric("Recorded At", act["recorded_at"])

        st.success(
            "Demo complete! The ML model's prediction has been compared to the "
            "actual delivery time. Check the **ML Insights** page for aggregate "
            "accuracy across all deliveries."
        )
    else:
        st.info(
            "Waiting for feedback loop to record actual vs predicted... "
            "(the stream processor computes this on delivery)"
        )
        b1, b2 = st.columns(2)
        if b1.button("Refresh", use_container_width=True):
            st.rerun()
        time.sleep(3)
        st.rerun()


# ── System Stats (collapsible) ────────────────────────────────────────────────

st.divider()
with st.expander("System Stats"):
    c1, c2, c3, c4 = st.columns(4)

    code_o, orders_list = api.list_orders(base, limit=100)
    if code_o == 200 and isinstance(orders_list, list):
        c1.metric("Total Orders", len(orders_list))
        by_status: dict[str, int] = {}
        for o in orders_list:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        c2.metric("Shipped", by_status.get("shipped", 0))
        c3.metric("Delivered", by_status.get("delivered", 0))
        c4.metric("Exceptions", by_status.get("exception", 0))

    try:
        pred_stats = _run_query(
            "SELECT COUNT(*) AS total, "
            "COUNT(DISTINCT model_version) AS models FROM predictions"
        )
        actual_stats = _run_query(
            "SELECT COUNT(*) AS total, "
            "COALESCE(AVG(absolute_error), 0) AS mae FROM prediction_actuals"
        )
        p = pred_stats[0] if pred_stats else {"total": 0, "models": 0}
        a = actual_stats[0] if actual_stats else {"total": 0, "mae": 0}

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Predictions", p["total"])
        m2.metric("Model Versions", p["models"])
        m3.metric("Feedback Samples", a["total"])
        m4.metric("MAE", f'{float(a["mae"]):.2f} h')
    except Exception:
        pass
