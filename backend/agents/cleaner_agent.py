"""
Agent 1 - Data Correction Agent.

Responsibilities:
  * Given deterministic column profiles, decide (via LLM) a cleaning PLAN per
    column: corrected dtype, which tokens count as missing, and an imputation
    strategy + one-sentence reasoning.
  * The LLM only PLANS. All actual dataframe transformations are executed
    deterministically in plain pandas (see pipeline/execute.py).

Per-column failures (invalid JSON after retries) are surfaced, not fatal: the
orchestrator falls back to a safe default plan and flags the column.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

import config
from agents import base

DType = Literal["numeric", "integer", "categorical", "datetime", "boolean", "text"]
Strategy = Literal[
    "drop_row", "leave_null", "fill_mean", "fill_median",
    "fill_mode", "fill_constant", "forward_fill",
]


# Small models often emit synonyms for the canonical enum values. Normalise them
# BEFORE Literal validation so a valid decision isn't rejected over vocabulary.
_DTYPE_SYNONYMS = {
    "string": "text", "str": "text", "object": "text", "obj": "text",
    "float": "numeric", "double": "numeric", "number": "numeric",
    "numerical": "numeric", "decimal": "numeric", "continuous": "numeric",
    "int": "integer", "int64": "integer", "whole": "integer",
    "category": "categorical", "cat": "categorical", "factor": "categorical",
    "nominal": "categorical", "date": "datetime", "timestamp": "datetime",
    "time": "datetime", "bool": "boolean", "binary": "boolean",
}
_STRATEGY_SYNONYMS = {
    "mean": "fill_mean", "average": "fill_mean",
    "median": "fill_median", "mode": "fill_mode", "most_frequent": "fill_mode",
    "constant": "fill_constant", "fill": "fill_constant", "fill_value": "fill_constant",
    "null": "leave_null", "none": "leave_null", "keep_null": "leave_null",
    "leave": "leave_null", "nothing": "leave_null", "keep": "leave_null",
    "drop": "drop_row", "dropna": "drop_row", "remove": "drop_row", "delete": "drop_row",
    "ffill": "forward_fill", "forward": "forward_fill", "forwardfill": "forward_fill",
}


class ColumnDecision(BaseModel):
    name: str
    corrected_dtype: DType
    treat_as_missing: list[str] = Field(default_factory=list)
    strategy: Strategy
    fill_constant: Optional[str] = None   # used only when strategy == fill_constant
    reasoning: str = ""

    @field_validator("treat_as_missing", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v]

    @field_validator("corrected_dtype", mode="before")
    @classmethod
    def _norm_dtype(cls, v):
        if isinstance(v, str):
            key = v.strip().lower()
            return _DTYPE_SYNONYMS.get(key, key)
        return v

    @field_validator("strategy", mode="before")
    @classmethod
    def _norm_strategy(cls, v):
        if isinstance(v, str):
            key = v.strip().lower()
            return _STRATEGY_SYNONYMS.get(key, key)
        return v

    @field_validator("fill_constant", mode="before")
    @classmethod
    def _stringify_constant(cls, v):
        return None if v is None else str(v)


class CleanerPlan(BaseModel):
    columns: list[ColumnDecision]


SYSTEM_PROMPT = """You are a meticulous data-cleaning planner.
You receive a JSON profile of every column in a tabular dataset (dtype, sample \
values, % missing, unique counts, detected placeholder tokens, and for \
numeric-looking columns min/max/mean/median/mode/skewness/outliers).

Decide, for EACH column, a cleaning plan. You only plan; you never see or edit \
raw rows.

Rules you must follow:
- corrected_dtype is one of: numeric, integer, categorical, datetime, boolean, text.
- treat_as_missing lists any placeholder tokens (e.g. "N/A", "-", "?", "unknown", \
empty string) that should be converted to missing before imputation. Use the \
placeholder_tokens_found hints.
- strategy is one of: drop_row, leave_null, fill_mean, fill_median, fill_mode, \
fill_constant, forward_fill.
- For NUMERIC/INTEGER columns: use fill_mean for roughly symmetric data, but \
fill_median when the column is skewed (|skewness| > ~1) or has outliers, because \
the median is more robust.
- For CATEGORICAL/BOOLEAN/TEXT columns: use fill_mode (or fill_constant like \
"Unknown" when a distinct missing category is meaningful). Never use mean/median \
on non-numeric columns.
- When a column is more than ~50% missing, prefer leave_null or drop_row over \
imputation, because imputing would be misleading.
- A column with a small set of repeated labels is CATEGORICAL even when its \
casing/whitespace is inconsistent — e.g. "DELHI", "delhi", " Delhi " are the same \
city. The profile flags this as case_variants / case_variant_examples. Mark such \
columns categorical; their inconsistent spellings are then standardized to one form \
automatically. Do NOT leave them as text.
- The `reasoning` MUST be a concrete justification, citing the actual numbers from \
the profile, that explains BOTH decisions:
  (a) why this dtype, and
  (b) the missing-value handling — why THIS strategy over the alternatives AND why \
