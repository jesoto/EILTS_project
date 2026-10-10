"""Métricas de fluidez sin LLM, a partir de los timestamps por palabra."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .stt import Word

PAUSE_THRESHOLD = 1.5   # segundos
FILLER_WORDS = {"um", "umm", "uh", "uhh", "eh", "er", "erm", "hmm", "mm", "mmm", "ah"}
FILLER_PHRASES = ["you know", "i mean", "like"]
LOW_CONFIDENCE = 0.5
STOPWORDS = set("""a an the and or but so if then of to in on at for with by from as is are was were be been being
i you he she it we they me my your his her its our their this that these those there here do does did have has had
not no yes very just really also can could will would should may might more most much many some any about than
what which who whom whose when where why how because while into out up down over under again""".split())


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower().replace("’", "'"))


@dataclass
class Pause:
    after: str
    seconds: float


@dataclass
class SpeakingMetrics:
    words: int = 0
    speaking_seconds: float = 0.0
    wpm: float = 0.0
    pauses: list[Pause] = field(default_factory=list)
    fillers: dict[str, int] = field(default_factory=dict)
    repeated: list[tuple[str, int]] = field(default_factory=list)
    ttr: float = 0.0
    mattr: float = 0.0
    low_confidence: list[str] = field(default_factory=list)

    @property
    def filler_total(self) -> int:
        return sum(self.fillers.values())

    def summary(self) -> str:
        """Texto compacto para el prompt del LLM."""
        return (f"words={self.words}, speaking_time={self.speaking_seconds:.0f}s, wpm={self.wpm:.0f}, "
                f"pauses>1.5s={len(self.pauses)}, fillers={self.fillers or 'none'}, "
                f"most_repeated={self.repeated or 'none'}, lexical_diversity(MATTR)={self.mattr:.2f}")


def _mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-average TTR: más estable que el TTR simple con textos de distinta longitud."""
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    ratios = [len(set(tokens[i:i + window])) / window for i in range(len(tokens) - window + 1)]
    return sum(ratios) / len(ratios)


def count_fillers(tokens: list[str]) -> dict[str, int]:
    text = " " + " ".join(tokens) + " "
    out = {w: tokens.count(w) for w in FILLER_WORDS if w in tokens}
    for ph in FILLER_PHRASES:
        n = len(re.findall(rf"(?<= ){re.escape(ph)}(?= )", text))
        if n:
            out[ph] = n
    return out


def compute_metrics(segments: list[list[Word]]) -> SpeakingMetrics:
    """`segments`: una lista de palabras por grabación (las pausas no cruzan grabaciones)."""
    words = [w for seg in segments for w in seg]
    tokens = [t for w in words for t in tokenize(w.text)]
    m = SpeakingMetrics(words=len(tokens))
    if not tokens:
        return m
    m.speaking_seconds = sum(max(0.0, seg[-1].end - seg[0].start) for seg in segments if seg)
    m.wpm = m.words / (m.speaking_seconds / 60) if m.speaking_seconds > 0 else 0.0
    for seg in segments:
        for a, b in zip(seg, seg[1:]):
            gap = b.start - a.end
            if gap > PAUSE_THRESHOLD:
                m.pauses.append(Pause(a.text, round(gap, 1)))
    m.fillers = count_fillers(tokens)
    content = [t for t in tokens if t not in STOPWORDS and t not in FILLER_WORDS and len(t) > 2]
    counts: dict[str, int] = {}
    for t in content:
        counts[t] = counts.get(t, 0) + 1
    m.repeated = sorted(((t, n) for t, n in counts.items() if n >= 3), key=lambda x: -x[1])[:5]
    m.ttr = len(set(tokens)) / len(tokens)
    m.mattr = _mattr(tokens)
    m.low_confidence = [w.text for w in words if w.prob < LOW_CONFIDENCE and tokenize(w.text)][:12]
    return m


def compare_transcripts(reference: str, spoken: str) -> dict:
    """Shadowing: compara la transcripción de referencia con la del usuario (a nivel de palabra)."""
    import difflib
    ref, got = tokenize(reference), tokenize(spoken)
    sm = difflib.SequenceMatcher(a=ref, b=got, autojunk=False)
    missing, extra = [], []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op in ("delete", "replace"):
            missing += ref[a0:a1]
        if op in ("insert", "replace"):
            extra += got[b0:b1]
    weak = {"a", "an", "the", "of", "to", "and", "or", "for", "can", "at", "from", "that", "was", "are", "have", "has"}
    return {"similarity": round(sm.ratio(), 2), "missing": missing, "extra": extra,
            "weak_forms_missing": [w for w in missing if w in weak]}
