"""Shared sidebar layout and styles for Streamlit test-ui pages."""

from __future__ import annotations

import streamlit as st


def inject_sidebar_styles() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            border-inline-end: 1px solid rgba(100, 116, 139, 0.2);
        }
        section[data-testid="stSidebar"] > div {
            background: var(--secondary-background-color);
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1.1rem !important;
            padding-bottom: 1.5rem !important;
        }
        .sc-sidebar-brand {
            font-size: 0.62rem;
            font-weight: 700;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: #64748b;
            margin: 0 0 0.2rem 0;
        }
        .sc-sidebar-title {
            font-size: 1.05rem;
            font-weight: 650;
            line-height: 1.3;
            margin: 0 0 0.5rem 0;
            color: var(--text-color, #0f172a);
        }
        .sc-side-hint {
            display: block;
            font-size: 0.72rem;
            line-height: 1.4;
            color: #64748b;
            margin: 0 0 0.45rem 0;
        }
        .sc-conn {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.55rem 0.8rem;
            border-radius: 10px;
            font-size: 0.84rem;
            font-weight: 550;
            margin: 0.35rem 0 0.85rem 0;
        }
        .sc-conn-ok {
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.32);
            color: #0d9488;
        }
        .sc-conn-bad {
            background: rgba(244, 63, 94, 0.1);
            border: 1px solid rgba(244, 63, 94, 0.28);
            color: #e11d48;
        }
        .sc-conn-ping {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: currentColor;
            box-shadow: 0 0 0 2px rgba(255,255,255,0.35);
            flex-shrink: 0;
        }
        .sc-side-section {
            font-size: 0.68rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #94a3b8;
            margin: 0.85rem 0 0.35rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_brand(*, page_title: str, tag: str = "Supply chain · demo UI") -> None:
    st.sidebar.markdown(
        f'<p class="sc-sidebar-brand">{tag}</p>'
        f'<p class="sc-sidebar-title">{page_title}</p>',
        unsafe_allow_html=True,
    )


def sidebar_connection_hint() -> None:
    st.sidebar.markdown(
        '<span class="sc-side-hint">FastAPI root URL (no path). In Docker use '
        "<code>http://api:8000</code>; on the host use <code>http://localhost:8000</code>.</span>",
        unsafe_allow_html=True,
    )


def sidebar_section_backend() -> None:
    st.sidebar.markdown('<p class="sc-side-section">Backend</p>', unsafe_allow_html=True)


def sidebar_section_actions() -> None:
    st.sidebar.markdown('<p class="sc-side-section">Session</p>', unsafe_allow_html=True)


def sidebar_api_status(*, connected: bool) -> None:
    if connected:
        st.sidebar.markdown(
            '<div class="sc-conn sc-conn-ok">'
            '<span class="sc-conn-ping"></span>'
            "<span>API reachable</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.sidebar.markdown(
            '<div class="sc-conn sc-conn-bad">'
            '<span class="sc-conn-ping"></span>'
            "<span>API unreachable</span>"
            "</div>",
            unsafe_allow_html=True,
        )
