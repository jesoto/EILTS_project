"""Checklist automática previa al LLM (solo reglas): rápida, determinista y explicable."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import split_paragraphs, split_sentences, word_count

MIN_WORDS = {"t1": 150, "t2": 250}
SUGGESTED_WORDS = {"t1": 170, "t2": 270}
FALSE_FRIENDS = ["actually", "realize", "eventually", "sensible", "assist", "sympathetic"]
SUBORDINATORS = r"\b(which|who|whom|whose|that|although|though|while|whereas|because|since|if|when|unless|despite|even though|as)\b"
# Verbo al inicio de oración sin sujeto (pro-drop): "Is important…", "Exist many…", "Have a big impact".
NO_SUBJECT = re.compile(r"^(is|are|was|were|has|have|had|exist|exists|seems?|appears?|depends?|becomes?|happens?)\b", re.I)
SING_SUBJ_PL_VERB = re.compile(r"\b(he|she|it|everyone|everybody|each|this|that|nobody|someone)\s+(are|were|have|don't|do)\b", re.I)
PL_SUBJ_SG_VERB = re.compile(r"\b(they|we|people|children|police|many \w+|these \w+|those \w+)\s+(is|was|has|doesn't|does)\b", re.I)
POSITION = re.compile(r"\b(i (strongly )?(agree|disagree|believe|think)|in my (opinion|view)|this essay|i would argue|"
                      r"outweigh|i am of the opinion|from my perspective)\b", re.I)


@dataclass
class CheckItem:
    id: str
    ok: bool
    message_es: str
    evidence: list[str]

    def as_line(self) -> str:
        mark = "OK" if self.ok else "WARNING"
        ev = f" Evidence: {'; '.join(self.evidence[:3])}" if self.evidence else ""
        return f"- [{mark}] {self.id}: {self.message_es}{ev}"


def _sentences_by_paragraph(text: str) -> list[list[str]]:
    return [split_sentences(p) for p in split_paragraphs(text)]


def run_checklist(text: str, task: str) -> list[CheckItem]:
    """task: 't1' o 't2'."""
    items: list[CheckItem] = []
    words = word_count(text)
    paragraphs = split_paragraphs(text)
    sentences = [s for p in _sentences_by_paragraph(text) for s in p]
    minimum, suggested = MIN_WORDS[task], SUGGESTED_WORDS[task]

    items.append(CheckItem("word_count", words >= minimum,
                           f"{words} palabras (mínimo {minimum}, sugerido {suggested}).", []))

    bad = [s for s in sentences if NO_SUBJECT.match(s) and not s.endswith("?")]
    items.append(CheckItem("explicit_subject", not bad,
                           "Cada cláusula debería tener sujeto explícito (it / there / this…)." if bad
                           else "No se detectaron oraciones sin sujeto.", bad))

    agr = [m.group(0) for s in sentences for m in [SING_SUBJ_PL_VERB.search(s) or PL_SUBJ_SG_VERB.search(s)] if m]
    items.append(CheckItem("agreement", not agr,
                           "Posible error de concordancia sujeto-verbo." if agr else "Sin problemas evidentes de concordancia.",
                           agr))

    lower = text.lower()
    ff = [w for w in FALSE_FRIENDS if re.search(rf"\b{w}\w*\b", lower)]
    items.append(CheckItem("false_friends", not ff,
                           "Revisa el uso de estos falsos amigos (actually ≠ actualmente, realize ≠ realizar, "
                           "eventually ≠ eventualmente, sensible ≠ sensible, assist ≠ asistir, sympathetic ≠ simpático)." if ff
                           else "No aparecen falsos amigos típicos.", ff))

    weak = []
    for i, sents in enumerate(_sentences_by_paragraph(text), start=1):
        complex_n = sum(1 for s in sents if re.search(SUBORDINATORS, s, re.I) or ";" in s)
        if complex_n < 2:
            weak.append(f"párrafo {i}: {complex_n} oración(es) compleja(s)")
    items.append(CheckItem("complex_sentences", not weak,
                           "Cada párrafo debería tener ≥2 oraciones complejas." if weak
                           else "Buen uso de oraciones complejas.", weak))

    counts = {w: len(re.findall(rf"\b{w}\b", lower)) for w in ("but", "so", "about")}
    over = [f"{w} ×{n}" for w, n in counts.items() if n >= 3]
    items.append(CheckItem("connector_variety", not over,
                           "Abuso de conectores básicos; varía (however, whereas, consequently…)." if over
                           else "Conectores variados.", over))

    if task == "t1":
        overview = paragraphs[1] if len(paragraphs) > 1 else ""
        figures = re.findall(r"\d[\d.,]*\s?%?", overview)
        items.append(CheckItem("overview_no_figures", bool(overview) and not figures,
                               "El overview (2.º párrafo) debe resumir tendencias SIN cifras." if figures
                               else ("No hay un párrafo de overview separado." if not overview
                                     else "Overview sin cifras."), figures))
        items.append(CheckItem("paragraph_structure", len(paragraphs) == 4,
                               f"Task 1 debe tener 4 párrafos (tienes {len(paragraphs)}): intro, overview, cuerpo 1, cuerpo 2.", []))
    else:
        intro = paragraphs[0] if paragraphs else ""
        items.append(CheckItem("clear_position", bool(POSITION.search(intro)) or bool(POSITION.search(text)),
                               "No se detecta una posición clara; decláralo en la introducción (I believe… / This essay will…).", []))
        items.append(CheckItem("paragraph_structure", 4 <= len(paragraphs) <= 5,
                               f"Task 2 suele tener 4-5 párrafos (tienes {len(paragraphs)}).", []))
    return items


def checklist_summary(items: list[CheckItem]) -> str:
    return "\n".join(i.as_line() for i in items)
