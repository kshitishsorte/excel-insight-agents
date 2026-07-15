"""
Deterministic execution of a cleaning plan (pure pandas — NO LLM).

The LLM decides the plan (agents/cleaner_agent.py); this module performs every
actual transformation and records a detailed before/after cleaning report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

import config
from agents.cleaner_agent import ColumnDecision


@dataclass
class ColumnCleanResult:
    name: str
    dtype_before: str
    dtype_after: str
    pct_missing_before: float
    pct_missing_after: float
    strategy: str
    corrected_dtype: str
    values_changed: int          # placeholders->NaN + imputed cells
    n_imputed: int
    rows_dropped: int
    reasoning: str
    flagged: bool = False        # True when a fallback/failed plan was used
    note: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


@dataclass
class CleanOutcome:
    df: pd.DataFrame
    results: list[ColumnCleanResult] = field(default_factory=list)


def _to_missing(series: pd.Series, tokens: list[str]) -> tuple[pd.Series, int]:
    """Replace listed tokens (and native placeholders) with NaN. Return count."""
    token_set = {str(t).strip().lower() for t in tokens}
    # Always fold the global placeholder set too, so a missed token is still caught.
    token_set |= set(config.PLACEHOLDER_TOKENS)

    def is_token(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, float) and np.isnan(v):
            return False  # already NaN, not a *changed* value
        return str(v).strip().lower() in token_set

    mask = series.map(is_token)
    changed = int(mask.sum())
    out = series.copy()
    out[mask] = np.nan
    return out, changed


def _cast(series: pd.Series, dtype: str) -> pd.Series:
    if dtype in ("numeric", "integer"):
        return pd.to_numeric(series, errors="coerce")
    if dtype == "datetime":
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.to_datetime(series, errors="coerce", format="mixed")
    if dtype == "boolean":
        return _to_boolean(series)
    # categorical / text -> keep as object strings (strip whitespace)
    return series.map(lambda v: v if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v).strip())


def _title_case(s: str) -> str:
    """Standardise a label to Title Case, e.g. "DELHI"/"delhi" -> "Delhi",
    "new york" -> "New York". Keeps a short ALL-CAPS token (<=3 chars, e.g. an
    acronym like "USA", "UK") as-is so it isn't mangled to "Usa"."""
    out = []
    for word in s.split():
        if word.isupper() and len(word) <= 3:
            out.append(word)          # keep short acronyms
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def _canonicalize_categories(series: pd.Series) -> tuple[pd.Series, int]:
    """Standardise categorical text so values that differ only by case/whitespace
    collapse to ONE consistent, Title-Cased spelling — e.g. "DELHI", "delhi",
    " Delhi " all become "Delhi", and "CHENNAI"/"chennai" become "Chennai". This
    gives a uniform result rather than picking whichever spelling was most common.
    Returns (series, number_of_values_changed).
    """
    mask = series.notna()
    stripped = series[mask].astype(str).str.strip()
    if stripped.empty:
        return series, 0
    new_vals = stripped.map(_title_case)
    n_changed = int((new_vals.to_numpy() != stripped.to_numpy()).sum())
    out = series.copy()
    out.loc[mask] = new_vals
    return out, n_changed


def _to_boolean(series: pd.Series) -> pd.Series:
    true_set = {"true", "yes", "y", "1", "t"}
    false_set = {"false", "no", "n", "0", "f"}

    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        s = str(v).strip().lower()
        if s in true_set:
            return True
        if s in false_set:
            return False
        return np.nan

    return series.map(conv)


def _impute(series: pd.Series, strategy: str, dtype: str, fill_constant) -> tuple[pd.Series, int]:
    missing_mask = series.isna()
    n_missing = int(missing_mask.sum())
    if n_missing == 0 or strategy in ("leave_null", "drop_row"):
        return series, 0

    out = series.copy()
    if strategy == "fill_mean":
        val = pd.to_numeric(series, errors="coerce").mean()
        out = out.fillna(val)
    elif strategy == "fill_median":
        val = pd.to_numeric(series, errors="coerce").median()
        out = out.fillna(val)
    elif strategy == "fill_mode":
        mode = series.mode(dropna=True)
        if not mode.empty:
            out = out.fillna(mode.iloc[0])
    elif strategy == "fill_constant":
        const = fill_constant if fill_constant is not None else ("Unknown" if dtype in ("categorical", "text") else 0)
        out = out.fillna(const)
    elif strategy == "forward_fill":
        out = out.ffill().bfill()

    imputed = int(missing_mask.sum() - out.isna().sum())
    return out, imputed


def _finalize_integer(series: pd.Series) -> pd.Series:
    """Cast a numeric series to a nullable integer dtype when it's whole-valued."""
    valid = series.dropna()
    if not valid.empty and (valid == valid.round()).all():
        try:
            return series.round().astype("Int64")
        except (TypeError, ValueError):
            return series
    return series


