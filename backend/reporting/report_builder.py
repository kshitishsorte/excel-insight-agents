"""
Assemble the final report object the UI renders, and build a standalone HTML
export (self-contained, with embedded plotly charts).
"""

from __future__ import annotations

import datetime as _dt
import html
from typing import Any

import pandas as pd

import config


def build_overview(result) -> dict:
    """High-level numbers for the Overview tab."""
    dtype_changes = [
        {
            "column": r.name,
            "dtype_before": r.dtype_before,
            "dtype_after": r.dtype_after,
            "changed": r.dtype_before != r.dtype_after,
        }
        for r in result.clean_results
    ]
    n_dtype_changed = sum(1 for d in dtype_changes if d["changed"])
    total_imputed = sum(r.n_imputed for r in result.clean_results)
    total_rows_dropped = max((r.rows_dropped for r in result.clean_results), default=0)
    return {
        "rows_before": len(result.original_df),
        "rows_after": len(result.cleaned_df),
        "cols_before": result.original_df.shape[1],
        "cols_after": result.cleaned_df.shape[1],
        "n_dtype_changed": n_dtype_changed,
        "total_cells_imputed": total_imputed,
        "total_rows_dropped": total_rows_dropped,
        "dtype_changes": dtype_changes,
        "final_approved": result.final_approved,
        "n_rounds": len(result.verification_rounds),
        "column_failures": result.column_failures,
        "models": {
            "cleaner": config.CLEANER_MODEL,
            "verifier": config.VERIFIER_MODEL,
            "insights": config.INSIGHTS_MODEL,
            "verifier_distinct": config.VERIFIER_IS_DISTINCT_MODEL,
        },
    }


def cleaning_log_frame(result) -> pd.DataFrame:
    rows = []
    for r in result.clean_results:
        rows.append(
            {
                "column": r.name,
                "dtype: before → after": f"{r.dtype_before} → {r.dtype_after}",
                "missing% before": f"{r.pct_missing_before*100:.1f}%",
                "missing% after": f"{r.pct_missing_after*100:.1f}%",
                "strategy": r.strategy,
                "cells imputed": r.n_imputed,
                "values changed": r.values_changed,
                "rows dropped": r.rows_dropped,
                "finalized": r.note,
                "reasoning": r.reasoning,
            }
        )
    return pd.DataFrame(rows)


def missing_summary_frame(result) -> pd.DataFrame:
    rows = [
        {
            "column": r.name,
            "missing% before": round(r.pct_missing_before * 100, 1),
            "missing% after": round(r.pct_missing_after * 100, 1),
            "strategy": r.strategy,
        }
        for r in result.clean_results
    ]
    return pd.DataFrame(rows)


