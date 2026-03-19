"""
Orders — create, browse, inspect, and cancel orders.
"""

import os
import time

import streamlit as st

import api_client as api

base = st.session_state.get("api_base", os.getenv("API_BASE_URL", "http://api:8000"))

st.header("Explorer — Orders")

tab_create, tab_browse, tab_detail = st.tabs(["Create Order", "Browse Orders", "Order Detail"])

# ── Create Order ──────────────────────────────────────────────────────────────

with tab_create:
    st.subheader("Import a New Order")

    with st.form("create_order_form"):
        col1, col2 = st.columns(2)
        ext_id = col1.text_input("External Order ID", value=f"UI-{int(time.time())}")
        channel = col2.selectbox("Channel", ["shopify", "amazon", "manual", "erp", "other"])

        col3, col4 = st.columns(2)
        name = col3.text_input("Customer Name", value="")
        email = col4.text_input("Customer Email (optional)", value="")

        address = st.text_input("Shipping Address", value="")

        st.markdown("**Order Items**")
        num_items = st.number_input("Number of items", min_value=1, max_value=10, value=1)

        items = []
        for i in range(int(num_items)):
            st.markdown(f"*Item {i + 1}*")
            ic1, ic2, ic3, ic4 = st.columns([2, 3, 1, 1])
            sku = ic1.text_input("SKU", key=f"sku_{i}", value=f"ITEM-{i+1}")
            prod = ic2.text_input("Product Name", key=f"prod_{i}", value=f"Product {i+1}")
            qty = ic3.number_input("Qty", key=f"qty_{i}", min_value=1, value=1)
            price = ic4.number_input("Price", key=f"price_{i}", min_value=0.0, value=10.0, step=0.5)
            items.append({"sku": sku, "product_name": prod, "quantity": int(qty), "unit_price": float(price)})

        submitted = st.form_submit_button("Submit Order", type="primary", use_container_width=True)

    if submitted:
        if not name or not address:
            st.error("Customer name and shipping address are required.")
        else:
            payload = {
                "external_order_id": ext_id,
                "channel": channel,
                "customer_name": name,
                "shipping_address": address,
                "items": items,
            }
            if email:
                payload["customer_email"] = email

            code, body = api.create_order(base, payload)
            if code == 201:
                st.success(f"Order created — ID: `{body['id']}`  Status: **{body['status']}**")
                with st.expander("Response"):
                    st.json(body)
            elif code == 409:
                st.warning(f"Duplicate: {body.get('detail', 'Order already exists')}")
            else:
                st.error(f"Failed ({code})")
                st.json(body)


# ── Browse Orders ─────────────────────────────────────────────────────────────

with tab_browse:
    st.subheader("Order List")

    fc1, fc2, fc3 = st.columns([2, 2, 1])
    f_status = fc1.selectbox(
        "Filter by status",
        [None, "received", "validated", "erp_synced", "allocated", "shipped", "delivered", "cancelled", "exception"],
        format_func=lambda x: "All statuses" if x is None else x,
    )
    f_channel = fc2.text_input("Filter by channel", value="")
    fc3.write("")  # spacer
    refresh = fc3.button("Refresh", key="refresh_orders", use_container_width=True)

    code, orders = api.list_orders(base, status=f_status, channel=f_channel or None)

    if code == 200 and isinstance(orders, list):
        if not orders:
            st.info("No orders match the filter.")
        else:
            STATUS_COLORS = {
                "received": "blue",
                "validated": "blue",
                "erp_synced": "blue",
                "allocated": "violet",
                "shipped": "green",
                "delivered": "green",
                "cancelled": "orange",
                "exception": "red",
            }
            for o in orders:
                color = STATUS_COLORS.get(o["status"], "gray")
                with st.container(border=True):
                    r1, r2, r3, r4 = st.columns([3, 2, 2, 1])
                    r1.markdown(f"**{o['external_order_id']}**")
                    r1.caption(f"`{o['id']}`")
                    r2.markdown(f":{color}[{o['status']}]")
                    r2.caption(o["channel"])
                    r3.markdown(o["customer_name"])
                    r3.caption(o["created_at"][:19])
                    if o["status"] not in ("shipped", "delivered", "cancelled"):
                        if r4.button("Cancel", key=f"cancel_{o['id']}", use_container_width=True):
                            cc, cb = api.cancel_order(base, o["id"])
                            if cc == 200:
                                st.success(f"Cancelled {o['id']}")
                                st.rerun()
                            else:
                                st.error(f"Cancel failed: {cb.get('detail', cc)}")
    else:
        st.error("Could not fetch orders.")
        if isinstance(orders, dict):
            st.json(orders)


# ── Order Detail ──────────────────────────────────────────────────────────────

with tab_detail:
    st.subheader("Order Lookup")

    order_id = st.text_input("Order ID (UUID)", key="detail_order_id")

    if order_id:
        code, body = api.get_order(base, order_id.strip())
        if code == 200:
            STATUS_PIPELINE = ["received", "validated", "erp_synced", "allocated", "shipped", "delivered"]

            current = body["status"]
            if current in STATUS_PIPELINE:
                idx = STATUS_PIPELINE.index(current)
                progress_pct = (idx + 1) / len(STATUS_PIPELINE)
            else:
                progress_pct = 0.0

            st.progress(progress_pct, text=f"Status: **{current}**")

            d1, d2 = st.columns(2)
            d1.markdown(f"**External ID:** {body['external_order_id']}")
            d1.markdown(f"**Channel:** {body['channel']}")
            d1.markdown(f"**Customer:** {body['customer_name']}")
            d2.markdown(f"**Address:** {body['shipping_address']}")
            d2.markdown(f"**Created:** {body['created_at'][:19]}")
            d2.markdown(f"**Updated:** {body['updated_at'][:19]}")

            if current not in ("shipped", "delivered", "cancelled"):
                if st.button("Cancel This Order", type="secondary"):
                    cc, cb = api.cancel_order(base, order_id.strip())
                    if cc == 200:
                        st.success("Order cancelled.")
                        st.rerun()
                    else:
                        st.error(f"Cancel failed: {cb.get('detail', cc)}")

            with st.expander("Raw JSON"):
                st.json(body)

            if st.button("Auto-refresh (poll for 30s)", key="poll_order"):
                placeholder = st.empty()
                deadline = time.time() + 30
                while time.time() < deadline:
                    _, fresh = api.get_order(base, order_id.strip())
                    if isinstance(fresh, dict):
                        placeholder.markdown(f"Status: **{fresh['status']}**  (updated {fresh['updated_at'][:19]})")
                        if fresh["status"] in ("shipped", "delivered", "cancelled", "exception"):
                            break
                    time.sleep(2)
                st.rerun()

        elif code == 404:
            st.warning("Order not found.")
        else:
            st.error(f"Error ({code})")
            if isinstance(body, dict):
                st.json(body)
