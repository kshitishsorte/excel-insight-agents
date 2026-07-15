"""
Shared Ollama call wrapper for all agents.

Design guarantees:
  * Every call is STATELESS. The full message list is rebuilt fresh on each
    invocation. We never append to a growing chat thread, so no agent can ever
    leak its private reasoning into a later call or into another agent.
  * JSON mode with pydantic validation and corrective re-prompting.
  * Graceful failure: after retries are exhausted the caller gets a structured
    error instead of a crash.
"""

from __future__ import annotations

import json
import time
from typing import Optional, Type, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)


# Reusable anti-hallucination clause appended to every generating agent's prompt.
PRECISION_RULE = (
    "\n\nBE PRECISE. Use ONLY the information given to you above. If something is not "
    "supported by that information, say you don't know or that the data doesn't cover "
    "it — do NOT guess, estimate, extrapolate, or invent numbers, columns, names, or "
    "facts. A correct \"I don't know\" is better than a confident wrong answer."
)


def _gen_options() -> dict:
    """Sampling options tuned for factual, low-hallucination output."""
    return {
        "temperature": config.LLM_TEMPERATURE,
        "top_p": getattr(config, "LLM_TOP_P", 0.9),
        "repeat_penalty": getattr(config, "LLM_REPEAT_PENALTY", 1.1),
    }


class OllamaUnreachableError(RuntimeError):
    """Raised when the local Ollama server cannot be contacted at all."""


class LLMJSONError(RuntimeError):
    """Raised when valid schema-conforming JSON could not be obtained."""


# A single shared client pointed at the local server. Stateless by construction:
# the client holds no conversation, we pass complete messages every call.
_client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)


def check_server() -> tuple[bool, str]:
    """Return (ok, message). Used by the UI to give a friendly error early."""
    try:
        _client.list()
        return True, "Ollama server reachable."
    except Exception as exc:  # noqa: BLE001 - surface any connection failure
        return False, (
            f"Could not reach the Ollama server at {config.OLLAMA_HOST}. "
            f"Start it (run `ollama serve` or open the Ollama app) and try again. "
            f"Details: {exc}"
        )


def _raw_chat(model: str, system: str, user: str, force_json: bool) -> str:
    """One stateless chat turn. Returns the assistant message content string.

    Transient failures (connection/timeout) are retried a few times with backoff
    so a one-off blip never silently skips a cleaning or verification step.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    attempts = getattr(config, "LLM_TRANSIENT_RETRIES", 2) + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = _client.chat(
                model=model,
                messages=messages,
                format="json" if force_json else "",
                options=_gen_options(),
                keep_alive=getattr(config, "LLM_KEEP_ALIVE", "5m"),
            )
            return resp["message"]["content"]
        except ollama.ResponseError as exc:
            # A model-level error (bad request) — not transient, don't retry.
            raise LLMJSONError(f"Ollama returned an error for model '{model}': {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            if _is_transient(exc):
                last_exc = exc
                if attempt < attempts - 1:
                    time.sleep(3 * (attempt + 1))  # 3s, 6s backoff
                    continue
                raise OllamaUnreachableError(str(exc)) from exc
            raise LLMJSONError(str(exc)) from exc
    raise OllamaUnreachableError(str(last_exc))  # pragma: no cover


def _is_transient(exc: Exception) -> bool:
    """True for connection/timeout-style errors (as opposed to bad output)."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "timeout" in name
        or "connect" in name
        or any(s in msg for s in ("timed out", "timeout", "connect", "refused", "read operation"))
    )


def call_text(model: str, system: str, user: str) -> str:
    """Plain (non-JSON) stateless text completion, e.g. the insights narrative."""
    return _raw_chat(model, system, user, force_json=False).strip()


def stream_chat(model: str, messages: list[dict]):
    """
    Stateless streaming chat: yields content tokens as they arrive.

    The FULL message list is passed in fresh every call (system + prior turns +
    the new user message). We never rely on Ollama holding session state — same
    stateless guarantee as the other agents, just streamed.
    """
    try:
        stream = _client.chat(
            model=model,
            messages=messages,
            stream=True,
            options=_gen_options(),
            keep_alive=getattr(config, "LLM_KEEP_ALIVE", "5m"),
        )
        for chunk in stream:
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield token
    except ollama.ResponseError as exc:
        raise LLMJSONError(f"Ollama returned an error for model '{model}': {exc}") from exc
    except ConnectionError as exc:
        raise OllamaUnreachableError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "timeout" in msg:
            raise OllamaUnreachableError(str(exc)) from exc
        raise LLMJSONError(str(exc)) from exc


def call_json(
    model: str,
    system: str,
    user: str,
    schema: Type[T],
    max_retries: Optional[int] = None,
) -> T:
    """
    Stateless JSON call validated against a pydantic schema.

    On malformed / non-conforming JSON we re-prompt with a corrective message
    that includes the exact error, up to `max_retries` extra attempts. Each
    attempt is still a fresh, stateless call (we rebuild the message list; we
    do NOT accumulate a chat history).
    """
    if max_retries is None:
        max_retries = config.JSON_MAX_RETRIES

    base_user = user
    last_error = ""
    attempts = max_retries + 1

    for attempt in range(attempts):
        user_msg = base_user
        if attempt > 0:
            user_msg = (
                base_user
                + "\n\n---\nYour previous reply was not valid according to the "
                "required schema. Error:\n"
                + last_error
                + "\nReturn ONLY a single valid JSON object that matches the schema. "
                "No prose, no markdown, no code fences."
            )

        content = _raw_chat(model, system, user_msg, force_json=True)

        # First parse as JSON, then validate against the schema.
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            # Some models wrap JSON in ```; try to salvage.
            salvaged = _salvage_json(content)
            if salvaged is None:
                last_error = f"Not valid JSON: {exc}. Got: {content[:300]}"
                continue
            data = salvaged

        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            last_error = _short_validation_error(exc)
            continue

    raise LLMJSONError(
        f"Model '{model}' did not return schema-valid JSON after "
        f"{attempts} attempts. Last error: {last_error}"
    )


def _salvage_json(text: str):
    """Best-effort extraction of a JSON object from a noisy string."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _short_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", []))
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)