def execute_plan(df: pd.DataFrame, decisions: list[ColumnDecision]) -> CleanOutcome:
    """Apply every column decision deterministically and record the report."""
    work = df.copy()
    results: list[ColumnCleanResult] = []
    rows_to_drop = pd.Series(False, index=work.index)

    decision_by_name = {d.name: d for d in decisions}

    for col in list(work.columns):
        decision = decision_by_name.get(col)
        original = work[col]
        dtype_before = str(original.dtype)
        pct_missing_before = float(
            (original.isna() | original.map(_looks_placeholder)).mean()
        ) if len(original) else 0.0

        if decision is None:
            # No plan for this column: leave untouched but record it.
            results.append(
                ColumnCleanResult(
                    name=col, dtype_before=dtype_before, dtype_after=dtype_before,
                    pct_missing_before=round(pct_missing_before, 4),
                    pct_missing_after=round(pct_missing_before, 4),
                    strategy="none", corrected_dtype="unchanged",
                    values_changed=0, n_imputed=0, rows_dropped=0,
                    reasoning="No decision produced for this column.",
                    flagged=True, note="Column left unchanged.",
                )
            )
            continue

        # 1) placeholders -> NaN
        stepped, changed_missing = _to_missing(original, decision.treat_as_missing)

        eff_dtype = decision.corrected_dtype
        eff_strategy = decision.strategy
        override_note = ""   # a guard that CHANGED the dtype/strategy (drives reasoning)
        canon_note = ""      # additive: casing/whitespace standardization

        # 2) cast dtype, with a safety guard against destructive numeric casts.
        # If the LLM assigned a numeric/integer dtype to a column that is really
        # text (so coercion would turn most present values into NaN), we do NOT
        # silently destroy the data: keep it as text and flag the override.
        if eff_dtype in ("numeric", "integer"):
            trial = _cast(stepped, eff_dtype)
            present_before = int(stepped.notna().sum())
            present_after = int(trial.notna().sum())
            if present_before > 0 and (present_after / present_before) < 0.5:
                eff_dtype = "text"
                override_note = (
                    f"The column is not actually numeric (casting would lose "
                    f"{present_before - present_after}/{present_before} values), so it was "
                    "kept as text."
                )
                if eff_strategy in ("fill_mean", "fill_median"):
                    eff_strategy = "fill_mode"
                    override_note += " Imputed with the mode (text has no mean/median)."
                cast = _cast(stepped, eff_dtype)
            else:
                cast = trial
        else:
            cast = _cast(stepped, eff_dtype)

        # 2a) canonicalize categorical text: merge values that differ only by
        # case/whitespace (e.g. "DELHI", "delhi", " Delhi " -> one spelling) so
        # they aren't treated as separate categories. Uses the most common spelling.
        n_canonicalized = 0
        if eff_dtype == "categorical":
            cast, n_canonicalized = _canonicalize_categories(cast)
            if n_canonicalized:
                canon_note = (
                    f"Standardized {n_canonicalized} value(s) with inconsistent "
                    "casing/whitespace to a single Title-Cased spelling."
                )

        # 2b) guard: never impute a mostly-missing column — filling >50% of a
        # column with one value is misleading, so fall back to leave_null.
        _fill_strategies = ("fill_mean", "fill_median", "fill_mode", "fill_constant", "forward_fill")
        if eff_strategy in _fill_strategies and len(cast):
            miss_rate = float(cast.isna().mean())
            if miss_rate > config.HIGH_MISSING_THRESHOLD:
                eff_strategy = "leave_null"
                extra = (
                    f"{miss_rate*100:.0f}% of this column is missing — too much to impute "
                    "reliably, so the missing values were left as null (blank) rather than "
                    f"filled with a single '{decision.strategy}' value, which would be misleading."
                )
                override_note = (override_note + " " + extra).strip() if override_note else extra

        # 3) impute / drop
        if eff_strategy == "drop_row":
            rows_to_drop |= cast.isna()
            imputed_series, n_imputed = cast, 0
        else:
            imputed_series, n_imputed = _impute(
                cast, eff_strategy, eff_dtype, decision.fill_constant
            )

        if eff_dtype == "integer":
            imputed_series = _finalize_integer(imputed_series)

        work[col] = imputed_series

        pct_missing_after = float(work[col].isna().mean()) if len(work[col]) else 0.0
        # When a guard CHANGED the action, the planner's reasoning is now stale — use
        # the guard's (accurate) explanation as the justification instead, so the
        # reasoning always matches what was actually done. Canonicalization is
        # additive and kept in the note.
        final_reasoning = override_note.strip() if override_note else decision.reasoning
        # The override reason is now the reasoning; the note holds only the additive
        # canonicalization info (the orchestrator appends the "finalized in round N").
        note = canon_note
        results.append(
            ColumnCleanResult(
                name=col,
                dtype_before=dtype_before,
                dtype_after=str(work[col].dtype),
                pct_missing_before=round(pct_missing_before, 4),
                pct_missing_after=round(pct_missing_after, 4),
                strategy=eff_strategy,
                corrected_dtype=eff_dtype,
                values_changed=changed_missing + n_imputed + n_canonicalized,
                n_imputed=n_imputed,
                rows_dropped=0,  # filled in after row drop below
                reasoning=final_reasoning,
                flagged=bool(override_note or canon_note),
                note=note,
            )
        )

    # Apply row drops once, across all drop_row columns.
    n_dropped = int(rows_to_drop.sum())
    if n_dropped:
        work = work[~rows_to_drop].reset_index(drop=True)
        for r in results:
            if r.strategy == "drop_row":
                r.rows_dropped = n_dropped
                r.pct_missing_after = float(work[r.name].isna().mean()) if len(work) else 0.0

    return CleanOutcome(df=work, results=results)


def _looks_placeholder(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    return str(v).strip().lower() in config.PLACEHOLDER_TOKENS
