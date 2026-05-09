"""
ML Insights — prediction log and model accuracy metrics.
Use the Demo Flow (home page) for the end-to-end lifecycle; this page
shows aggregate prediction data and accuracy trends.
"""

import asyncio
import os

import asyncpg
import streamlit as st

base = st.session_state.get("api_base", os.getenv("API_BASE_URL", "http://api:8000"))
DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://supplychain:supplychain_secret@postgresql:5432/supplychain",
)

st.header("ML Insights")

tab_browse, tab_accuracy = st.tabs(["Prediction Log", "Model Accuracy"])


def _run_query(sql, *args):
    async def _q():
        conn = await asyncpg.connect(DB_DSN)
        rows = await conn.fetch(sql, *args)
        await conn.close()
        return rows

    return asyncio.new_event_loop().run_until_complete(_q())


# ── Prediction Log ────────────────────────────────────────────────────────────

with tab_browse:
    st.subheader("Recent ETA Predictions")

    if st.button("Refresh", key="refresh_preds"):
        pass

    rows = _run_query(
        "SELECT p.delivery_order_id, p.predicted_eta_hours, p.model_version, p.predicted_at, "
        "       d.status AS delivery_status, so.external_order_id "
        "FROM predictions p "
        "JOIN delivery_orders d ON d.delivery_order_id = p.delivery_order_id "
        "JOIN sale_orders so ON so.sale_order_id = p.sale_order_id "
        "ORDER BY p.predicted_at DESC LIMIT 50"
    )

    if rows:
        data = [
            {
                "Delivery Order": str(r["delivery_order_id"])[:8] + "...",
                "External Order": r["external_order_id"],
                "Delivery Status": r["delivery_status"],
                "Predicted ETA (h)": round(r["predicted_eta_hours"], 1),
                "Model": r["model_version"],
                "Predicted At": str(r["predicted_at"])[:19],
            }
            for r in rows
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        st.caption(f"{len(rows)} predictions total")
    else:
        st.info("No predictions yet. Run the demo to generate some.")


# ── Model Accuracy ────────────────────────────────────────────────────────────

with tab_accuracy:
    st.subheader("Model Accuracy — Predictions vs Actuals")

    if st.button("Refresh", key="refresh_accuracy"):
        pass

    actuals = _run_query(
        "SELECT pa.sale_order_id, p.delivery_order_id, p.predicted_eta_hours, pa.actual_eta_hours, "
        "       pa.absolute_error, pa.recorded_at "
        "FROM prediction_actuals pa "
        "JOIN predictions p ON p.id = pa.prediction_id "
        "ORDER BY pa.recorded_at DESC LIMIT 50"
    )

    if actuals:
        data = [
            {
                "Sale Order": str(r["sale_order_id"])[:8] + "...",
                "Delivery Order": str(r["delivery_order_id"])[:8] + "...",
                "Predicted (h)": round(r["predicted_eta_hours"], 1),
                "Actual (h)": round(r["actual_eta_hours"], 2),
                "Error (h)": round(r["absolute_error"], 2),
                "Recorded": str(r["recorded_at"])[:19],
            }
            for r in actuals
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)

        errors = [r["absolute_error"] for r in actuals]
        n = len(errors)
        mae = sum(errors) / n
        rmse = (sum(e**2 for e in errors) / n) ** 0.5

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Samples", n)
        c2.metric("MAE", f"{mae:.2f} h")
        c3.metric("RMSE", f"{rmse:.2f} h")
    else:
        st.info(
            "No actuals yet. Predictions are compared to actuals when a "
            "shipment reaches **delivered**. Run the demo to see the full "
            "feedback loop."
        )
