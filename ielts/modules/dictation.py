"""Dictado (bottom-up): 1 min de audio → el usuario transcribe → comparación con la transcripción del libro."""
from __future__ import annotations

import difflib
import re

from ..speaking_metrics import compare_transcripts

WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
SPEAKER = re.compile(r"^\s*[A-Za-z][A-Za-z ]{0,20}:\s*", re.M)

# Palabras que en el habla conectada se reducen o se funden (formas débiles / coarticulación)
WEAK = {"a", "an", "the", "of", "to", "and", "or", "for", "can", "at", "from", "that", "was", "were", "are", "have",
        "has", "had", "do", "does", "would", "could", "should", "his", "her", "your", "them", "us", "some", "been"}


def clean_transcript(text: str) -> str:
    """Quita las etiquetas de hablante («peter:», «jan:»)."""
    return SPEAKER.sub("", text)


def words(text: str) -> list[str]:
    return WORD.findall(text.replace("’", "'"))


def locate(asr_text: str, book_text: str, slack: float = 1.25) -> str:
    """Busca en la transcripción del libro el tramo que mejor coincide con lo que Whisper oyó."""
    ref = words(clean_transcript(book_text))
    asr = [w.lower() for w in words(asr_text)]
    if not asr or not ref:
        return ""
    size = min(len(ref), int(len(asr) * slack) + 3)
    best, best_i = -1.0, 0
    low = [w.lower() for w in ref]
    for i in range(0, max(1, len(ref) - size + 1), 2):
        r = difflib.SequenceMatcher(a=asr, b=low[i:i + size], autojunk=False).ratio()
        if r > best:
            best, best_i = r, i
    # recorta a los bloques que realmente coinciden con lo oído (no se exigen palabras de los bordes)
    window = ref[best_i:best_i + size]
    sm = difflib.SequenceMatcher(a=asr, b=[w.lower() for w in window], autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
    if not blocks:
        return " ".join(window)
    return " ".join(window[blocks[0].b:blocks[-1].b + blocks[-1].size])


def compare_dictation(reference: str, typed: str) -> dict:
    """Resultado de compare_transcripts + formas débiles omitidas (según WEAK)."""
    r = compare_transcripts(reference, typed)
    r["weak_forms_missing"] = [w for w in r["missing"] if w in WEAK]
    return r
