"""
Analysis Agent — turns a data question into a real pandas computation.

Flow:
  1. Router/planner (LLM, JSON): decide whether the question needs a fresh
     computation on the cleaned data ("compute") or is about the cleaning/EDA
     already in the report ("report").
  2. If compute: the LLM writes a short pandas snippet that assigns the answer to
     `result`. We execute it against the cleaned DataFrame in a restricted
     namespace (pd/np/df only, no imports/files/network), retrying once with the
     error if it throws.
  3. The actual computed result is returned to the UI as a table/value, and a
     summariser LLM streams a plain-English answer stating the real numbers.

This keeps the offline, local-only contract: no code leaves the machine, and the
numbers come from pandas, not from the model's imagination.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

import config
from agents import base
from reporting.serialize import _clean

MAX_TABLE_ROWS = 50


class Plan(BaseModel):
    mode: Literal["compute", "report"]
    pandas_code: str = Field(default="")


class Code(BaseModel):
    pandas_code: str = Field(default="")


# --- Deterministic routing ---------------------------------------------------
# Small models misroute questions, so we decide the obvious cases with regex and
# only fall back to the LLM planner when genuinely ambiguous.
_REPORT_RE = re.compile(
    r"\b(why|how did you|what strategy|which strategy|reasoning|explain why|"
    r"imput\w*|strateg\w*|dtype|data type|verif\w*|"
    r"how many rounds|which round|placeholder\w*|narrative|"
    r"what did you (do|change|clean)|how was .* (cleaned|handled))\b",
    re.IGNORECASE,
)
_COMPUTE_RE = re.compile(
    r"\b(how many|how much|count\w*|number of|average\w*|means?|median\w*|sums?|totals?|"
    r"most|least|highest|lowest|max\w*|min\w*|top\s*\d*|bottom|rank\w*|"
    r"per |for each|by each|group\w*|breakdown|distribution\w*|correlat\w*|"
    r"percent\w*|proportion\w*|ratio|unique|value counts|"
    r"which \w+ (has|have|had|is|are|were)|by \w+)\b",
    re.IGNORECASE,
)


def classify(question: str) -> str:
    """Return 'report', 'compute', or 'unsure' from the question wording alone."""
    q = question.strip().lower()
    # "why ..." and explicit process wording => about the cleaning/report.
    if q.startswith("why") or _REPORT_RE.search(q):
        return "report"
    if _COMPUTE_RE.search(q):
        return "compute"
    return "unsure"


PLANNER_SYSTEM = """You route a user's question about a cleaned tabular dataset.

