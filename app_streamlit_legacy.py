"""
RETIRED — legacy Streamlit entrypoint, kept as a reference only.

The app is now a FastAPI backend + React frontend (see backend/ and frontend/,
run with `uvicorn backend.main:app`). The shared modules this file imports
(config, agents, pipeline, reporting, utils) were MOVED into backend/, so this
script no longer runs as-is; to revive it you would point these imports at
backend/ (e.g. add backend/ to sys.path). It remains here purely as a reference
for the original single-process UI behaviour.

Everything still runs locally against Ollama. No cloud LLM calls.
"""

from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st

import config
from agents import base
from utils import excel_io
from pipeline import orchestrator
from reporting import report_builder
from ui import theme

st.set_page_config(
    page_title="Excel Cleaning & Insights",
    page_icon="🧹",
    layout="wide",
)

# Global look-and-feel + clean Plotly template.
st.markdown(theme.inject_global_css(), unsafe_allow_html=True)
theme.apply_plotly_template()


# --- helpers -----------------------------------------------------------------
def _load_dataframe(upload, sheet):
    return excel_io.load_sheet(upload, sheet)


def _plot(fig, key):
    # theme=None keeps our custom template; force the font explicitly so it wins
    # over Streamlit's injected default.
    fig.update_layout(
        template="insight_clean",
        font=dict(family=theme.FONT_STACK, size=13, color=theme.PALETTE["ink"]),
        title_font=dict(family=theme.FONT_STACK, size=15, color=theme.PALETTE["ink"]),
    )
    st.plotly_chart(fig, use_container_width=True, key=key, theme=None)


# --- Hero --------------------------------------------------------------------
verifier_mode = "different families" if config.VERIFIER_IS_DISTINCT_MODEL else "isolated context"
st.markdown(
    theme.hero(
        "Excel Cleaner & Insights",
        "Upload a messy spreadsheet. A Correction agent fixes data types and missing "
        "values, an independent Verifier agent reviews the work over up to three rounds, "
        "and an Insights agent runs the EDA and draws the key findings — all on your "
        "machine, fully offline.",
        [
            ("Correction / Insights", config.CLEANER_MODEL, False),
            ("Verifier", f"{config.VERIFIER_MODEL} · {verifier_mode}", False),
            ("Runtime", "local Ollama", True),
        ],
    ),
    unsafe_allow_html=True,
)

# Server health check up front.
ok, msg = base.check_server()
if not ok:
    st.error(msg)
    st.stop()

# --- Upload ------------------------------------------------------------------
st.markdown(theme.section("Upload", "xlsx / xls · multi-sheet supported"), unsafe_allow_html=True)
uploaded = st.file_uploader("Upload an Excel workbook", type=["xlsx", "xls"], label_visibility="collapsed")

if uploaded is None:
    st.info("Awaiting an `.xlsx` / `.xls` upload. Generate a test file with "
            "`python sample_data/generate_messy_sample.py`.")
    st.stop()

try:
    sheets = excel_io.list_sheets(uploaded)
except excel_io.ExcelLoadError as exc:
    st.error(f"Could not read this workbook: {exc}")
    st.stop()

sheet = sheets[0]
if len(sheets) > 1:
    sheet = st.selectbox("This workbook has multiple sheets — pick one:", sheets)

try:
    df_preview = _load_dataframe(uploaded, sheet)
except excel_io.ExcelLoadError as exc:
    st.error(str(exc))
    st.stop()

st.markdown(
    theme.section("Raw data", f"{df_preview.shape[0]} rows · {df_preview.shape[1]} columns"),
    unsafe_allow_html=True,
)
st.dataframe(df_preview.head(20), use_container_width=True, height=280)

run = st.button("🚀  Run Analysis", type="primary")

if not run:
    st.stop()

# --- Run the pipeline with live status --------------------------------------
status_box = st.status("Starting the multi-agent pipeline…", expanded=True)


def progress_cb(phase: str, message: str):
    status_box.update(label=message)
    status_box.write(message)


try:
    with st.spinner("Running local models — CPU inference can take a few minutes…"):
        result = orchestrator.run_pipeline(df_preview, progress=progress_cb)
    status_box.update(label="Pipeline complete", state="complete", expanded=False)
except base.OllamaUnreachableError:
    status_box.update(label="Ollama unreachable", state="error")
    st.error(
        "Lost connection to the Ollama server mid-run. Make sure it is running "
        f"(`ollama serve`) at {config.OLLAMA_HOST} and retry."
    )
    st.stop()
except Exception as exc:  # noqa: BLE001
    status_box.update(label="Pipeline failed", state="error")
    st.error(f"The pipeline hit an unexpected error: {exc}")
    with st.expander("Traceback"):
        st.code(traceback.format_exc())
    st.stop()


# --- Report ------------------------------------------------------------------
overview = report_builder.build_overview(result)

if result.final_approved:
    st.markdown(
        theme.badge(f"✓  Verifier approved after {overview['n_rounds']} round(s)", "good"),
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        theme.badge(
            f"⚠  Verifier did not fully approve after {overview['n_rounds']} round(s) — "
            "latest cleaning kept, see Verification History",
            "warn",
        ),
        unsafe_allow_html=True,
    )

