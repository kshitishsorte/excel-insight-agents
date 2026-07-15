"""
Central configuration for the Excel Cleaning & Insights multi-agent app.

Hardware profile detected on the build machine:
    CPU : Intel i7-1165G7 (4 cores / 8 threads)
    RAM : 15.7 GB
    GPU : Intel Iris Xe (integrated, no usable dedicated VRAM) -> CPU-only inference
    Disk: E: with ~104 GB free

Model-tier decision (logged):
    No dedicated GPU, so inference is CPU-only on a 4-core laptop with 15.7 GB RAM.
    We started on the 3B tier for responsiveness, but the 3B cleaner cleaned poorly
    and — notably — tended to REGRESS when revising after verifier feedback. Since
    quality matters more than latency here, we upgraded to 7-8B (Tier B), using two
    genuinely different families so the Verifier is a real "fresh look":

        Correction + Insights + Chat : qwen2.5:7b-instruct   (Alibaba Qwen family)
        Verifier                     : llama3.1:8b           (Meta Llama family)

    Trade-off: each run is slower and, since both won't fit in RAM at once, Ollama
    swaps them in/out between verifier rounds (reload latency). To go back to the
    fast 3B tier, set the *_MODEL values below to qwen2.5:3b-instruct / llama3.2:3b.

All LLM calls run against a LOCAL Ollama server. No cloud / Anthropic APIs.
"""

import os

# --- Ollama connection -------------------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# --- Voice (offline STT + TTS) ----------------------------------------------
# Whisper (STT) via faster-whisper and Piper (TTS) run fully locally on CPU.
# Models live under VOICE_DIR (downloaded once from Hugging Face, then offline).
VOICE_DIR = os.environ.get("VOICE_MODELS_DIR", r"E:\LLM\voice")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")   # tiny.en < base.en < small.en
# Piper voice: the agent's (built-in, non-cloned) speaking voice.
PIPER_VOICE = os.environ.get("PIPER_VOICE", "en_US-lessac-medium")
# Spoken answers are kept short so CPU TTS stays responsive.
VOICE_BRIEF_CHARS = 500

# --- Model selection ---------------------------------------------------------
# The Correction and Insights agents share one model; the Verifier deliberately
# uses a different family so its review is genuinely independent.
#
# Upgraded from the 3B tier to 7-8B for materially better cleaning decisions and
# more reliable revisions (the 3B cleaner tended to regress when acting on the
# verifier's feedback). CPU-only, so these are slower and Ollama swaps the two
# families in/out of RAM between verifier rounds — accepted for the quality gain.
CLEANER_MODEL = "qwen2.5:7b-instruct"
INSIGHTS_MODEL = "qwen2.5:7b-instruct"
VERIFIER_MODEL = "llama3.1:8b"
# The chat assistant answers questions about a finished report + runs the analysis
# codegen. The stronger 7B also produces better/less-buggy pandas.
CHAT_MODEL = "qwen2.5:7b-instruct"

# True when the verifier truly uses a different model family than the cleaner.
# When hardware forces a single model, the orchestrator still isolates context.
VERIFIER_IS_DISTINCT_MODEL = VERIFIER_MODEL != CLEANER_MODEL

# --- Agent loop --------------------------------------------------------------
MAX_VERIFY_ITERATIONS = 3

# --- LLM call robustness -----------------------------------------------------
# Retries for malformed / schema-invalid JSON before a column is failed gracefully.
JSON_MAX_RETRIES = 2
# Per-call request timeout (seconds). On CPU, a 7-8B call includes loading ~5 GB
# into RAM (with a model swap between the cleaner and verifier) plus slow token
# generation, which can far exceed a few minutes. This MUST be large enough that a
# call never times out mid-clean — a timeout makes the pipeline fall back to safe
# defaults, which defeats the point of the verification. 30 min gives wide headroom.
LLM_TIMEOUT = 1800
# Keep a model resident between calls so consecutive same-model calls don't reload.
LLM_KEEP_ALIVE = "20m"
# Retries for transient connection/timeout failures, so a one-off blip never
# silently skips a cleaning or verification step (which would hurt accuracy).
LLM_TRANSIENT_RETRIES = 2
# Sampling: greedy (temperature 0) for maximum precision and determinism — we want
# the models to be factual and reproducible, not creative. top_p is also pinned low
# and we nudge against runaway repetition. These reduce hallucination.
LLM_TEMPERATURE = 0.0
LLM_TOP_P = 0.5
LLM_REPEAT_PENALTY = 1.1

# --- Profiling / data limits -------------------------------------------------
SAMPLE_VALUES_PER_COLUMN = 8          # sample values shown to the LLM per column
MAX_ROWS_FOR_PROFILING = 100_000      # cap rows scanned for profiling stats
HIGH_MISSING_THRESHOLD = 0.50         # >50% missing -> prefer drop/null over impute

# Placeholder tokens treated as "missing" during profiling (case-insensitive).
PLACEHOLDER_TOKENS = [
    "", "n/a", "na", "null", "none", "nan", "-", "--", "?", "??",
    "unknown", "unk", "missing", "not available", "not applicable",
    "#n/a", "nil", "tbd", ".",
]
