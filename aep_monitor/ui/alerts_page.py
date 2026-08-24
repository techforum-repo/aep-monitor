from __future__ import annotations

import streamlit as st

from .. import database


def render() -> None:
    st.markdown("### Alerts")
    st.caption(
        "Generated from the latest refresh of each product's page (or from poller_cli.py on a schedule). "
        "An alert clears itself automatically once its condition is no longer present on the next refresh."
    )

    tab_open, tab_resolved = st.tabs(["Open", "Resolved"])

    with tab_open:
        open_alerts = database.list_alerts(resolved=False, limit=200)
        if open_alerts.empty:
            st.success("🟢 Nothing open.")
        else:
            for _, row in open_alerts.iterrows():
                icon = "🔴" if row["severity"] == "critical" else "🟡"
                with st.container(border=True):
                    st.markdown(f"{icon} **{row['title']}**")
                    if row["message"]:
                        st.caption(row["message"])
                    st.caption(f"{row['source']} · opened {row['created_at']}")
                    if st.button("Mark resolved", key=f"resolve_{row['id']}"):
                        database.resolve_alert(int(row["id"]))
                        st.rerun()

    with tab_resolved:
        resolved_alerts = database.list_alerts(resolved=True, limit=100)
        if resolved_alerts.empty:
            st.caption("No resolved alerts yet.")
        else:
            st.dataframe(
                resolved_alerts[["created_at", "source", "severity", "title", "resolved_at"]],
                use_container_width=True, hide_index=True,
            )
