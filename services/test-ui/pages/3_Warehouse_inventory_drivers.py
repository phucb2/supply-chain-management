"""
Warehouse — goods-in/out, inventory overview, driver management.
"""

import os
from uuid import UUID

import streamlit as st

import api_client as api

base = st.session_state.get("api_base", os.getenv("API_BASE_URL", "http://api:8000"))

st.header("Explorer — Warehouse")

tab_inv, tab_move, tab_drivers = st.tabs(["Inventory", "Goods Movement", "Drivers"])

# ── Inventory ─────────────────────────────────────────────────────────────────

with tab_inv:
    st.subheader("Current Inventory Levels")

    if st.button("Refresh", key="refresh_inventory"):
        st.rerun()

    code, data = api.list_inventory(base)
    if code == 200 and isinstance(data, list):
        if not data:
            st.info("No inventory data. Record goods-in to get started.")
        else:
            st.dataframe(data, use_container_width=True, hide_index=True)
    else:
        st.error("Could not fetch inventory.")
        if isinstance(data, dict):
            st.json(data)


# ── Goods Movement ────────────────────────────────────────────────────────────

with tab_move:
    col_in, col_out = st.columns(2)

    with col_in:
        st.subheader("Goods In")
        with st.form("goods_in_form"):
            gi_sku = st.text_input("SKU", key="gi_sku")
            gi_qty = st.number_input("Quantity", min_value=1, value=100, key="gi_qty")
            gi_ref = st.text_input("Reference # (optional)", key="gi_ref")
            gi_sub = st.form_submit_button("Record Goods-In", type="primary", use_container_width=True)

        if gi_sub:
            if not gi_sku:
                st.error("SKU is required.")
            else:
                code, body = api.goods_in(base, gi_sku, int(gi_qty), gi_ref or None)
                if code == 202:
                    st.success(f"Goods-in accepted: {gi_sku} x{gi_qty}")
                else:
                    st.error(f"Failed ({code})")
                    if isinstance(body, dict):
                        st.json(body)

    with col_out:
        st.subheader("Goods Out")
        with st.form("goods_out_form"):
            go_sku = st.text_input("SKU", key="go_sku")
            go_qty = st.number_input("Quantity", min_value=1, value=10, key="go_qty")
            go_ref = st.text_input("Reference # (optional)", key="go_ref")
            go_sub = st.form_submit_button("Record Goods-Out", type="primary", use_container_width=True)

        if go_sub:
            if not go_sku:
                st.error("SKU is required.")
            else:
                code, body = api.goods_out(base, go_sku, int(go_qty), go_ref or None)
                if code == 202:
                    st.success(f"Goods-out accepted: {go_sku} x{go_qty}")
                else:
                    st.error(f"Failed ({code})")
                    if isinstance(body, dict):
                        st.json(body)


# ── Drivers ───────────────────────────────────────────────────────────────────

with tab_drivers:
    st.subheader("Driver Management")

    with st.form("add_driver_form"):
        st.markdown("**Register a New Driver**")
        dc1, dc2 = st.columns(2)
        d_name = dc1.text_input("Full name")
        d_license = dc2.text_input("License number")
        d_phone = st.text_input("Phone (optional)")
        d_vendor_id = st.text_input("Vendor ID — UUID only (optional)", placeholder="00000000-0000-0000-0000-000000000000")
        d_sub = st.form_submit_button("Add Driver", type="primary", use_container_width=True)

    if d_sub:
        if not d_name or not d_license:
            st.error("Full name and license number are required.")
        else:
            vid: str | None = None
            if d_vendor_id and d_vendor_id.strip():
                try:
                    vid = str(UUID(d_vendor_id.strip()))
                except ValueError:
                    st.error("Vendor ID must be a valid UUID.")
                    vid = "__invalid__"
            if vid != "__invalid__":
                code, body = api.create_driver(
                    base,
                    d_name.strip(),
                    d_license.strip(),
                    d_phone.strip() or None,
                    vid,
                )
                if code == 201:
                    st.success(f"Driver created: **{body.get('name', d_name)}** — ID: `{body['id']}`")
                else:
                    st.error(f"Failed ({code})")
                    if isinstance(body, dict):
                        st.json(body)

    st.divider()
    st.markdown("**Remove a Driver**")
    rm_id = st.text_input("Driver ID to remove")
    if st.button("Remove Driver", type="secondary"):
        if rm_id:
            code, body = api.delete_driver(base, rm_id.strip())
            if code == 200:
                st.success("Driver removed.")
            elif code == 404:
                st.warning("Driver not found.")
            else:
                st.error(f"Failed ({code})")
                if isinstance(body, dict):
                    st.json(body)
