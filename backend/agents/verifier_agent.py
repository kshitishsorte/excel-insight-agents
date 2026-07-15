"""
Agent 2 - Verifier Agent.

Gives a genuinely INDEPENDENT review of Agent 1's cleaning decisions:
  * Runs on a DIFFERENT model family than Agent 1/3 (config.VERIFIER_MODEL).
  * Receives ONLY cold data: the original column profiles + Agent 1's *decisions*
    (dtype, strategy, resulting missing %). Agent 1's REASONING TEXT is withheld,
    so the verifier forms its own judgement rather than agreeing with a rationale.
  * Every call is stateless (agents/base.py), so no chain-of-thought leaks in.

It is prompted to actively hunt for problems, not rubber-stamp.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

import config
from agents import base


class VerifierIssue(BaseModel):
    column: str
    problem: str
    suggested_fix: str


class VerifierVerdict(BaseModel):
    approved: bool
    issues: list[VerifierIssue] = Field(default_factory=list)


SYSTEM_PROMPT = """You are an independent data-quality reviewer. Another system \
produced a cleaning plan for a dataset. Your job is to critically audit that plan \
against the raw column statistics and flag anything wrong. You are NOT here to \
approve by default - look hard for mistakes.

You are given, per column: the original profile (dtype, sample values, % missing, \
unique count, placeholder tokens found, and numeric stats incl. skewness and \
outliers) and the plan's DECISIONS ONLY (chosen dtype, tokens treated as missing, \
imputation strategy, and resulting missing %). You are deliberately NOT told the \
planner's reasoning - judge the decisions on their merits.

Flag a column when you find any of:
- Wrong dtype (e.g. a numeric column called categorical, a date called text, an \
ID with many uniques imputed as if numeric).
- Imputation mismatched to the distribution: mean used on a clearly skewed \
(|skewness| > ~1) or outlier-heavy numeric column (median is more appropriate); \
mean/median used on a non-numeric column.
- Placeholder tokens that were found in the profile but NOT included in \
treat_as_missing (so junk like "N/A" would survive), or legitimate values wrongly \
treated as missing.
- Imputing a column that is mostly missing (>~50%), where filling is misleading \
and leave_null/drop_row would be safer.
- Inconsistent categories left unmerged: if the original profile shows \
case_variants > 0 (values that differ only by case/whitespace, e.g. "DELHI" vs \
"delhi"), the column MUST be marked categorical so those spellings get standardized. \
If such a column was NOT marked categorical, flag it with suggested_fix \
"use corrected_dtype='categorical'".

If every decision is sound, approve. Otherwise list concrete issues with a \
specific suggested_fix (e.g. "use fill_median instead of fill_mean").

Return ONLY JSON: {"approved": true|false, "issues": [{"column":..., \
"problem":..., "suggested_fix":...}]}"""


def build_review_payload(
    profiles_for_llm: list[dict],
    decisions: list,  # list[ColumnDecision]
    results_by_name: dict,  # name -> ColumnCleanResult (for resulting missing %)
) -> list[dict]:
    """
    Assemble the cold-data review payload. Crucially, we include the decision
    fields but NOT decision.reasoning.
    """
    prof_by_name = {p["name"]: p for p in profiles_for_llm}
    payload = []
    for d in decisions:
        prof = prof_by_name.get(d.name, {})
        res = results_by_name.get(d.name)
        payload.append(
            {
                "column": d.name,
                "original_profile": prof,
                "decision": {
                    "corrected_dtype": d.corrected_dtype,
                    "treat_as_missing": d.treat_as_missing,
                    "strategy": d.strategy,
                    "fill_constant": d.fill_constant,
                    # resulting missing % after execution, no reasoning text:
                    "resulting_pct_missing": (res.pct_missing_after if res else None),
                    "resulting_dtype": (res.dtype_after if res else None),
                },
            }
        )
    return payload


def review(review_payload: list[dict]) -> VerifierVerdict:
    user = (
        "Audit the following cleaning decisions. Remember: you are NOT given the "
        "planner's reasoning on purpose.\n\n"
        + json.dumps({"columns": review_payload}, indent=2, default=str)
        + "\n\nReturn your verdict JSON."
    )
    verifier_precision = (
        "\n\nBE PRECISE. Only flag a column when the profile numbers you were given "
        "clearly justify the problem — cite the number (e.g. skew, % missing, dtype). "
        "Do NOT invent issues or flag a decision that is already sound; if everything "
        "checks out, approve. A wrong flag makes the cleaner change a correct decision."
    )
    return base.call_json(
        config.VERIFIER_MODEL, SYSTEM_PROMPT + verifier_precision, user, VerifierVerdict
    )
