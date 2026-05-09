"""
Live multi-role demo: Customer, Warehouse, and Driver viewports (B2B / B2C).
Uses existing API only; separate Streamlit route from the home demo.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import html
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

API_BASE_DEFAULT = os.getenv("API_BASE_URL", "http://api:8000")
DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://supplychain:supplychain_secret@postgresql:5432/supplychain",
)


def _fetch_latest_prediction(shipment_id: str) -> dict | None:
    """Load newest ML ETA row for this delivery order (same source as main demo)."""

    async def _q():
        conn = await asyncpg.connect(DB_DSN)
        try:
            rows = await conn.fetch(
                "SELECT predicted_eta_hours, model_version, predicted_at "
                "FROM predictions WHERE delivery_order_id = $1 "
                "ORDER BY predicted_at DESC LIMIT 1",
                shipment_id,
            )
        finally:
            await conn.close()
        return rows

    try:
        rows = asyncio.new_event_loop().run_until_complete(_q())
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    return {
        "predicted_eta_hours": float(row["predicted_eta_hours"]),
        "model_version": row["model_version"],
        "predicted_at": str(row["predicted_at"])[:19] if row["predicted_at"] else "",
    }

st.set_page_config(page_title="Live roles demo", page_icon=":busts_in_silhouette:", layout="wide")
inject_sidebar_styles()

st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        padding: 0.5rem 0.75rem 0.75rem 0.75rem;
    }
    h1 { font-size: 1.35rem; margin-bottom: 0.15rem; }
    .story-track { font-size: 0.92rem; margin: 0.35rem 0 0.55rem 0; line-height: 1.45; opacity: 0.92; }
    /* Status rail */
    .lr-rail { margin: 0.35rem 0 0.5rem 0; }
    .lr-rail-title { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em; opacity: 0.6; margin-bottom: 0.35rem; }
    .lr-rail-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.15rem; }
    .lr-rs { flex: 1; text-align: center; position: relative; min-width: 0; }
    .lr-rs-dot {
        width: 0.55rem; height: 0.55rem; border-radius: 50%; margin: 0 auto 0.25rem;
        background: rgba(128,128,128,0.35);
    }
    .lr-rs-done .lr-rs-dot { background: #2e8540; }
    .lr-rs-current .lr-rs-dot {
        background: #1f6feb;
        box-shadow: 0 0 0 3px rgba(31, 111, 235, 0.28);
    }
    .lr-rs-todo .lr-rs-lbl { opacity: 0.45; }
    .lr-rs-lbl { font-size: 0.65rem; line-height: 1.2; display: block; }
    .lr-pill-row { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.35rem; align-items: center; }
    .lr-pill {
        font-size: 0.74rem; padding: 0.2rem 0.55rem; border-radius: 999px;
        border: 1px solid rgba(128,128,128,0.35);
    }
    .lr-pill b { opacity: 0.65; font-weight: 600; margin-right: 0.3rem; }
    /* Vertical timeline */
    .lr-tl-wrap { margin-top: 0.15rem; }
    .lr-tl-heading {
        font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em;
        opacity: 0.6; margin-bottom: 0.4rem;
    }
    .lr-tl { list-style: none; margin: 0; padding: 0; }
    .lr-tl li {
        position: relative; padding: 0 0 1rem 1.4rem; margin: 0;
    }
    .lr-tl li::before {
        content: ""; position: absolute; left: 0.48rem; top: 1.05rem; bottom: 0.1rem;
        width: 2px; background: rgba(128,128,128,0.28);
    }
    .lr-tl li:last-child::before { display: none; }
    .lr-tl-dot {
        position: absolute; left: 0.22rem; top: 0.32rem; width: 0.62rem; height: 0.62rem;
        border-radius: 50%; background: #5a7ab8;
        box-shadow: 0 0 0 2px rgba(250,250,250,0.95), 0 0 0 3px rgba(0,0,0,0.06);
    }
    .lr-tl-latest .lr-tl-dot {
        width: 0.78rem; height: 0.78rem; left: 0.14rem; top: 0.26rem;
        background: #1f6feb;
    }
    .lr-v-done .lr-tl-dot { background: #2e8540; }
    .lr-v-bad .lr-tl-dot { background: #c0392b; }
    .lr-v-move .lr-tl-dot { background: #2874a6; }
    .lr-tl-meta { font-size: 0.72rem; opacity: 0.62; line-height: 1.3; }
    .lr-tl-title { font-weight: 600; font-size: 0.9rem; margin-top: 0.12rem; line-height: 1.3; }
    .lr-tl-sub { font-size: 0.76rem; opacity: 0.78; margin-top: 0.18rem; line-height: 1.35; }
    .lr-tl-badge {
        font-size: 0.62rem; font-weight: 600; margin-left: 0.35rem; padding: 0.08rem 0.32rem;
        border-radius: 4px; background: rgba(31, 111, 235, 0.15); vertical-align: middle;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "api_base" not in st.session_state:
    st.session_state.api_base = API_BASE_DEFAULT

_LIVE_INIT: dict = {
    "flow": "b2c",
    "outcome_mode": "success",
    "order_id": None,
    "external_order_id": None,
    "order_items": [],
    "order_snapshot": None,
    "shipment_id": None,
    "driver_step": 0,
    "last_error": None,
}

if "live_roles" not in st.session_state:
    st.session_state.live_roles = {**_LIVE_INIT}

with st.sidebar:
    sidebar_brand(page_title="Live roles", tag="Multi-viewport demo")
    sidebar_section_backend()
    sidebar_connection_hint()
    st.text_input("API base URL", key="api_base", placeholder="http://localhost:8000")
    base = st.session_state.api_base
    health_status, _ = api.health_check(base)
    sidebar_api_status(connected=health_status == 200)
    sidebar_section_actions()
    if st.button("Reset session", use_container_width=True, key="lr_reset", help="Clear order, driver steps, and widgets"):
        for _k in (
            "lr_flow_radio",
            "lr_outcome_mode",
            "lr_num_items",
            "lr_live_checkbox",
            "lr_manual_refresh",
            "lr_exc_reason",
            "lr_exc_sim",
        ):
            st.session_state.pop(_k, None)
        st.session_state.live_roles = {**_LIVE_INIT}
        st.rerun()

lr = st.session_state.live_roles

DRIVER_STEPS = [
    ("picked_up", "Picked up", "Dock"),
    ("in_transit", "In transit", "En route"),
    ("delivered", "Delivered", "Drop-off"),
]

_RAIL_LABELS = ["Received", "Confirmed", "Fulfillment", "On the way", "Delivered"]

_ORDER_RANK: dict[str, int] = {
    "pending": 0,
    "confirmed": 1,
    "allocated": 2,
    "packed": 2,
    "in_transit": 3,
    "delivered": 4,
    "cancelled": -2,
    "exception": -2,
}


def _order_rank(status: str | None) -> int:
    return _ORDER_RANK.get((status or "pending").lower(), 0)


def _event_label(event_type: str) -> str:
    raw = (event_type or "").replace("order.", "").strip()
    return raw.replace("_", " ").title() if raw else "Update"


def _timeline_variant(event_type: str) -> str:
    t = (event_type or "").lower()
    if "delivered" in t:
        return "lr-v-done"
    if "exception" in t or "fail" in t or "cancel" in t:
        return "lr-v-bad"
    if "transit" in t or "pick" in t or "out_for" in t:
        return "lr-v-move"
    return ""


def _render_status_block(order_status: str | None, ship_status: str | None, ref: str | None) -> str:
    o = (order_status or "—").lower()
    sh = ship_status or "—"
    ref_s = html.escape(ref or "—")
    if o in ("cancelled", "exception"):
        return (
            f'<div class="lr-pill-row"><span class="lr-pill"><b>Order</b>{html.escape(o)}</span>'
            f'<span class="lr-pill"><b>Shipment</b>{html.escape(sh)}</span>'
            f'<span class="lr-pill"><b>Ref</b>{ref_s}</span></div>'
            f'<div class="lr-rail"><div class="lr-rail-title">Order progress</div>'
            f'<p style="margin:0;font-size:0.85rem;opacity:0.85;">Stopped in <strong>{html.escape(o)}</strong> state.</p></div>'
        )

    rank = _order_rank(order_status)
    parts = [
        '<div class="lr-pill-row">',
        f'<span class="lr-pill"><b>Order</b>{html.escape(order_status or "—")}</span>',
        f'<span class="lr-pill"><b>Shipment</b>{html.escape(sh)}</span>',
        f'<span class="lr-pill"><b>Ref</b>{ref_s}</span>',
        "</div>",
        '<div class="lr-rail"><div class="lr-rail-title">Order progress</div><div class="lr-rail-row">',
    ]
    for i, name in enumerate(_RAIL_LABELS):
        if rank < i:
            cls = "lr-rs lr-rs-todo"
        elif rank == i:
            cls = "lr-rs lr-rs-done lr-rs-current"
        else:
            cls = "lr-rs lr-rs-done"
        parts.append(
            f'<div class="{cls}"><span class="lr-rs-dot"></span>'
            f'<span class="lr-rs-lbl">{html.escape(name)}</span></div>'
        )
    parts.append("</div></div>")
    return "".join(parts)


def _render_tracking_timeline(events: list[dict]) -> str:
    sorted_ev = sorted(
        events,
        key=lambda e: e.get("created_at") or "",
        reverse=True,
    )[:12]
    parts = [
        '<div class="lr-tl-wrap"><div class="lr-tl-heading">Shipment timeline</div><ul class="lr-tl">',
    ]
    for i, ev in enumerate(sorted_ev):
        et = ev.get("event_type") or ""
        when_raw = (ev.get("created_at") or "")[:19]
        when = html.escape(when_raw.replace("T", " "))
        label = html.escape(_event_label(et))
        remarks = (ev.get("payload") or {}).get("remarks")
        sub = html.escape(str(remarks)) if remarks else ""
        classes = [c for c in (_timeline_variant(et), "lr-tl-latest" if i == 0 else "") if c]
        cls = " ".join(classes)
        sub_html = f'<div class="lr-tl-sub">{sub}</div>' if sub else ""
        badge = '<span class="lr-tl-badge">Latest</span>' if i == 0 else ""
        parts.append(
            f'<li class="{cls}"><span class="lr-tl-dot" aria-hidden="true"></span>'
            f'<div class="lr-tl-body"><div class="lr-tl-meta">{when}{badge}</div>'
            f'<div class="lr-tl-title">{label}</div>{sub_html}</div></li>'
        )
    parts.append("</ul></div>")
    return "".join(parts)


def _story_line(lr: dict) -> str:
    """One-line narrative: where you are in the demo."""
    oid = lr.get("order_id")
    sid = lr.get("shipment_id")
    ds = int(lr.get("driver_step") or 0)
    done_drive = ds >= len(DRIVER_STEPS)
    stt = (lr.get("order_snapshot") or {}).get("status", "")
    delivered = stt == "delivered"
    stl = (stt or "").lower()

    if not oid:
        return "**1 · Order** → 2 · Pipeline → 3 · Road → 4 · Closed"
    if stl == "cancelled":
        return "**Flow:** order **cancelled** (customer) — fulfillment stops."
    if stl == "exception":
        return "**Flow:** **Exception** — shipment failed; customer sees problem state in timeline."
    if not sid:
        return "1 ✓ → **2 · Pipeline** (Kafka) → 3 · Road → 4 · Closed"
    if not done_drive:
        return "1 ✓ → 2 ✓ → **3 · Road** (driver taps) → 4 · Closed"
    if delivered:
        return "1 ✓ → 2 ✓ → 3 ✓ → **4 · Closed**"
    return "1 ✓ → 2 ✓ → 3 ✓ → **4 · Closed**"


st.title("One order, three roles")
st.markdown(
    '<p class="story-track"><strong>Story:</strong> Order → warehouse sees pick list → driver updates — or choose a <strong>failure</strong> outcome below '
    "(driver exception or early cancel). <em>The left column reflects the same API + stream pipeline.</em></p>",
    unsafe_allow_html=True,
)

flow = st.radio(
    "Channel",
    options=["b2c", "b2b"],
    index=0 if lr.get("flow") == "b2c" else 1,
    format_func=lambda x: "Retail (B2C)" if x == "b2c" else "Enterprise (B2B)",
    horizontal=True,
    key="lr_flow_radio",
)
lr["flow"] = flow

_outcome_labels = {"success": "Success — full delivery", "exception": "Failure — driver exception", "cancel": "Failure — customer cancel"}
_out_choices = ["success", "exception", "cancel"]
_out_stored = str(lr.get("outcome_mode") or "success")
outcome = st.radio(
    "Demo outcome",
    options=_out_choices,
    index=_out_choices.index(_out_stored) if _out_stored in _out_choices else 0,
    format_func=lambda x: _outcome_labels[x],
    horizontal=True,
    key="lr_outcome_mode",
)
lr["outcome_mode"] = outcome
_outcome_blurb = {
    "success": "Happy path to delivered.",
    "exception": "Driver sends status **exception** → order **exception**, shipment **failed** (stream processor).",
    "cancel": "Customer cancels while the order is still **pending / confirmed / allocated** (not yet in transit).",
}
st.caption(_outcome_blurb[outcome])
st.caption("Live step indicator (bold) refreshes in the **End customer** panel when auto-refresh is on.")

col_customer, col_wh, col_driver = st.columns(3)


def _build_order_payload(cat: str, num_items: int) -> dict:
    ts = int(time.time())
    items = [
        {
            "sku": f"{cat.upper()}-{i + 1}-{ts % 10000}",
            "product_name": f"Line {i + 1}",
            "quantity": i + 1,
            "unit_price": round(12.0 + i * 4.5, 2),
            "weight_per_unit_kg": round(0.4 + i * 0.15, 2),
        }
        for i in range(int(num_items))
    ]
    if cat == "b2b":
        return {
            "external_order_id": f"B2B-{ts}",
            "source": "erp",
            "customer_category": "b2b",
            "request_type": "b2b",
            "customer_name": "Acme Wholesale — Procurement",
            "customer_email": "procurement@acme.example",
            "shipping_address": "200 Industrial Blvd, Logistics Park",
            "req_delivery_date": date.today().isoformat(),
            "origin": "main_warehouse",
            "destination": "Regional DC North",
            "items": items,
        }
    return {
        "external_order_id": f"B2C-{ts}",
        "source": "shopify",
        "customer_category": "b2c",
        "request_type": "b2c",
        "customer_name": "Jane Retail",
        "customer_email": "jane@example.com",
        "shipping_address": "48 Oak Street, River City",
        "req_delivery_date": date.today().isoformat(),
        "origin": "main_warehouse",
        "destination": "River City",
        "items": items,
    }


# ── Customer ──────────────────────────────────────────────────────────────────

with col_customer:
    with st.container(border=True):
        st.markdown("**End customer** — *read-only*")
        n_items = st.number_input("SKUs in cart", 1, 5, 2, key="lr_num_items")
        live = st.checkbox("Auto-refresh 2s", value=True, key="lr_live_checkbox")
        if not live and lr.get("order_id") and st.button("Refresh", use_container_width=True, key="lr_manual_refresh"):
            st.rerun()

        if st.button("Place order", type="primary", use_container_width=True, key="lr_place_order"):
            lr["last_error"] = None
            payload = _build_order_payload(flow, n_items)
            code, body = api.create_order(base, payload)
            if code == 201 and isinstance(body, dict):
                lr["order_id"] = body.get("sale_order_id")
                lr["external_order_id"] = body.get("external_order_id")
                lr["order_snapshot"] = body
                lr["shipment_id"] = str(body["delivery_order_id"]) if body.get("delivery_order_id") else None
                lr["order_items"] = list(payload["items"])
                lr["driver_step"] = 0
                lr["outcome_mode"] = outcome
                st.rerun()
            else:
                lr["last_error"] = (code, body)
                st.error(f"Failed ({code})")
                if isinstance(body, dict):
                    st.json(body)

        if lr.get("last_error") and not lr.get("order_id"):
            st.caption("Check API URL or duplicate order id.")

        if lr.get("outcome_mode") == "cancel" and lr.get("order_id"):
            co_can, od_can = api.get_order(base, str(lr["order_id"]))
            st_can = (od_can.get("status") or "").lower() if co_can == 200 and isinstance(od_can, dict) else ""
            if st_can == "cancelled":
                st.info("This order is **cancelled**.")
            elif st_can in ("in_transit", "delivered"):
                st.caption("Cancel is no longer allowed (in transit or delivered). Place a new order and cancel earlier.")
            elif st_can == "exception":
                st.caption("Order is already in **exception** — pick **Failure — driver exception** to demo that path.")
            elif st_can in ("pending", "confirmed", "allocated", "packed"):
                if st.button("Cancel this order", type="secondary", use_container_width=True, key="lr_cancel_order"):
                    cx, cb = api.cancel_order(base, str(lr["order_id"]))
                    if cx == 200:
                        st.success("Cancellation accepted.")
                        st.rerun()
                    else:
                        st.error(f"{cx}")
                        if isinstance(cb, dict):
                            st.json(cb)

        frag_interval = timedelta(seconds=2) if live else None

        @st.fragment(run_every=frag_interval)
        def _customer_feed():
            _base = st.session_state.api_base
            _lr = st.session_state.live_roles
            st.markdown(_story_line(_lr))
            oid = _lr.get("order_id")
            if not oid:
                st.caption("Start with **Place order**.")
                return

            oc, order = api.get_order(_base, str(oid))
            if oc == 200 and isinstance(order, dict):
                _lr["order_snapshot"] = order
                sid = order.get("delivery_order_id")
                if sid:
                    _lr["shipment_id"] = str(sid)

            snap = _lr.get("order_snapshot") or {}
            ship_id = _lr.get("shipment_id")
            ship_st = "—"
            if ship_id:
                sc, ship = api.get_shipment(_base, ship_id)
                if sc == 200 and isinstance(ship, dict):
                    ship_st = str(ship.get("status", "—"))

            st.markdown(
                _render_status_block(
                    str(snap.get("status")) if snap.get("status") is not None else None,
                    ship_st if ship_st != "—" else None,
                    str(snap.get("external_order_id")) if snap.get("external_order_id") else None,
                ),
                unsafe_allow_html=True,
            )

            if ship_id:
                pred = _fetch_latest_prediction(ship_id)
                if pred:
                    h = pred["predicted_eta_hours"]
                    st.metric("Est. ETA (ML)", f"{h:.1f} hours")
                    st.caption(f"Model `{pred['model_version']}` · predicted at {pred['predicted_at']}")
                else:
                    st.caption(
                        "**ETA estimate:** not in database yet — runs after the ETA agent writes to `predictions` "
                        "(needs stream processor + ML pipeline up)."
                    )

                tc, tracking = api.get_tracking(_base, ship_id)
                if tc == 200 and isinstance(tracking, list) and tracking:
                    st.markdown(_render_tracking_timeline(tracking), unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div class="lr-tl-wrap"><div class="lr-tl-heading">Shipment timeline</div>'
                        "<p style=\"margin:0;font-size:0.82rem;opacity:0.75;\">No events yet — use "
                        "<strong>Driver</strong> milestones to add scans.</p></div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Shipment id appears after the pipeline consumes the order.")

        _customer_feed()

# ── Warehouse ───────────────────────────────────────────────────────────────

with col_wh:
    with st.container(border=True):
        st.markdown("**Warehouse** — *pick list*")
        if not lr.get("order_id"):
            st.caption("Waiting for an order.")
        else:
            items = lr.get("order_items") or []
            if not items:
                st.caption("Place order again to load lines.")
            else:
                rows = [
                    {
                        "SKU": it.get("sku", "—"),
                        "Product": it.get("product_name", "—"),
                        "Qty": it.get("quantity", "—"),
                        "Unit price": it.get("unit_price", "—"),
                    }
                    for it in items
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)

# ── Driver ────────────────────────────────────────────────────────────────────

with col_driver:
    with st.container(border=True):
        st.markdown("**Driver** — *milestones*")
        ship_id = lr.get("shipment_id")
        step = int(lr.get("driver_step") or 0)
        mode = str(lr.get("outcome_mode") or "success")

        order_live = ""
        if lr.get("order_id"):
            qo, qd = api.get_order(base, str(lr["order_id"]))
            if qo == 200 and isinstance(qd, dict):
                order_live = (qd.get("status") or "").lower()

        if not lr.get("order_id"):
            st.caption("Waiting for an order.")
        elif order_live == "cancelled":
            st.warning("Cancelled — no further driver events.")
        elif order_live == "exception":
            st.warning("Exception recorded — order is in **exception**, shipment **failed**.")
        elif mode == "cancel":
            st.caption("Customer-cancel run: use **Cancel this order** on the left before **in transit**.")
        elif not ship_id:
            st.caption("Waiting for shipment id (pipeline).")
        elif mode == "exception":
            reason = st.text_input("Notes", key="lr_exc_reason", placeholder="e.g. Vehicle breakdown")
            loc = (reason or "").strip() or "Incident on route"
            if st.button("Report delivery exception", type="primary", use_container_width=True, key="lr_exc_send"):
                code, body = api.push_shipment_status(base, ship_id, "exception", loc)
                if code == 202:
                    st.success("Exception status sent — check customer view.")
                    st.rerun()
                else:
                    st.error(f"{code}")
                    if isinstance(body, dict):
                        st.json(body)
        elif step >= len(DRIVER_STEPS):
            st.success("Route complete.")
        else:
            _, label, where = DRIVER_STEPS[step]
            if st.button(f"{label} · {where}", type="primary", use_container_width=True, key=f"lr_drv_{step}"):
                code, body = api.push_shipment_status(base, ship_id, DRIVER_STEPS[step][0], where)
                if code == 202:
                    lr["driver_step"] = step + 1
                    st.rerun()
                else:
                    st.error(f"{code}")
                    if isinstance(body, dict):
                        st.json(body)
            if step + 1 < len(DRIVER_STEPS):
                st.caption(f"Then: {DRIVER_STEPS[step + 1][1]}")
            with st.expander("Simulate failure (exception)"):
                sim = st.text_input("Reason", key="lr_exc_sim", placeholder="Optional detail")
                sim_loc = sim.strip() or "Demo exception"
                if st.button("Send exception status", key="lr_exc_sim_btn"):
                    ec, eb = api.push_shipment_status(base, ship_id, "exception", sim_loc)
                    if ec == 202:
                        st.success("Sent.")
                        st.rerun()
                    else:
                        st.error(f"{ec}")
                        if isinstance(eb, dict):
                            st.json(eb)
