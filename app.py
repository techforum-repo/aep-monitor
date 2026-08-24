from __future__ import annotations

import streamlit as st

from aep_monitor.config import harden_env_file
from aep_monitor.database import initialize
from aep_monitor.ui import (
    alerts_page,
    audit_page,
    cja_page,
    compare_page,
    datasets_page,
    dc_page,
    diagnostics_page,
    aep_page,
    overview,
    sdr_page,
    settings_page,
)
from aep_monitor.ui.shared import CUSTOM_CSS, init_session_state, render_hero, render_sidebar

initialize()
harden_env_file()
st.set_page_config(page_title="Adobe Experience Cloud Monitor", page_icon="📡", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

init_session_state()
page = render_sidebar()
render_hero()

PAGES = {
    "Overview": overview.render,
    "AEP Ingestion": aep_page.render,
    "Datasets": datasets_page.render,
    "Data Collection": dc_page.render,
    "CJA": cja_page.render,
    "Compare": compare_page.render,
    "SDR": sdr_page.render,
    "Audit Log": audit_page.render,
    "Alerts": alerts_page.render,
    "Diagnostics": diagnostics_page.render,
    "Settings": settings_page.render,
}
PAGES[page]()
