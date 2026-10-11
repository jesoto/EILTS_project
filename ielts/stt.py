"""Speech-to-text local con faster-whisper (timestamps y confianza por palabra)."""
from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from .config import STTConfig, load_app_config, load_llm_config, load_stt_config
from .llm.base import LLMError


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0   # duración del audio (s)


class Transcriber(Protocol):
    def transcribe(self, source: bytes | str | Path, *, start: float | None = None,
                   end: float | None = None) -> Transcript: ...


class FasterWhisperTranscriber:
    """Carga el modelo la primera vez (descarga ~500 MB para `small`)."""

    def __init__(self, cfg: STTConfig | None = None, model=None):
        self.cfg = cfg or load_stt_config()
        self._model = model  # inyectable en tests

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError("Whisper local no está instalado: ejecuta `uv sync --extra local-stt` "
                                   "o usa [stt] provider = \"openai\" en config.toml.") from e
            self._model = WhisperModel(self.cfg.model, device=self.cfg.device, compute_type=self.cfg.compute_type)
        return self._model

    def transcribe(self, source, *, start=None, end=None) -> Transcript:
        model = self._load()
        src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
        kwargs = {}
        if start is not None or end is not None:
            kwargs["clip_timestamps"] = f"{start or 0},{end if end is not None else 0}"
        segments, info = model.transcribe(
            src, language=self.cfg.language, word_timestamps=True, beam_size=5,
            condition_on_previous_text=False, initial_prompt=self.cfg.initial_prompt or None, **kwargs)
        words: list[Word] = []
        parts: list[str] = []
        for seg in segments:
            parts.append(seg.text.strip())
            for w in seg.words or []:
                words.append(Word(w.word.strip(), float(w.start), float(w.end), float(getattr(w, "probability", 1.0))))
        return Transcript(" ".join(p for p in parts if p), words, float(getattr(info, "duration", 0.0)))


class OpenAITranscriber:
    """Transcripción con la API de OpenAI (`whisper-1`: único modelo con timestamps por palabra). Para el modo cloud."""

    def __init__(self, cfg: STTConfig | None = None, *, transport: httpx.BaseTransport | None = None, usage=None,
                 sleep=None):
        import time
        self.cfg = cfg or load_stt_config()
        self.llm = load_llm_config()
        self._transport = transport
        self.usage = usage
        self._sleep = sleep or time.sleep

    def _key(self) -> str:
        key = os.environ.get(self.llm.openai_key_env, "").strip()
        if not key:
            raise LLMError(f"Falta {self.llm.openai_key_env}: sin ella no se puede transcribir el audio.")
        return key

    def transcribe(self, source, *, start=None, end=None) -> Transcript:
        from .audio import to_wav16k
        from .llm.usage import calls_today
        cap = self.llm.max_calls_per_day
        if cap and self.usage is not None and calls_today(self.usage) >= cap:
            raise LLMError(f"Límite diario de llamadas a OpenAI alcanzado ({cap}). Se reinicia mañana.")
        data = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
        wav, clip_seconds = to_wav16k(data, start, end)
        offset = float(start or 0.0)
        form = {"model": self.cfg.openai_model, "response_format": "verbose_json", "language": self.cfg.language,
                "timestamp_granularities[]": ["word", "segment"]}
        if self.cfg.initial_prompt:
            form["prompt"] = self.cfg.initial_prompt
        url = f"{self.llm.openai_base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._key()}"}
        for attempt in range(3):
            try:
                with httpx.Client(transport=self._transport, timeout=self.llm.timeout_s) as client:
                    r = client.post(url, data=form, files={"file": ("audio.wav", wav, "audio/wav")}, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"No se pudo conectar con OpenAI para transcribir: {self._redact(str(e))}") from e
            if r.status_code == 200:
                break
            body = self._redact(r.text[:300])
            if r.status_code == 401:
                raise LLMError("OpenAI rechazó la clave (401) al transcribir: revisa OPENAI_API_KEY.")
            if r.status_code == 429 and "insufficient_quota" in body:
                raise LLMError("Sin crédito en la cuenta de OpenAI (insufficient_quota).")
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                self._sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"OpenAI devolvió {r.status_code} al transcribir: {body}")
        else:
            raise LLMError("OpenAI no respondió al transcribir tras varios intentos.")
        if self.usage is not None:
            self.usage.record(self.cfg.openai_model, 0, 0)          # cuenta como llamada (tope diario)
        return self._to_transcript(r.json(), offset, clip_seconds)

    def _redact(self, text: str) -> str:
        key = os.environ.get(self.llm.openai_key_env, "")
        return text.replace(key, "***") if key else text

    @staticmethod
    def _to_transcript(payload: dict, offset: float, clip_seconds: float) -> Transcript:
        """verbose_json → Transcript. La API no da probabilidad por palabra: se aproxima con la del segmento."""
        segments = payload.get("segments") or []

        def prob_at(t: float) -> float:
            for sg in segments:
                if sg.get("start", 0) <= t <= sg.get("end", 0) + 0.01:
                    lp = sg.get("avg_logprob")
                    return float(min(1.0, math.exp(lp))) if lp is not None else 1.0
            return 1.0
        words = [Word(str(w["word"]).strip(), float(w["start"]) + offset, float(w["end"]) + offset, prob_at(float(w["start"])))
                 for w in payload.get("words") or []]
        text = (payload.get("text") or "").strip()
        return Transcript(text, words, float(payload.get("duration") or clip_seconds))


def resolve_stt_provider(cfg: STTConfig | None = None) -> str:
    """auto → openai en modo cloud, local en el resto."""
    cfg = cfg or load_stt_config()
    if cfg.provider in ("local", "openai"):
        return cfg.provider
    return "openai" if load_app_config().is_cloud else "local"


def make_transcriber(usage=None) -> Transcriber:
    cfg = load_stt_config()
    if resolve_stt_provider(cfg) == "openai":
        return OpenAITranscriber(cfg, usage=usage)
    return FasterWhisperTranscriber(cfg)