st.write("")
tab_insights, tab_overview, tab_log, tab_verify, tab_eda, tab_download = st.tabs(
    ["💡 Key Insights", "📋 Overview", "🧾 Cleaning Log", "🔍 Verification History",
     "📊 EDA & Charts", "⬇️ Download"]
)

# ---- Key Insights (lead tab) ----
with tab_insights:
    st.markdown(
        theme.section("What the data tells us", "exact figures, drawn deterministically from the EDA"),
        unsafe_allow_html=True,
    )
    if result.findings:
        st.markdown(theme.insight_cards(result.findings), unsafe_allow_html=True)
    else:
        st.info("No notable findings were derived.")

    if result.takeaways:
        st.markdown(theme.section("Actionable takeaways", f"drafted by {config.INSIGHTS_MODEL}"),
                    unsafe_allow_html=True)
        st.markdown(theme.takeaways_block(result.takeaways), unsafe_allow_html=True)

    st.markdown(theme.section("Narrative summary"), unsafe_allow_html=True)
    st.write(result.narrative)

# ---- Overview ----
with tab_overview:
    st.markdown(theme.section("At a glance"), unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", overview["rows_after"], delta=overview["rows_after"] - overview["rows_before"])
    c2.metric("Columns", overview["cols_after"])
    c3.metric("Types corrected", overview["n_dtype_changed"])
    c4.metric("Cells imputed", overview["total_cells_imputed"])
    if overview["total_rows_dropped"]:
        st.caption(f"{overview['total_rows_dropped']} row(s) dropped by drop_row strategies.")

    if overview["column_failures"]:
        st.warning(
            "These columns fell back to a safe default plan because the LLM did not "
            "return valid JSON for them: " + ", ".join(overview["column_failures"])
        )

    st.markdown(theme.section("Missing-value handling"), unsafe_allow_html=True)
    st.dataframe(report_builder.missing_summary_frame(result), use_container_width=True)

    st.markdown(theme.section("Type changes"), unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(overview["dtype_changes"]), use_container_width=True)

# ---- Cleaning Log ----
with tab_log:
    st.markdown(theme.section("Cleaning log", "before / after per column, and which round finalized it"),
                unsafe_allow_html=True)
    st.dataframe(report_builder.cleaning_log_frame(result), use_container_width=True)

# ---- Verification History ----
with tab_verify:
    st.markdown(theme.section("Independent review", f"up to {config.MAX_VERIFY_ITERATIONS} rounds"),
                unsafe_allow_html=True)
    if not config.VERIFIER_IS_DISTINCT_MODEL:
        st.caption("Hardware constrained the verifier to the same model as the cleaner, "
                   "but it runs with fully isolated context (no shared reasoning).")
    for vr in result.verification_rounds:
        if vr.error:
            st.error(f"Round {vr.round_no}: verifier error — {vr.error}")
            continue
        header = f"Round {vr.round_no} — " + ("✓ approved" if vr.approved else f"{len(vr.issues)} issue(s), changes requested")
        with st.expander(header, expanded=not vr.approved):
            if vr.issues:
                st.dataframe(pd.DataFrame(vr.issues), use_container_width=True)
            else:
                st.write("No issues flagged.")
            if vr.revised_columns:
                st.caption("Revised columns: " + ", ".join(vr.revised_columns))
    if result.unresolved_issues:
        st.error("Unresolved disagreements after the final round:")
        st.dataframe(pd.DataFrame(result.unresolved_issues), use_container_width=True)
    if result.notes:
        with st.expander("Run notes"):
            for n in result.notes:
                st.write("• " + n)

# ---- EDA & Charts ----
with tab_eda:
    eda = result.eda
    st.markdown(theme.section("Charts"), unsafe_allow_html=True)
    if not result.charts:
        st.info("Not enough numeric/categorical structure to build charts.")
    for key, fig in result.charts.items():
        _plot(fig, key)

    with st.expander("Top correlated pairs (Pearson)"):
        if eda.top_correlations:
            st.dataframe(pd.DataFrame(eda.top_correlations), use_container_width=True)
        else:
            st.write("Fewer than two numeric columns — no correlations computed.")

    with st.expander("Descriptive statistics"):
        if eda.describe:
            st.dataframe(pd.DataFrame(eda.describe), use_container_width=True)
        else:
            st.write("No numeric columns to describe.")

# ---- Download ----
with tab_download:
    st.markdown(theme.section("Export"), unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        cleaned_bytes = excel_io.dataframe_to_xlsx_bytes(result.cleaned_df, sheet_name=sheet)
        st.download_button(
            "⬇️  Cleaned Excel (.xlsx)",
            data=cleaned_bytes,
            file_name="cleaned_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col_b:
        html_report = report_builder.build_html_report(result)
        st.download_button(
            "⬇️  Full report (.html)",
            data=html_report.encode("utf-8"),
            file_name="cleaning_insights_report.html",
            mime="text/html",
            use_container_width=True,
        )
    st.markdown(theme.section("Cleaned data preview"), unsafe_allow_html=True)
    st.dataframe(result.cleaned_df.head(30), use_container_width=True)
