"""Normalización de respuestas y utilidades de texto."""
from __future__ import annotations

import re

_TYPO = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize_answer(s: str, *, strip_final_punct: bool = True) -> str:
    """Solo mayúsculas/espacios (y comillas tipográficas): la ortografía SÍ cuenta."""
    s = s.translate(_TYPO).strip().lower()
    s = re.sub(r"\s+", " ", s)
    if strip_final_punct:
        s = s.rstrip(" .")
    return s


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text.strip()) if s.strip()]
