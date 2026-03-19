"""
Shipments — look up shipments, view tracking history, push status updates.
"""

import os

import streamlit as st

import api_client as api

base = st.session_state.get("api_base", os.getenv("API_BASE_URL", "http://api:8000"))

st.header("Explorer — Shipments")

tab_lookup, tab_update = st.tabs(["Lookup & Tracking", "Push Status Update"])

SHIPMENT_PIPELINE = ["requested", "created", "picked_up", "in_transit", "out_for_delivery", "delivered"]

# ── Lookup ────────────────────────────────────────────────────────────────────

with tab_lookup:
    st.subheader("Shipment Lookup")

    sid = st.text_input("Shipment ID (UUID)", key="shipment_lookup_id")

    if sid:
        code, body = api.get_shipment(base, sid.strip())

        if code == 200:
            current = body["status"]
            if current in SHIPMENT_PIPELINE:
                idx = SHIPMENT_PIPELINE.index(current)
                pct = (idx + 1) / len(SHIPMENT_PIPELINE)
            else:
                pct = 0.0

            st.progress(pct, text=f"Status: **{current}**")

            c1, c2 = st.columns(2)
            c1.markdown(f"**Shipment ID:** `{body['id']}`")
            c1.markdown(f"**Order ID:** `{body['order_id']}`")
            c1.markdown(f"**Carrier:** {body.get('carrier') or '---'}")
            c2.markdown(f"**Tracking #:** {body.get('tracking_number') or '---'}")
            c2.markdown(f"**Created:** {body['created_at'][:19]}")
            c2.markdown(f"**Updated:** {body['updated_at'][:19]}")

            with st.expander("Raw JSON"):
                st.json(body)

            # Tracking history
            st.divider()
            st.subheader("Tracking History")

            tc, tracking = api.get_tracking(base, sid.strip())
            if tc == 200 and isinstance(tracking, list):
                if not tracking:
                    st.info("No tracking events yet.")
                else:
                    for ev in tracking:
                        payload = ev.get("payload", {})
                        icon = ":white_check_mark:" if payload.get("status") == "delivered" else ":truck:"
                        loc = payload.get("location", "---")
                        stat = payload.get("status", ev.get("event_type", "---"))
                        ts = ev.get("created_at", "")[:19]

                        with st.container(border=True):
                            ec1, ec2, ec3 = st.columns([2, 3, 2])
                            ec1.markdown(f"{icon} **{stat}**")
                            ec2.markdown(loc)
                            ec3.caption(ts)
            else:
                st.warning("Could not fetch tracking events.")

        elif code == 404:
            st.warning("Shipment not found.")
        else:
            st.error(f"Error ({code})")
            if isinstance(body, dict):
                st.json(body)


# ── Push Status ───────────────────────────────────────────────────────────────

with tab_update:
    st.subheader("Push Tracking Status")
    st.caption("Simulate a driver or warehouse pushing a status update.")

    with st.form("push_status_form"):
        ship_id = st.text_input("Shipment ID")
        new_status = st.selectbox("New Status", SHIPMENT_PIPELINE[2:])  # skip requested/created
        location = st.text_input("Location (optional)", value="")

        pushed = st.form_submit_button("Push Status", type="primary", use_container_width=True)

    if pushed:
        if not ship_id:
            st.error("Shipment ID is required.")
        else:
            code, body = api.push_shipment_status(base, ship_id.strip(), new_status, location or None)
            if code == 202:
                st.success(f"Status **{new_status}** accepted for shipment `{ship_id.strip()}`")
            elif code == 404:
                st.warning("Shipment not found.")
            else:
                st.error(f"Failed ({code})")
                if isinstance(body, dict):
                    st.json(body)
