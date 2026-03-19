"""
Webhooks — manage outbound subscriptions and send inbound carrier webhooks.
"""

import os

import streamlit as st

import api_client as api

base = st.session_state.get("api_base", os.getenv("API_BASE_URL", "http://api:8000"))

st.header("Explorer — Webhooks")

tab_subs, tab_inbound = st.tabs(["Subscriptions", "Inbound Webhook"])

# ── Subscriptions ─────────────────────────────────────────────────────────────

with tab_subs:
    st.subheader("Webhook Subscriptions")

    with st.form("create_sub_form"):
        st.markdown("**Create Subscription**")
        sub_url = st.text_input("Callback URL", value="https://hooks.example.com/supply-chain")
        sub_events = st.multiselect(
            "Events to subscribe to",
            ["shipment.status-updated", "order.shipped", "order.received", "order.cancelled"],
            default=["shipment.status-updated", "order.shipped"],
        )
        sub_secret = st.text_input("HMAC Secret (optional)", type="password")
        sub_submit = st.form_submit_button("Create Subscription", type="primary", use_container_width=True)

    if sub_submit:
        if not sub_url or not sub_events:
            st.error("URL and at least one event are required.")
        else:
            code, body = api.create_subscription(base, sub_url, sub_events, sub_secret or None)
            if code == 201:
                st.success(f"Subscription created — ID: `{body['id']}`")
                with st.expander("Details"):
                    st.json(body)
            else:
                st.error(f"Failed ({code})")
                if isinstance(body, dict):
                    st.json(body)

    st.divider()
    st.subheader("Active Subscriptions")

    if st.button("Refresh", key="refresh_subs"):
        st.rerun()

    code, subs = api.list_subscriptions(base)
    if code == 200 and isinstance(subs, list):
        if not subs:
            st.info("No subscriptions yet.")
        else:
            for s in subs:
                with st.container(border=True):
                    sc1, sc2 = st.columns([3, 2])
                    active_label = ":green[active]" if s.get("active") else ":red[inactive]"
                    sc1.markdown(f"**{s['url']}**  {active_label}")
                    sc1.caption(f"ID: `{s['id']}`")
                    sc2.markdown(f"Events: {', '.join(s.get('events', []))}")
                    sc2.caption(f"Created: {s.get('created_at', '---')[:19]}")
    else:
        st.error("Could not fetch subscriptions.")


# ── Inbound Webhook ───────────────────────────────────────────────────────────

with tab_inbound:
    st.subheader("Send Inbound Webhook")
    st.caption("Simulate a carrier or external system sending a webhook to the platform.")

    with st.form("inbound_form"):
        event_type = st.selectbox("Event Type", [
            "shipment.status-updated",
            "order.status-updated",
        ])
        ref_id = st.text_input("Reference ID (shipment or order UUID)")
        inb_status = st.selectbox("Status", [
            "picked_up", "in_transit", "out_for_delivery", "delivered", "exception",
        ])
        notes = st.text_area("Notes (optional)", value="")
        inb_submit = st.form_submit_button("Send Webhook", type="primary", use_container_width=True)

    if inb_submit:
        if not ref_id:
            st.error("Reference ID is required.")
        else:
            payload = {
                "event_type": event_type,
                "reference_id": ref_id.strip(),
                "status": inb_status,
            }
            if notes:
                payload["notes"] = notes
            code, body = api.send_inbound_webhook(base, payload)
            if code == 200:
                st.success("Webhook delivered successfully.")
                with st.expander("Response"):
                    st.json(body)
            else:
                st.error(f"Failed ({code})")
                if isinstance(body, dict):
                    st.json(body)
