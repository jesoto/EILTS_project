"""Speech-to-text local con faster-whisper (timestamps y confianza por palabra)."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import STTConfig, load_stt_config


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
            from faster_whisper import WhisperModel
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
