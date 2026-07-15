"""
Derive concrete, human-readable insights from the EDA + cleaning results.

This is fully deterministic (no LLM) so every stated number is exact. It powers
the "Key Insights" cards in the UI and the report, and also builds a compact
grounding payload for the LLM takeaways.
"""

from __future__ import annotations


def _pct(x: float) -> str:
    return f"{x*100:.0f}%" if x >= 0.1 or x == 0 else f"{x*100:.1f}%"


def derive_findings(eda, clean_results, unresolved_issues, column_failures) -> list[dict]:
    """Return a list of {category, icon, title, detail, severity} insight cards."""
    findings: list[dict] = []

    # ---- Overview ----------------------------------------------------------
    findings.append({
        "category": "Overview", "icon": "📐", "severity": "info",
        "title": "Dataset shape",
        "detail": (
            f"{eda.n_rows} rows × {eda.n_cols} columns after cleaning — "
            f"{len(eda.numeric_cols)} numeric, {len(eda.categorical_cols)} categorical, "
            f"{len(eda.datetime_cols)} datetime."
        ),
    })

    # ---- Data quality ------------------------------------------------------
    dtype_changed = [r for r in clean_results if r.dtype_before != r.dtype_after]
    if dtype_changed:
        names = ", ".join(r.name for r in dtype_changed[:4])
        more = f" (+{len(dtype_changed)-4} more)" if len(dtype_changed) > 4 else ""
        findings.append({
            "category": "Data quality", "icon": "🔧", "severity": "good",
            "title": f"{len(dtype_changed)} column type(s) corrected",
            "detail": f"Recast to their true types: {names}{more}.",
        })

    total_imputed = sum(r.n_imputed for r in clean_results)
    if total_imputed:
        imputed_cols = [r for r in clean_results if r.n_imputed > 0]
        findings.append({
            "category": "Data quality", "icon": "🩹", "severity": "info",
            "title": f"{total_imputed} missing cells filled",
            "detail": (
                f"Imputed across {len(imputed_cols)} column(s) using per-column "
                "strategies (median for skewed numerics, mode for categoricals)."
            ),
        })

    still_missing = [r for r in clean_results if r.pct_missing_after > 0.005]
    if still_missing:
        parts = ", ".join(f"{r.name} ({_pct(r.pct_missing_after)})" for r in still_missing[:4])
        findings.append({
            "category": "Data quality", "icon": "🕳️", "severity": "warn",
            "title": "Some columns intentionally left with nulls",
            "detail": (
                f"Left un-imputed because filling would mislead: {parts}. "
                "These were mostly-missing or not safely fillable."
            ),
        })

    guardrail = [r for r in clean_results if getattr(r, "flagged", False) and "Overrode" in (r.note or "")]
    if guardrail:
        findings.append({
            "category": "Data quality", "icon": "🛡️", "severity": "warn",
            "title": "Prevented a data-destroying cast",
            "detail": (
                f"{', '.join(r.name for r in guardrail)}: an assigned numeric type "
                "would have wiped the text values, so it was kept as text."
            ),
        })

    if column_failures:
        findings.append({
            "category": "Data quality", "icon": "⚠️", "severity": "warn",
            "title": "Columns handled by fallback rules",
            "detail": (
                f"{', '.join(column_failures)}: the model didn't return a valid plan, "
                "so safe deterministic defaults were applied."
            ),
        })

    # ---- Distributions -----------------------------------------------------
    skewed = sorted(
        ((c, s) for c, s in eda.skewness.items() if s is not None and abs(s) > 1),
        key=lambda kv: abs(kv[1]), reverse=True,
    )
    for c, s in skewed[:2]:
        direction = "right" if s > 0 else "left"
        findings.append({
            "category": "Distributions", "icon": "📈", "severity": "info",
            "title": f"‘{c}’ is heavily {direction}-skewed",
            "detail": (
                f"Skewness {s:.1f} — a long {direction} tail. The median was used "
                "for imputation rather than the mean, which the tail would distort."
            ),
        })

    outlier_cols = sorted(
        eda.outlier_summary.items(), key=lambda kv: kv[1]["n_outliers"], reverse=True,
    )
    for c, info in outlier_cols[:2]:
        if info["n_outliers"] > 0:
            findings.append({
                "category": "Distributions", "icon": "🎯", "severity": "warn",
                "title": f"‘{c}’ has {info['n_outliers']} outlier(s)",
                "detail": (
                    f"{info['pct']:.0f}% of values fall outside the IQR fence "
                    f"[{info['low_bound']:.0f}, {info['high_bound']:.0f}]. "
                    "Worth checking before averaging or modelling."
                ),
            })

    # ---- Relationships -----------------------------------------------------
    if eda.top_correlations:
        best = eda.top_correlations[0]
        r = best.get("pearson")
        if r is not None:
            ar = abs(r)
            sig = best.get("p_value")
            sig_txt = ""
            if sig is not None:
                sig_txt = " (statistically significant)" if sig < 0.05 else " (not statistically significant)"
            if ar >= 0.5:
                sev, strength = ("good", "a strong")
            elif ar >= 0.3:
                sev, strength = ("info", "a moderate")
            else:
                sev, strength = ("info", "only a weak")
            if ar < 0.3:
                findings.append({
                    "category": "Relationships", "icon": "🔗", "severity": "info",
                    "title": "No strong linear relationships",
                    "detail": (
                        f"The strongest pair, ‘{best['col_a']}’ vs ‘{best['col_b']}’, is "
                        f"only r = {r:.2f}{sig_txt}. The numeric columns move largely "
                        "independently."
                    ),
                })
            else:
                findings.append({
                    "category": "Relationships", "icon": "🔗", "severity": sev,
                    "title": f"{strength.capitalize()} correlation found",
                    "detail": (
                        f"‘{best['col_a']}’ vs ‘{best['col_b']}’: r = {r:.2f}{sig_txt} "
                        f"across {best.get('n','?')} rows."
                    ),
                })
    elif len(eda.numeric_cols) < 2:
        findings.append({
            "category": "Relationships", "icon": "🔗", "severity": "info",
            "title": "Not enough numeric columns to correlate",
            "detail": "At least two numeric columns are needed for a correlation analysis.",
        })

    # ---- Categories --------------------------------------------------------
    for c, info in list(eda.categorical_distributions.items()):
        tv = info.get("top_values", {})
        if not tv:
            continue
        total = sum(tv.values())
        top_label, top_count = next(iter(tv.items()))
        share = top_count / total if total else 0
        if share >= 0.6:
            findings.append({
                "category": "Categories", "icon": "📊", "severity": "warn",
                "title": f"‘{c}’ is imbalanced",
                "detail": (
                    f"‘{top_label}’ accounts for {_pct(share)} of values "
                    f"({info.get('n_unique','?')} categories total). A dominant class "
                    "can bias downstream analysis."
                ),
            })
        elif info.get("n_unique", 0) >= max(20, 0.5 * eda.n_rows):
            findings.append({
                "category": "Categories", "icon": "🏷️", "severity": "info",
                "title": f"‘{c}’ is high-cardinality",
                "detail": f"{info['n_unique']} distinct values — likely an identifier or free text.",
            })

    # ---- Unresolved verifier disagreement ----------------------------------
    if unresolved_issues:
        cols = ", ".join(sorted({i.get("column", "?") for i in unresolved_issues}))
        findings.append({
            "category": "Review", "icon": "⚖️", "severity": "bad",
            "title": "Unresolved cleaning disagreement",
            "detail": (
                f"After 3 review rounds the verifier still contested: {cols}. "
                "The latest cleaning was kept — see the Verification History tab."
            ),
        })

    return findings


def findings_for_llm(findings: list[dict]) -> list[dict]:
    """Trim findings to what the takeaways model needs."""
    return [{"category": f["category"], "point": f"{f['title']}: {f['detail']}"} for f in findings]
