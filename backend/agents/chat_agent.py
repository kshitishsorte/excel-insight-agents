"""
Chat Agent — answers the user's questions about a finished analysis.

Grounding contract:
  * It is given ONLY the computed report (overview stats, per-column cleaning
    decisions + reasoning, verifier history, EDA numbers, narrative) — never the
    raw dataframe.
  * It must answer from those numbers. If asked for something the report does not
    contain (e.g. a fresh calculation on the raw data), it says so rather than
    inventing a figure.
  * Stateless streaming: the FULL message list (system + stored history + new
    question) is rebuilt every turn and passed to Ollama; no server-side session.
"""

from __future__ import annotations

import config
from agents import base

SYSTEM_TEMPLATE = """You are the analysis assistant for a local spreadsheet-cleaning \
tool. A multi-agent pipeline has already cleaned a dataset and produced the report \
below. Answer the user's questions about THIS analysis.

Ground rules:
- Use ONLY the facts in the report below. Quote the actual numbers, column names, \
strategies and reasoning from it.
- If the user asks for something the report does not contain — a new statistic, a \
value for a specific row, a calculation that wasn't run — say plainly that the \
report doesn't include it and, if useful, suggest what would be needed. Do NOT \
invent or estimate numbers.
- Be concise and direct. Prefer specifics ("median was used for income because its \
skew was 9.1") over generic explanations.
- Plain text, no markdown headers. Short paragraphs or tight bullets are fine.

===== ANALYSIS REPORT =====
{report_context}
===== END REPORT ====="""


def build_messages(report_context: str, history: list[dict]) -> list[dict]:
    """Fresh message list every call: system(report) + full prior turns."""
    system = {
        "role": "system",
        "content": SYSTEM_TEMPLATE.format(report_context=report_context) + base.PRECISION_RULE,
    }
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    return [system] + turns


_BRIEF = (
    " IMPORTANT: this answer will be read aloud, so keep it to 1-2 short spoken "
    "sentences. Lead with the answer, state the key number, no lists or markdown."
)


def stream_answer(report_context: str, history: list[dict], brief: bool = False):
    """Yield answer tokens for the latest user turn already present in `history`."""
    messages = build_messages(report_context, history)
    if brief:
        messages[0]["content"] += _BRIEF
    yield from base.stream_chat(config.CHAT_MODEL, messages)
