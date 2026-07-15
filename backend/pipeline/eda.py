"""
Deterministic EDA (pandas/numpy/scipy — NO LLM) plus plotly chart builders.

Everything numeric is computed here. The Insights agent only narrates these
numbers; it never computes or invents a statistic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


@dataclass
class EDAResult:
    n_rows: int
    n_cols: int
    numeric_cols: list[str]
    categorical_cols: list[str]
    datetime_cols: list[str]
    describe: dict                       # column -> stat -> value
    pearson: Optional[dict] = None       # nested dict matrix
    spearman: Optional[dict] = None
    top_correlations: list[dict] = field(default_factory=list)
    categorical_distributions: dict = field(default_factory=dict)
    outlier_summary: dict = field(default_factory=dict)
    skewness: dict = field(default_factory=dict)


def _numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.select_dtypes(include=[np.number])


def compute_eda(df: pd.DataFrame, top_n: int = 5) -> EDAResult:
    numeric_df = _numeric_frame(df)
    numeric_cols = list(numeric_df.columns)
    datetime_cols = list(df.select_dtypes(include=["datetime", "datetimetz"]).columns)
    categorical_cols = [
        c for c in df.columns if c not in numeric_cols and c not in datetime_cols
    ]

    describe = {}
    if numeric_cols:
        desc = numeric_df.describe().replace({np.nan: None})
        describe = {c: desc[c].to_dict() for c in numeric_cols}

    skewness = {}
    outlier_summary = {}
    for c in numeric_cols:
        s = numeric_df[c].dropna()
        if len(s) >= 3:
            skewness[c] = _round(scipy_stats.skew(s))
        if len(s) >= 4:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                n_out = int(((s < low) | (s > high)).sum())
                outlier_summary[c] = {
                    "n_outliers": n_out,
                    "pct": _round(100 * n_out / len(s)),
                    "low_bound": _round(low),
                    "high_bound": _round(high),
                }

    pearson = spearman = None
    top_correlations: list[dict] = []
    if len(numeric_cols) >= 2:
        pear = numeric_df.corr(method="pearson")
        spear = numeric_df.corr(method="spearman")
        pearson = _matrix_to_dict(pear)
        spearman = _matrix_to_dict(spear)
        top_correlations = _top_correlations(numeric_df, pear, top_n)

    categorical_distributions = {}
    for c in categorical_cols:
        vc = df[c].astype("object").value_counts(dropna=True).head(10)
        if not vc.empty:
            categorical_distributions[c] = {
                "top_values": {str(k): int(v) for k, v in vc.items()},
                "n_unique": int(df[c].nunique(dropna=True)),
            }

    return EDAResult(
        n_rows=len(df),
        n_cols=df.shape[1],
        numeric_cols=numeric_cols,
        categorical_cols=categorical_cols,
        datetime_cols=datetime_cols,
        describe=describe,
        pearson=pearson,
        spearman=spearman,
        top_correlations=top_correlations,
        categorical_distributions=categorical_distributions,
        outlier_summary=outlier_summary,
        skewness=skewness,
    )


def _top_correlations(numeric_df: pd.DataFrame, pear: pd.DataFrame, top_n: int) -> list[dict]:
    cols = list(pear.columns)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            r = pear.iloc[i, j]
            if pd.isna(r):
                continue
            # significance via scipy on the pairwise-complete data
            sub = numeric_df[[a, b]].dropna()
            p = None
            if len(sub) >= 3:
                try:
                    _, p = scipy_stats.pearsonr(sub[a], sub[b])
                except Exception:  # noqa: BLE001
                    p = None
            pairs.append(
                {
                    "col_a": a,
                    "col_b": b,
                    "pearson": _round(r),
                    "abs": abs(float(r)),
                    "p_value": _round(p) if p is not None else None,
                    "n": len(sub),
                }
            )
    pairs.sort(key=lambda d: d["abs"], reverse=True)
    for d in pairs:
        d.pop("abs", None)
    return pairs[:top_n]


def _matrix_to_dict(m: pd.DataFrame) -> dict:
    return {
        str(r): {str(c): _round(m.loc[r, c]) for c in m.columns} for r in m.index
    }


def _round(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


# --- plotly chart builders ---------------------------------------------------
def build_charts(df: pd.DataFrame, eda: EDAResult) -> dict:
    """Return a dict of {chart_key: plotly Figure}. Import plotly lazily."""
    import plotly.express as px
    import plotly.graph_objects as go

    charts: dict = {}

    # Correlation heatmap
    if eda.pearson and len(eda.numeric_cols) >= 2:
        mat = pd.DataFrame(eda.pearson).reindex(index=eda.numeric_cols, columns=eda.numeric_cols)
        fig = px.imshow(
            mat, text_auto=".2f", aspect="auto", color_continuous_scale="RdBu",
            zmin=-1, zmax=1, title="Pearson correlation heatmap",
        )
        charts["corr_heatmap"] = fig

    # Histograms for highest-variance numeric columns
    if eda.numeric_cols:
        variances = df[eda.numeric_cols].var(numeric_only=True).sort_values(ascending=False)
        for col in list(variances.index)[:3]:
            fig = px.histogram(df, x=col, nbins=30, title=f"Distribution of {col}")
            charts[f"hist_{col}"] = fig

    # Bar charts for top categorical columns
    cat_sorted = sorted(
        eda.categorical_distributions.items(),
        key=lambda kv: kv[1]["n_unique"],
    )
    for col, info in cat_sorted[:3]:
        tv = info["top_values"]
        fig = px.bar(
            x=list(tv.keys()), y=list(tv.values()),
            labels={"x": col, "y": "count"}, title=f"Top values of {col}",
        )
        charts[f"bar_{col}"] = fig

    # Scatter plots for top correlated numeric pairs
    for pair in eda.top_correlations[:3]:
        a, b = pair["col_a"], pair["col_b"]
        fig = px.scatter(
            df, x=a, y=b, trendline=None,
            title=f"{a} vs {b} (r={pair['pearson']})",
        )
        charts[f"scatter_{a}_{b}"] = fig

    return charts
