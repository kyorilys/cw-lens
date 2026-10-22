"""Web UI.  Run with:  streamlit run app.py"""
import csv
import io

import streamlit as st

import logquery as lq

st.set_page_config(page_title="Log Search", layout="wide")
cfg = lq.load_config()

with st.sidebar:
    st.header("Settings")
    region = st.text_input("AWS region", cfg["region"])
    profile = st.text_input("AWS profile (optional)", cfg["profile"] or "")
    names = {k: v.get("label", k) for k, v in cfg["sources"].items()}
    source_key = st.radio("Logs", list(names) + ["custom"],
                          format_func=lambda k: names.get(k, "Custom log groups"))
    if source_key == "custom":
        groups_text = st.text_area("Log groups (one per line)")
        log_groups = [g.strip() for g in groups_text.splitlines() if g.strip()]
        saved = {}
    else:
        source = cfg["sources"][source_key]
        log_groups = source.get("log_groups", [])
        saved = source.get("saved_queries", {})
        st.caption("Log groups: " + ", ".join(log_groups))
    range_label = st.selectbox("Time range", list(lq.RANGES), index=1)

st.title(f"🔎 {names.get(source_key, 'Custom')} logs")

mode = st.radio("Mode", ["Simple search", "Saved query", "Advanced (Insights query)"],
                horizontal=True)
query = None
try:
    if mode == "Simple search":
        c1, c2, c3 = st.columns([4, 1, 1])
        term = c1.text_input("Search text (all words must match)",
                             placeholder="e.g. user@example.com or order 12345")
        level = c2.selectbox("Level", list(lq.LEVEL_PATTERNS))
        limit = c3.number_input("Max rows", 10, 10000, 200, step=50)
        query = lq.build_query(term, level, limit)
    elif mode == "Saved query":
        if not saved:
            st.info("No saved queries for this source. Add some in config.yaml.")
        else:
            name = st.selectbox("Query", list(saved))
            needs_term = "{term}" in saved[name]
            term = st.text_input("Search term") if needs_term else ""
            if not needs_term or term:
                query = lq.fill_template(saved[name], term)
    else:
        query = st.text_area("Logs Insights query", lq.build_query(), height=180)
except ValueError as e:
    st.warning(str(e))

if query:
    with st.expander("Query that will run"):
        st.code(query, language="sql")

if st.button("Run", type="primary", disabled=not query):
    start, end = lq.time_window(range_label)
    try:
        client = lq.make_client(region, profile or None)
        with st.spinner("Querying CloudWatch…"):
            rows = lq.run_query(client, log_groups, query, start, end)
    except Exception as e:  # show AWS/credential errors in the UI
        st.error(f"{type(e).__name__}: {e}")
    else:
        st.success(f"{len(rows)} rows")
        if rows:
            st.dataframe(rows, use_container_width=True, height=600)
            buf = io.StringIO()
            fields = sorted({k for r in rows for k in r})
            w = csv.DictWriter(buf, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
            st.download_button("Download CSV", buf.getvalue(), "logs.csv", "text/csv")