Decide one of two modes:
- "compute": the question needs a calculation, aggregation, ranking, filter, count,
  average, correlation, group-by, or any fresh number derived from the actual data
  (e.g. "which airline is delayed most?", "average income by city", "how many rows
  where X > 5", "top 5 ..."). Write pandas code to answer it.
- "report": the question is about the cleaning process, data types, missing-value
  strategy, verifier decisions, or the EDA already summarised. No new computation.

When mode is "compute", write `pandas_code` that:
- operates on a DataFrame named `df` (already loaded and cleaned),
- uses ONLY real column names from the schema given,
- assigns the final answer to a variable named `result` (a DataFrame, Series, or scalar),
- uses only pandas (pd) and numpy (np). NO imports, file access, network, or plots.
- Keep it short. Sort/round for readability. For "top/most" questions, sort and take head().

Return ONLY JSON: {"mode": "compute"|"report", "pandas_code": "..."}.
When mode is "report", set pandas_code to "".
"""

FIX_SYSTEM = """The pandas code you wrote raised an error. Rewrite it as ONE simple,
single-line statement that assigns the answer to `result`. No multi-line
expressions, ternaries, extra variables, or trailing indexing like [0]/['col'] on
a grouped result — return the small Series/DataFrame itself. Use only the real
columns in the schema and only pd/np/df.

Example: result = df.groupby('UniqueCarrier')['ArrDelay'].mean().sort_values(ascending=False).head(5)

Return ONLY JSON: {"mode":"compute","pandas_code":"..."}."""

SUMMARY_SYSTEM = """You are a data analyst. A pandas computation was just run on the
user's dataset to answer their question, and its result is given to you below.

State the answer directly and specifically, using the REAL numbers from the result.
Lead with the answer. Keep it to a few sentences. Do not show or mention code, and do
not invent anything beyond the result. If the result is empty or looks off, say so.
Plain text, no markdown headers."""


def build_schema(df: pd.DataFrame, max_cols: int = 60) -> str:
    """Compact column schema (name, dtype, a few sample values) for the planner."""
    lines = [f"{df.shape[0]} rows x {df.shape[1]} columns.", "Columns:"]
    for col in list(df.columns)[:max_cols]:
        s = df[col].dropna()
        samples = [str(v) for v in s.head(3).tolist()]
        lines.append(f"- {col} ({df[col].dtype}) e.g. {', '.join(samples) if samples else '(all missing)'}")
    return "\n".join(lines)


CODEGEN_SYSTEM = """Write pandas code to answer the user's question about a
DataFrame named `df` (already loaded and cleaned).

Rules:
- Use ONLY real column names from the schema given.
- Write ONE simple statement that assigns the answer to `result`. Keep it to a
  single line. Do NOT use multi-line expressions, ternaries, backslashes, or extra
  helper variables.
- Prefer returning a small Series or DataFrame that KEEPS the labels (e.g. the
  group-by result), not a bare number — so the answer keeps its context. For
  "top/most/least" sort and take .head().
- Use only pandas (pd) and numpy (np). NO imports, file access, network, or plots.

Good: result = df.groupby('UniqueCarrier')['ArrDelay'].mean().sort_values(ascending=False).head(5)

Return ONLY JSON: {"pandas_code": "..."}."""


def _plan_llm(question: str, schema: str, report_context: str) -> Plan:
    user = (
        f"Dataset schema:\n{schema}\n\n"
        f"(Existing report context, for deciding 'report' mode:)\n{report_context[:1500]}\n\n"
        f"User question: {question}\n\nReturn the routing JSON."
    )
    return base.call_json(config.CHAT_MODEL, PLANNER_SYSTEM, user, Plan)


def generate_code(question: str, schema: str) -> str:
    user = f"Dataset schema:\n{schema}\n\nQuestion: {question}\n\nReturn the pandas JSON."
    try:
        return base.call_json(config.CHAT_MODEL, CODEGEN_SYSTEM, user, Code).pandas_code
    except Exception:  # noqa: BLE001
        return ""


def decide(question: str, schema: str, report_context: str) -> tuple[str, str]:
    """Return (mode, pandas_code). Deterministic first, LLM planner only if unsure."""
    route = classify(question)
    if route == "report":
        return "report", ""
    if route == "compute":
        code = generate_code(question, schema)
        return ("compute", code) if code.strip() else ("report", "")
    # Ambiguous: let the LLM planner decide.
    try:
        plan = _plan_llm(question, schema, report_context)
    except Exception:  # noqa: BLE001
        return "report", ""
    if plan.mode == "compute" and plan.pandas_code.strip():
        return "compute", plan.pandas_code
    return "report", ""


def _fix_code(question: str, schema: str, code: str, error: str) -> str:
    user = (
        f"Schema:\n{schema}\n\nQuestion: {question}\n\n"
        f"Broken code:\n{code}\n\nError:\n{error}\n\nReturn corrected JSON."
    )
    try:
        return base.call_json(config.CHAT_MODEL, FIX_SYSTEM, user, Plan).pandas_code
    except Exception:  # noqa: BLE001
        return ""


_ALLOWED_BUILTINS = [
    "abs", "min", "max", "sum", "len", "round", "sorted", "range", "enumerate",
    "zip", "list", "dict", "set", "tuple", "str", "int", "float", "bool", "map",
    "filter", "any", "all", "reversed", "divmod", "print",
]


def _prep_df(df: pd.DataFrame) -> pd.DataFrame:
    """Analysis-friendly copy: coerce numeric-looking object columns to numbers so
    aggregations (mean/sum/...) work even if a column wasn't cast during cleaning."""
    d = df.copy()
    for c in d.columns:
        col = d[c]
        if (
            pd.api.types.is_numeric_dtype(col)
            or pd.api.types.is_datetime64_any_dtype(col)
            or pd.api.types.is_bool_dtype(col)
        ):
            continue
        conv = pd.to_numeric(col, errors="coerce")
        if len(col) and conv.notna().mean() >= 0.8:
            d[c] = conv
    return d


def _safe_globals(df: pd.DataFrame) -> dict:
    import builtins

    safe = {name: getattr(builtins, name) for name in _ALLOWED_BUILTINS if hasattr(builtins, name)}
    return {"__builtins__": safe, "pd": pd, "np": np, "df": _prep_df(df)}


def _strip_code(code: str) -> str:
    code = re.sub(r"```[a-zA-Z]*", "", code).replace("```", "")
    # Drop import lines — pd/np are already provided, imports are blocked anyway.
    kept = [ln for ln in code.splitlines() if not re.match(r"\s*(import|from)\s", ln)]
    return "\n".join(kept).strip()


def _compiles(code: str) -> bool:
    try:
        compile(code, "<analysis>", "exec")
        return True
    except SyntaxError:
        return False


def _balance_brackets(code: str) -> str:
    """Append missing closing brackets — the most common LLM syntax slip."""
    opens = {"(": ")", "[": "]", "{": "}"}
    closes = {")", "]", "}"}
    stack, quote = [], None
    for ch in code:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in opens:
            stack.append(ch)
        elif ch in closes and stack and opens[stack[-1]] == ch:
            stack.pop()
    return code + "".join(opens[c] for c in reversed(stack))


def _salvage_syntax(code: str) -> str | None:
    """Longest leading run of lines that still compiles (drops a broken trailer)."""
    lines = code.splitlines()
    for end in range(len(lines), 0, -1):
        prefix = "\n".join(lines[:end]).strip()
        if prefix and _compiles(prefix):
            return prefix
    return None


def _repair(code: str) -> str | None:
    """Return a compilable version of the code, trying a few cheap repairs."""
    for cand in (code, _balance_brackets(code), _salvage_syntax(code),
                 _salvage_syntax(_balance_brackets(code))):
        if cand and _compiles(cand):
            return cand
    return None


def run_code(df: pd.DataFrame, code: str):
    """Execute code, return (ok, result_obj, error, executed_code)."""
    cleaned = _strip_code(code)
    if not cleaned:
        return False, None, "No code to run.", cleaned
    repaired = _repair(cleaned)
    if repaired is None:
        return False, None, "SyntaxError: could not parse the generated code.", cleaned
    cleaned = repaired
    g = _safe_globals(df)
    local: dict = {}
    try:
        exec(cleaned, g, local)  # noqa: S102 - restricted namespace, local single-user tool
        if "result" in local:
            result = local["result"]
        elif "result" in g:
            result = g["result"]
        else:
            lines = [ln for ln in cleaned.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            result = eval(lines[-1], g, local) if lines else None  # noqa: S307
        return True, result, None, cleaned
    except Exception as exc:  # noqa: BLE001
        return False, None, f"{type(exc).__name__}: {exc}", cleaned


def result_payload(result) -> dict:
    """JSON-safe {table|value} for the UI."""
    if isinstance(result, pd.Series):
        result = result.rename("value").reset_index()
    if isinstance(result, pd.DataFrame):
        df = result.head(MAX_TABLE_ROWS)
        cols = [str(c) for c in df.columns]
        rows = [[_clean(v) for v in rec] for rec in df.itertuples(index=False, name=None)]
        return {"table": {"columns": cols, "rows": rows, "truncated": len(result) > MAX_TABLE_ROWS}, "value": None}
    if isinstance(result, (np.generic,)):
        result = result.item()
    return {"table": None, "value": None if result is None else str(result)}


def result_text(result) -> str:
    """Compact textual form of the result for the summariser LLM."""
    if isinstance(result, pd.Series):
        return result.head(20).to_string()
    if isinstance(result, pd.DataFrame):
        note = f"\n({len(result)} rows total)" if len(result) > 20 else ""
        return result.head(20).to_string() + note
    return str(result)


def stream_summary(question: str, result: object, brief: bool = False):
    """Yield tokens of a plain-English answer grounded in the computed result."""
    system = SUMMARY_SYSTEM + base.PRECISION_RULE
    if brief:
        system += (
            "\nThis will be read aloud: keep it to 1-2 short spoken sentences, "
            "lead with the answer and the key number, no lists."
        )
    user = (
        f"User question: {question}\n\n"
        f"Computed result:\n{result_text(result)}\n\n"
        "Answer the user's question using these numbers."
    )
    yield from base.stream_chat(config.CHAT_MODEL, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])


def compute(df: pd.DataFrame, question: str, schema: str, code: str, max_fixes: int = 3):
    """Run code, salvaging syntax errors and re-prompting on failure.
    Returns (ok, result, error, executed_code)."""
    ok, result, error, executed = run_code(df, code)
    if ok:
        return True, result, None, executed
    last_code, last_err = code, error
    for _ in range(max_fixes):
        fixed = _fix_code(question, schema, last_code, last_err or "")
        if not fixed.strip():
            break
        ok, result, error, executed = run_code(df, fixed)
        last_code, last_err = fixed, error
        if ok:
            return True, result, None, executed
    return False, None, last_err, executed
