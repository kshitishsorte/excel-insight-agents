"""
Offline speech services: Whisper (STT, faster-whisper) + Piper (TTS).

Both run locally on CPU. Models are downloaded once into VOICE_DIR from Hugging
Face, then everything is offline. Loading is lazy and cached, so the first voice
turn pays the model-load cost and later turns are fast.

The whole module degrades gracefully: if a model can't be loaded/downloaded,
`available()` reports why and the app falls back to text-only chat.
"""

from __future__ import annotations

import io
import os
import threading
import urllib.request
import wave

import config

_PIPER_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/lessac/medium/"
)

_lock = threading.Lock()
_whisper = None
_piper = None
_load_error: str | None = None


def _piper_paths() -> tuple[str, str]:
    onnx = os.path.join(config.VOICE_DIR, f"{config.PIPER_VOICE}.onnx")
    return onnx, onnx + ".json"


def _ensure_piper_voice() -> str:
    """Download the Piper voice files once if missing. Returns the .onnx path."""
    os.makedirs(config.VOICE_DIR, exist_ok=True)
    onnx, cfg = _piper_paths()
    for path, url in ((onnx, _PIPER_BASE + f"{config.PIPER_VOICE}.onnx"),
                      (cfg, _PIPER_BASE + f"{config.PIPER_VOICE}.onnx.json")):
        if not os.path.exists(path) or os.path.getsize(path) < 1000:
            urllib.request.urlretrieve(url, path)
    return onnx


def _get_piper():
    global _piper
    if _piper is None:
        from piper import PiperVoice

        _piper = PiperVoice.load(_ensure_piper_voice())
    return _piper


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        os.makedirs(config.VOICE_DIR, exist_ok=True)
        _whisper = WhisperModel(
            config.WHISPER_MODEL, device="cpu", compute_type="int8",
            download_root=config.VOICE_DIR,
        )
    return _whisper


def warm_up() -> bool:
    """Eagerly load both models. Returns True on success, records error otherwise."""
    global _load_error
    try:
        with _lock:
            _get_piper()
            _get_whisper()
        _load_error = None
        return True
    except Exception as exc:  # noqa: BLE001
        _load_error = str(exc)
        return False


def available() -> tuple[bool, str]:
    if _whisper is not None and _piper is not None:
        return True, "Voice models loaded."
    if _load_error:
        return False, f"Voice unavailable: {_load_error}"
    return True, "Voice models will load on first use."


def transcribe(audio_bytes: bytes) -> str:
    """Speech -> text. Accepts any container faster-whisper/av can decode (webm/wav)."""
    model = _get_whisper()
    segments, _info = model.transcribe(io.BytesIO(audio_bytes), beam_size=1, vad_filter=True)
    return " ".join(s.text for s in segments).strip()


def synthesize(text: str) -> bytes:
    """Text -> WAV bytes (16-bit PCM)."""
    text = (text or "").strip()
    if not text:
        return b""
    if len(text) > config.VOICE_BRIEF_CHARS:
        text = text[: config.VOICE_BRIEF_CHARS].rsplit(" ", 1)[0] + "…"
    voice = _get_piper()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf)
    return buf.getvalue()