# --- standalone HTML export --------------------------------------------------
def build_html_report(result) -> str:
    """Self-contained HTML with tables, narrative, and embedded plotly charts."""
    overview = build_overview(result)
    parts: list[str] = []
    parts.append(_html_head())

    parts.append("<h1>Excel Cleaning &amp; Insights Report</h1>")
    parts.append(
        f"<p class='muted'>Generated {_dt.datetime.now():%Y-%m-%d %H:%M} · "
        f"Cleaner: <code>{html.escape(config.CLEANER_MODEL)}</code> · "
        f"Verifier: <code>{html.escape(config.VERIFIER_MODEL)}</code></p>"
    )

    # Overview
    parts.append("<h2>Overview</h2>")
    approved = "✅ approved" if overview["final_approved"] else "⚠️ not fully approved"
    parts.append(
        "<ul>"
        f"<li>Rows: {overview['rows_before']} → {overview['rows_after']}</li>"
        f"<li>Columns: {overview['cols_before']} → {overview['cols_after']}</li>"
        f"<li>Dtype changes: {overview['n_dtype_changed']}</li>"
        f"<li>Cells imputed: {overview['total_cells_imputed']}</li>"
        f"<li>Rows dropped: {overview['total_rows_dropped']}</li>"
        f"<li>Verification: {approved} after {overview['n_rounds']} round(s)</li>"
        "</ul>"
    )
    if overview["column_failures"]:
        parts.append(
            "<p class='warn'>Columns that fell back to a default plan (LLM failed): "
            + ", ".join(html.escape(c) for c in overview["column_failures"])
            + "</p>"
        )

    # Cleaning log
    parts.append("<h2>Cleaning Log</h2>")
    parts.append(_df_to_html(cleaning_log_frame(result)))

    # Verification history
    parts.append("<h2>Verification History</h2>")
    parts.append(_verification_html(result))
    if result.unresolved_issues:
        parts.append("<p class='warn'>Unresolved disagreements after the final round:</p>")
        parts.append(_issues_html(result.unresolved_issues))

    # Key insights (deterministic) + takeaways (LLM) + narrative + charts
    parts.append("<h2>Key Insights</h2>")
    parts.append(_findings_html(getattr(result, "findings", [])))

    takeaways = getattr(result, "takeaways", [])
    if takeaways:
        parts.append("<h3>Takeaways</h3><ul class='takeaways'>")
        for t in takeaways:
            parts.append(f"<li>{html.escape(t)}</li>")
        parts.append("</ul>")

    parts.append("<h2>EDA &amp; Insights</h2>")
    parts.append("<h3>Narrative</h3>")
    parts.append(f"<div class='narrative'>{_text_to_html(result.narrative)}</div>")

    # Embed charts. First figure carries the plotlyjs; the rest reuse it.
    include_js: Any = "cdn"
    try:
        import plotly.io as pio  # noqa: F401

        include_js = True  # inline the full plotly.js into the first chart => offline
    except Exception:  # noqa: BLE001
        include_js = False

    first = True
    for key, fig in result.charts.items():
        try:
            div = fig.to_html(
                full_html=False,
                include_plotlyjs=(include_js if first else False),
            )
            parts.append(div)
            first = False
        except Exception as exc:  # noqa: BLE001
            parts.append(f"<p class='warn'>Chart '{html.escape(key)}' could not render: {html.escape(str(exc))}</p>")

    if result.notes:
        parts.append("<h2>Run Notes</h2><ul>")
        for n in result.notes:
            parts.append(f"<li>{html.escape(n)}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)


_SEV_COLOR = {"info": "#4F46E5", "good": "#059669", "warn": "#D97706", "bad": "#DC2626"}


def _findings_html(findings: list[dict]) -> str:
    if not findings:
        return "<p class='muted'>No notable findings.</p>"
    cards = ["<div class='findings'>"]
    for f in findings:
        color = _SEV_COLOR.get(f.get("severity", "info"), "#4F46E5")
        cards.append(
            f"<div class='fcard' style='border-left-color:{color}'>"
            f"<div class='ftag'>{html.escape(f.get('category',''))}</div>"
            f"<div class='ftitle'>{html.escape(f.get('icon',''))} {html.escape(f.get('title',''))}</div>"
            f"<div class='fdetail'>{html.escape(f.get('detail',''))}</div>"
            "</div>"
        )
    cards.append("</div>")
    return "\n".join(cards)


def _verification_html(result) -> str:
    if not result.verification_rounds:
        return "<p>No verification rounds were recorded.</p>"
    out = []
    for vr in result.verification_rounds:
        status = "approved ✅" if vr.approved else "changes requested"
        if vr.error:
            status = f"verifier error: {html.escape(vr.error)}"
        out.append(f"<h3>Round {vr.round_no} — {status}</h3>")
        if vr.issues:
            out.append(_issues_html(vr.issues))
        if vr.revised_columns:
            out.append("<p class='muted'>Revised: " + ", ".join(html.escape(c) for c in vr.revised_columns) + "</p>")
        if not vr.issues and not vr.error:
            out.append("<p class='muted'>No issues flagged.</p>")
    return "\n".join(out)


def _issues_html(issues: list[dict]) -> str:
    rows = ["<table><tr><th>Column</th><th>Problem</th><th>Suggested fix</th></tr>"]
    for i in issues:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(i.get('column','')))}</td>"
            f"<td>{html.escape(str(i.get('problem','')))}</td>"
            f"<td>{html.escape(str(i.get('suggested_fix','')))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _df_to_html(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p class='muted'>(nothing to show)</p>"
    return df.to_html(index=False, escape=True, border=0, classes="data")


def _text_to_html(text: str) -> str:
    safe = html.escape(text or "")
    paras = [p.strip() for p in safe.split("\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paras)


def _html_head() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'>
<title>Excel Cleaning & Insights Report</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:1000px;
      margin:2rem auto;padding:0 1rem;color:#1a1a1a;line-height:1.5}
 h1{border-bottom:2px solid #444;padding-bottom:.3rem}
 h2{margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}
 table{border-collapse:collapse;width:100%;margin:.5rem 0;font-size:.9rem}
 th,td{border:1px solid #ccc;padding:.3rem .5rem;text-align:left;vertical-align:top}
 th{background:#f3f3f3}
 code{background:#f0f0f0;padding:.1rem .3rem;border-radius:3px}
 .muted{color:#777}.warn{color:#b00;font-weight:600}
 .narrative{background:#fafafa;border-left:3px solid #888;padding:.5rem 1rem}
 .findings{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.7rem;margin:.6rem 0}
 .fcard{background:#fff;border:1px solid #e2e8f0;border-left:4px solid #4F46E5;border-radius:10px;padding:.7rem .9rem}
 .ftag{font-size:.68rem;text-transform:uppercase;letter-spacing:.04em;color:#64748b;font-weight:600}
 .ftitle{font-weight:700;margin-top:.15rem}
 .fdetail{color:#475569;font-size:.88rem;margin-top:.25rem;line-height:1.45}
 ul.takeaways{background:#eef0ff;border:1px solid #dde0ff;border-radius:10px;padding:.7rem 1rem .7rem 1.6rem}
 ul.takeaways li{margin:.3rem 0}
</style></head><body>"""
