"""
Orchestrator - runs the full multi-agent workflow.

    profile (deterministic)
      -> Agent 1 plan  ->  execute (deterministic)  ->  Agent 2 review
         [repeat targeted revisions up to MAX_VERIFY_ITERATIONS]
      -> Agent 3 EDA (deterministic) + narrative (LLM)

Progress is reported through an optional callback so the Streamlit UI can show a
live status. The full per-round history is always recorded for the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

import config
from agents import base, cleaner_agent, verifier_agent, insights_agent
from agents.cleaner_agent import ColumnDecision
from pipeline import profiling, execute, eda as eda_mod
from reporting import findings as findings_mod

ProgressCB = Optional[Callable[[str, str], None]]  # (phase, message) -> None


@dataclass
class VerificationRound:
    round_no: int
    approved: bool
    issues: list[dict] = field(default_factory=list)
    revised_columns: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class PipelineResult:
    original_df: pd.DataFrame
    cleaned_df: pd.DataFrame
    profiles: list                      # list[ColumnProfile]
    clean_results: list                 # list[ColumnCleanResult]
    verification_rounds: list[VerificationRound]
    final_approved: bool
    unresolved_issues: list[dict]
    eda: eda_mod.EDAResult
    charts: dict
    narrative: str
    column_failures: list[str]          # columns where the LLM plan failed -> fallback
    findings: list[dict] = field(default_factory=list)     # deterministic key insights
    takeaways: list[str] = field(default_factory=list)     # LLM actionable takeaways
    notes: list[str] = field(default_factory=list)


def _emit(cb: ProgressCB, phase: str, msg: str) -> None:
    if cb is not None:
        cb(phase, msg)


_STRATEGIES = [
    "drop_row", "leave_null", "fill_mean", "fill_median",
    "fill_mode", "fill_constant", "forward_fill",
]
_DTYPES = ["numeric", "integer", "categorical", "datetime", "boolean", "text"]


def _drop_resolved_issues(issues: list[dict], decision_by_name: dict) -> list[dict]:
    """Filter out verifier issues that the current decision already satisfies.

    We read the RECOMMENDED value out of `suggested_fix` (the part before
    "instead of"/"rather than") and compare it to the live decision: if the
    cleaner already uses that strategy/dtype, the flag is stale — drop it.
    """
    import re

    kept = []
    for issue in issues:
        d = decision_by_name.get(issue.get("column"))
        if d is None:
            kept.append(issue)
            continue
        sugg = str(issue.get("suggested_fix", "")).lower()
        rec = re.split(r"instead of|rather than|\bnot\b", sugg)[0]  # the recommended part

        strat_targets = [s for s in _STRATEGIES if s in rec]
        if strat_targets and d.strategy in strat_targets:
            continue  # already using the recommended strategy
        dtype_targets = [t for t in _DTYPES if re.search(rf"\b{t}\b", rec)]
        if dtype_targets and d.corrected_dtype in dtype_targets:
            continue  # already the recommended dtype
        # treat_as_missing additions: if every quoted token is already handled, drop.
        tokens = re.findall(r"['\"]([^'\"]+)['\"]", issue.get("suggested_fix", ""))
        have = {t.strip().lower() for t in d.treat_as_missing}
        if tokens and all(t.strip().lower() in have for t in tokens):
            continue
        kept.append(issue)
    return kept


def _plan_with_fallback(profiles_for_llm: list[dict], notes: list[str], failures: list[str]) -> list[ColumnDecision]:
    """Run Agent 1; on total failure fall back to per-column safe defaults."""
    try:
        plan = cleaner_agent.plan_cleaning(profiles_for_llm)
        decisions_by_name = {d.name: d for d in plan.columns}
    except (base.LLMJSONError, base.OllamaUnreachableError) as exc:
        notes.append(f"Correction agent JSON failed for the full pass ({exc}); using safe defaults per column.")
        decisions_by_name = {}

    # Ensure every column has a decision; fill gaps with defaults.
    decisions: list[ColumnDecision] = []
    for p in profiles_for_llm:
        d = decisions_by_name.get(p["name"])
        if d is None:
            d = cleaner_agent.default_decision(p)
            failures.append(p["name"])
        decisions.append(d)
    return decisions


def run_pipeline(df: pd.DataFrame, progress: ProgressCB = None) -> PipelineResult:
    notes: list[str] = []
    column_failures: list[str] = []

    # --- Phase: deterministic profiling --------------------------------------
    _emit(progress, "profiling", "Profiling columns (dtypes, missing %, outliers)…")
    profiles = profiling.profile_dataframe(df)
    profiles_for_llm = [profiling.profile_for_llm(p) for p in profiles]
    prof_llm_by_name = {p["name"]: p for p in profiles_for_llm}

    # --- Phase: Agent 1 initial plan -----------------------------------------
    _emit(progress, "cleaning", f"Correction agent ({config.CLEANER_MODEL}) deciding a plan…")
    decisions = _plan_with_fallback(profiles_for_llm, notes, column_failures)

    # Execute the initial plan deterministically.
    outcome = execute.execute_plan(df, decisions)
    results_by_name = {r.name: r for r in outcome.results}

    # --- Phase: verification loop --------------------------------------------
    verification_rounds: list[VerificationRound] = []
    final_approved = False
    unresolved_issues: list[dict] = []

    for round_no in range(1, config.MAX_VERIFY_ITERATIONS + 1):
        _emit(
            progress, "verifying",
            f"Verifier ({config.VERIFIER_MODEL}) round {round_no}/{config.MAX_VERIFY_ITERATIONS} — reviewing decisions…",
        )
        payload = verifier_agent.build_review_payload(
            profiles_for_llm, decisions, results_by_name
        )
        try:
            verdict = verifier_agent.review(payload)
        except (base.LLMJSONError, base.OllamaUnreachableError) as exc:
            # Verifier itself failed: record and stop the loop (accept current work).
            verification_rounds.append(
                VerificationRound(round_no=round_no, approved=False, error=str(exc))
            )
            notes.append(f"Verifier call failed in round {round_no} ({exc}); proceeding with current cleaning.")
            break

        issues = [i.model_dump() for i in verdict.issues]
        # Drop flags the current decision already satisfies. The verifier (esp. at
        # temperature 0) tends to re-flag issues the cleaner already fixed, which
        # would otherwise keep the loop from ever converging and wrongly mark
        # correct columns as "unresolved".
        n_before = len(issues)
        issues = _drop_resolved_issues(issues, {d.name: d for d in decisions})
        if len(issues) < n_before:
            notes.append(
                f"Round {round_no}: discarded {n_before - len(issues)} verifier flag(s) already "
                "satisfied by the current cleaning."
            )
        vround = VerificationRound(round_no=round_no, approved=verdict.approved, issues=issues)

        if verdict.approved or not issues:
            vround.approved = True
            verification_rounds.append(vround)
            final_approved = True
            _emit(progress, "verifying", f"Verifier approved in round {round_no}. ✅")
            break

        _emit(
            progress, "verifying",
            f"Verifier round {round_no}/{config.MAX_VERIFY_ITERATIONS} — {len(issues)} issue(s) found, revising…",
        )

        # Last allowed round and still not approved -> stop, surface disagreement.
        if round_no == config.MAX_VERIFY_ITERATIONS:
            verification_rounds.append(vround)
            unresolved_issues = issues
            notes.append(
                f"Reached the {config.MAX_VERIFY_ITERATIONS}-round limit without approval; "
                "proceeding with the latest cleaning and surfacing the unresolved issues."
            )
            break

        # --- Targeted revision: only re-plan the flagged columns -------------
        flagged_cols = sorted({i["column"] for i in issues if i["column"] in prof_llm_by_name})
        vround.revised_columns = flagged_cols
        verification_rounds.append(vround)

        if not flagged_cols:
            # Issues reference unknown columns; nothing actionable -> accept.
            notes.append(f"Round {round_no} issues referenced unknown columns; nothing to revise.")
            unresolved_issues = issues
            break

        flagged_profiles = [prof_llm_by_name[c] for c in flagged_cols]
        # Give the cleaner its CURRENT decision for each flagged column so it makes
        # a minimal, targeted fix instead of re-deriving and regressing other fields.
        decision_by_name = {d.name: d for d in decisions}
        prior_decisions = [
            decision_by_name[c].model_dump() for c in flagged_cols if c in decision_by_name
        ]
        try:
            revised_plan = cleaner_agent.revise_cleaning(flagged_profiles, issues, prior_decisions)
            revised_by_name = {d.name: d for d in revised_plan.columns}
        except (base.LLMJSONError, base.OllamaUnreachableError) as exc:
            notes.append(f"Correction agent failed to revise round {round_no} ({exc}); keeping prior decisions.")
            revised_by_name = {}

        # Merge revised decisions over the existing set (untouched cols preserved).
        changed_any = False
        for idx, d in enumerate(decisions):
            if d.name in revised_by_name:
                decisions[idx] = revised_by_name[d.name]
                changed_any = True
        if not changed_any:
            notes.append(f"No columns were actually revised in round {round_no}.")

        # Re-execute the full plan deterministically and loop to re-verify.
        outcome = execute.execute_plan(df, decisions)
        results_by_name = {r.name: r for r in outcome.results}

    cleaned_df = outcome.df

    # --- Phase: Agent 3 EDA + narrative --------------------------------------
    _emit(progress, "insights", "Computing EDA statistics and charts…")
    eda_result = eda_mod.compute_eda(cleaned_df)
    charts = eda_mod.build_charts(cleaned_df, eda_result)

    _emit(progress, "insights", f"Insights agent ({config.INSIGHTS_MODEL}) writing the narrative…")
    narrative = insights_agent.narrate(eda_result)

    # Deterministic key insights (exact numbers), then LLM actionable takeaways.
    findings = findings_mod.derive_findings(
        eda_result, outcome.results, unresolved_issues, column_failures
    )
    _emit(progress, "insights", "Drawing key insights and takeaways…")
    takeaways = insights_agent.key_takeaways(findings_mod.findings_for_llm(findings))

    # Annotate which round finalized each column (last round that revised it).
    finalize_round = {}
    for vr in verification_rounds:
        for c in vr.revised_columns:
            finalize_round[c] = vr.round_no
    for r in outcome.results:
        r_round = finalize_round.get(r.name, 1)
        finalized = f"Finalized in round {r_round}."
        r.note = f"{finalized} {r.note}".strip() if r.note else finalized

    return PipelineResult(
        original_df=df,
        cleaned_df=cleaned_df,
        profiles=profiles,
        clean_results=outcome.results,
        verification_rounds=verification_rounds,
        final_approved=final_approved,
        unresolved_issues=unresolved_issues,
        eda=eda_result,
        charts=charts,
        narrative=narrative,
        column_failures=column_failures,
        findings=findings,
        takeaways=takeaways,
        notes=notes,
    )