you fill vs. leave blank. E.g. "17% missing and right-skewed (skew 9.1) with \
outliers, so fill with the median — robust to the tail — rather than the mean; \
imputing is fine at only 17% missing." Do not give a vague one-liner; name the \
numbers that drove the choice.

Return ONLY JSON of the form:
{"columns":[{"name":..., "corrected_dtype":..., "treat_as_missing":[...], \
"strategy":..., "fill_constant": null, "reasoning":"..."}]}"""


REVISION_SYSTEM_PROMPT = """You are a meticulous data-cleaning planner making a \
MINIMAL, targeted correction after an independent reviewer flagged a problem.

For each column you are given: its profile, your CURRENT decision, and the specific \
issue + suggested fix. Change ONLY what the issue calls for and keep everything else \
in the current decision EXACTLY as it is. Do not "improve" fields that were not \
flagged — that has caused regressions before.

Rules:
- If the reviewer's suggested fix is sound, apply it and change nothing else.
- Only override the suggestion if it is clearly wrong (e.g. it would use mean/median \
on a non-numeric column, or impute a >50%-missing column); then pick the correct \
option and say why in one sentence.
- Keep the same corrected_dtype unless the issue is specifically about the dtype.
- Valid dtypes: numeric, integer, categorical, datetime, boolean, text. Valid \
strategies: drop_row, leave_null, fill_mean, fill_median, fill_mode, fill_constant, \
forward_fill.

Return ONLY JSON: {"columns":[{"name":..., "corrected_dtype":..., \
"treat_as_missing":[...], "strategy":..., "fill_constant": null, "reasoning":"..."}]}"""


def plan_cleaning(profiles_for_llm: list[dict]) -> CleanerPlan:
    """Initial full-dataset planning pass."""
    import json

    user = (
        "Column profiles:\n"
        + json.dumps({"columns": profiles_for_llm}, indent=2, default=str)
        + "\n\nReturn the cleaning plan JSON for every column."
    )
    return base.call_json(config.CLEANER_MODEL, SYSTEM_PROMPT + base.PRECISION_RULE, user, CleanerPlan)


def revise_cleaning(
    flagged_profiles_for_llm: list[dict],
    issues: list[dict],
    prior_decisions: list[dict] | None = None,
) -> CleanerPlan:
    """Targeted revision pass - only the flagged columns are re-planned.

    `prior_decisions` are the cleaner's CURRENT decisions for the flagged columns;
    passing them lets the model make a minimal change (fix only what was flagged)
    instead of re-deriving from scratch and regressing untouched fields.
    """
    import json

    user = (
        "Profiles of the columns needing revision:\n"
        + json.dumps({"columns": flagged_profiles_for_llm}, indent=2, default=str)
        + "\n\nYour CURRENT decision for each of these columns (change only what the "
        "issue calls for):\n"
        + json.dumps({"current_decisions": prior_decisions or []}, indent=2, default=str)
        + "\n\nReviewer issues to address:\n"
        + json.dumps({"issues": issues}, indent=2, default=str)
        + "\n\nReturn a cleaning plan JSON containing ONLY these columns, changing "
        "only what each issue requires."
    )
    return base.call_json(
        config.CLEANER_MODEL, REVISION_SYSTEM_PROMPT + base.PRECISION_RULE, user, CleanerPlan
    )


def default_decision(profile_for_llm: dict) -> ColumnDecision:
    """Safe deterministic fallback when the LLM fails for a column."""
    p = profile_for_llm
    if p.get("looks_numeric"):
        skew = p.get("skewness") or 0.0
        strat = "fill_median" if abs(skew) > 1 or p.get("n_outliers", 0) > 0 else "fill_mean"
        dtype = "numeric"
    elif p.get("looks_datetime"):
        dtype, strat = "datetime", "leave_null"
    elif p.get("looks_boolean"):
        dtype, strat = "boolean", "fill_mode"
    else:
        dtype, strat = "categorical" if p.get("n_unique", 0) <= max(20, 0.5 * p.get("n_total", 1)) else "text", "fill_mode"
    if p.get("pct_missing", 0) > config.HIGH_MISSING_THRESHOLD:
        strat = "leave_null"
    return ColumnDecision(
        name=p["name"],
        corrected_dtype=dtype,
        treat_as_missing=p.get("placeholder_tokens_found", []),
        strategy=strat,
        reasoning="Fallback default plan (LLM did not return a valid decision).",
    )
