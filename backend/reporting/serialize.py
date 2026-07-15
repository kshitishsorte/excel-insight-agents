"""
Serialize a PipelineResult into a JSON-safe report dict for the React frontend.

Reuses report_builder (overview, cleaning log, missing summary) so none of the
existing reporting logic is rewritten. Plotly figures are emitted with
`fig.to_json()` (dark-themed for the new UI) instead of `st.plotly_chart`.
"""

from __future__ import annotations

import json
import math
from typing import Any

from reporting import report_builder

# Dark Plotly styling matching the frontend design tokens.
_ACCENTS = ["#5B7FFF", "#9C6BFF", "#2DD9C4", "#F0A93B", "#EC6A9C", "#63B3ED"]
_DARK_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#C9C7D6", family="Inter, system-ui, sans-serif", size=12),
    title=dict(font=dict(color="#F1F0F5", size=14)),
    colorway=_ACCENTS,
    margin=dict(l=52, r=20, t=48, b=44),
    xaxis=dict(gridcolor="#2A2A38", zerolinecolor="#2A2A38", linecolor="#2A2A38"),
    yaxis=dict(gridcolor="#2A2A38", zerolinecolor="#2A2A38", linecolor="#2A2A38"),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)


def _clean(obj: Any) -> Any:
    """Recursively convert to JSON-safe values (NaN/inf -> None, numpy -> native)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    # numpy / pandas scalars
    try:
        import numpy as np

        if isinstance(obj, np.generic):
            return _clean(obj.item())
    except Exception:  # noqa: BLE001
        pass
    return str(obj)


def _frame_records(df) -> list[dict]:
    if df is None or df.empty:
        return []
    return _clean(df.to_dict(orient="records"))


def _charts_json(charts: dict) -> list[dict]:
    out = []
    for key, fig in charts.items():
        try:
            fig.update_layout(**_DARK_LAYOUT)
            fig.update_coloraxes(colorbar=dict(outlinewidth=0))
        except Exception:  # noqa: BLE001
            pass
        try:
            out.append({"key": key, "figure": json.loads(fig.to_json())})
        except Exception as exc:  # noqa: BLE001
            out.append({"key": key, "error": str(exc)})
    return out


def serialize_report(result) -> dict:
    """Full JSON-safe report payload."""
    overview = report_builder.build_overview(result)

    verification = {
        "final_approved": result.final_approved,
        "n_rounds": len(result.verification_rounds),
        "unresolved_issues": _clean(result.unresolved_issues),
        "rounds": [
            {
                "round_no": vr.round_no,
                "approved": vr.approved,
                "issues": _clean(vr.issues),
                "revised_columns": list(vr.revised_columns),
                "error": vr.error,
            }
            for vr in result.verification_rounds
        ],
        "notes": list(result.notes),
        "column_failures": list(result.column_failures),
    }

    eda = result.eda
    eda_payload = {
        "narrative": result.narrative,
        "findings": _clean(result.findings),
        "takeaways": list(result.takeaways),
        "numeric_cols": list(eda.numeric_cols),
        "categorical_cols": list(eda.categorical_cols),
        "datetime_cols": list(eda.datetime_cols),
        "top_correlations": _clean(eda.top_correlations),
        "skewness": _clean(eda.skewness),
        "outlier_summary": _clean(eda.outlier_summary),
        "describe": _clean(eda.describe),
        "charts": _charts_json(result.charts),
    }

    return {
        "overview": _clean(overview),
        "cleaning_log": _frame_records(report_builder.cleaning_log_frame(result)),
        "missing_summary": _frame_records(report_builder.missing_summary_frame(result)),
        "verification": verification,
        "eda": eda_payload,
    }


def report_context_for_chat(report: dict) -> str:
    """
    Compact, plain-text grounding of the report for the chat agent — stats,
    cleaning decisions, verifier history, EDA numbers. NEVER the raw dataframe.
    """
    ov = report.get("overview", {})
    lines: list[str] = []
    lines.append("=== DATASET OVERVIEW ===")
    lines.append(
        f"Rows: {ov.get('rows_before')} -> {ov.get('rows_after')}; "
        f"Columns: {ov.get('cols_before')} -> {ov.get('cols_after')}; "
        f"Type corrections: {ov.get('n_dtype_changed')}; "
        f"Cells imputed: {ov.get('total_cells_imputed')}; "
        f"Rows dropped: {ov.get('total_rows_dropped')}."
    )

    lines.append("\n=== PER-COLUMN CLEANING DECISIONS ===")
    for row in report.get("cleaning_log", []):
        lines.append(
            f"- {row.get('column')}: {row.get('dtype: before → after')}, "
            f"strategy={row.get('strategy')}, "
            f"missing {row.get('missing% before')}->{row.get('missing% after')}, "
            f"cells imputed={row.get('cells imputed')}. "
            f"Reasoning: {row.get('reasoning')}"
        )

    ver = report.get("verification", {})
    lines.append("\n=== VERIFIER REVIEW ===")
    lines.append(
        f"Final approved: {ver.get('final_approved')} after {ver.get('n_rounds')} round(s)."
    )
    for r in ver.get("rounds", []):
        issues = "; ".join(
            f"{i.get('column')}: {i.get('problem')} -> {i.get('suggested_fix')}"
            for i in r.get("issues", [])
        ) or "no issues"
        lines.append(f"Round {r.get('round_no')} (approved={r.get('approved')}): {issues}")
    if ver.get("unresolved_issues"):
        unresolved = "; ".join(
            f"{i.get('column')}: {i.get('problem')}" for i in ver["unresolved_issues"]
        )
        lines.append(f"UNRESOLVED disagreements: {unresolved}")

    eda = report.get("eda", {})
    lines.append("\n=== EDA ===")
    if eda.get("top_correlations"):
        lines.append("Top correlations:")
        for c in eda["top_correlations"]:
            lines.append(
                f"- {c.get('col_a')} vs {c.get('col_b')}: r={c.get('pearson')}, "
                f"p={c.get('p_value')}, n={c.get('n')}"
            )
    if eda.get("skewness"):
        lines.append("Skewness: " + ", ".join(f"{k}={v}" for k, v in eda["skewness"].items()))
    if eda.get("outlier_summary"):
        lines.append(
            "Outliers: "
            + ", ".join(f"{k}={v.get('n_outliers')} ({v.get('pct')}%)" for k, v in eda["outlier_summary"].items())
        )
    if eda.get("findings"):
        lines.append("Key findings:")
        for f in eda["findings"]:
            lines.append(f"- [{f.get('category')}] {f.get('title')}: {f.get('detail')}")
    if eda.get("narrative"):
        lines.append("\nNarrative summary:\n" + eda["narrative"])

    return "\n".join(lines)
