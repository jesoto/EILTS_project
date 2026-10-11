"""Reading y Listening: corrección con clave, bandas, registro de intentos y causas de error."""
from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .. import db
from ..ingest.schema import Group, KeyEntry, TestData, list_tests
from ..scoring import listening_band, reading_band
from ..text import normalize_answer
from .. import clock

READING_CAUSES = ["Sinónimo no reconocido", "Not Given vs False", "Falta de tiempo", "Vocabulario desconocido",
                  "Leí mal / descuido", "Adiviné"]
LISTENING_CAUSES = ["Ortografía", "No escuché / me perdí", "Distractor (cambió la respuesta)",
                    "Número o deletreo", "Vocabulario desconocido", "Adiviné"]
SPELLING = "Ortografía"


def causes_for(skill: str) -> list[str]:
    return READING_CAUSES if skill == "reading" else LISTENING_CAUSES


# ------------------------------------------------------------------ respuestas aceptadas
def expand_answer(alt: str) -> set[str]:
    """Variantes aceptadas de una alternativa de la clave, ya normalizadas.

    «(Sumatran) orangutan» → con y sin «Sumatran»;  «floor(s)» → floor / floors.
    """
    variants = {alt}
    for _ in range(3):
        nxt = set()
        for v in variants:
            m = re.search(r"\(([^)]+)\)", v)
            if not m:
                nxt.add(v)
                continue
            inner = m.group(1)
            nxt.add((v[:m.start()] + v[m.end():]))                 # sin lo opcional
            nxt.add((v[:m.start()] + inner + v[m.end():]))         # con lo opcional
        variants = nxt
    return {normalize_answer(re.sub(r"\s+", " ", v)) for v in variants if v.strip()}


def accepted_set(alts: list[str]) -> set[str]:
    out: set[str] = set()
    for a in alts:
        out |= expand_answer(a)
    return out


def display_answer(alts: list[str]) -> str:
    return " / ".join(alts)


# ------------------------------------------------------------------ corrección
@dataclass
class QResult:
    q: int
    user: str
    correct: bool
    expected: str                 # texto para mostrar
    qtype: str = ""
    near_miss: bool = False       # casi correcta (probable error de ortografía)


def _near(user: str, valid: set[str]) -> bool:
    u = normalize_answer(user)
    return bool(u) and any(difflib.SequenceMatcher(a=u, b=v).ratio() >= 0.8 for v in valid if v != u)


def grade(td: TestData, skill: str, answers: dict[int, str], qnums: list[int],
          qtype_of: dict[int, str] | None = None) -> list[QResult]:
    """Corrige solo `qnums`. Las parejas «IN EITHER ORDER» se corrigen como conjunto."""
    km = td.key_map(skill)
    qtype_of = qtype_of or {}
    results: dict[int, QResult] = {}
    done_entries: set[int] = set()
    for q in qnums:
        entry = km.get(q)
        if entry is None:
            results[q] = QResult(q, answers.get(q, ""), False, "(sin clave)", qtype_of.get(q, ""))
            continue
        if id(entry) in done_entries:
            continue
        done_entries.add(id(entry))
        if entry.any_order:
            pool = [accepted_set(a) for a in entry.answers]
            for qn in entry.qnums:
                u = normalize_answer(answers.get(qn, ""))
                hit = next((i for i, s in enumerate(pool) if u and u in s), None)
                if hit is not None:
                    pool.pop(hit)
                results[qn] = QResult(qn, answers.get(qn, ""), hit is not None,
                                      " / ".join(display_answer(a) for a in entry.answers) + " (cualquier orden)",
                                      qtype_of.get(qn, ""))
        else:
            qn = entry.qnums[0]
            valid = accepted_set(entry.answers[0])
            u = normalize_answer(answers.get(qn, ""))
            ok = bool(u) and u in valid
            results[qn] = QResult(qn, answers.get(qn, ""), ok, display_answer(entry.answers[0]), qtype_of.get(qn, ""),
                                  near_miss=(not ok and _near(answers.get(qn, ""), valid)))
    return [results[q] for q in qnums if q in results]


def band_for(skill: str, raw: int, total: int) -> float | None:
    """Solo se da banda con el test completo (40 preguntas)."""
    if total != 40:
        return None
    return reading_band(raw) if skill == "reading" else listening_band(raw)


# ------------------------------------------------------------------ registro
def group_types(units) -> dict[int, str]:
    return {q: g.type for u in units for g in u.groups for q in g.qnums}


def record_attempt(conn: sqlite3.Connection, *, week: int, skill: str, td: TestData, unit: str,
                   results: list[QResult], qtype: str = "", seconds: int = 0, aggregate: bool = False) -> int:
    """`aggregate=True`: fila resumen del test completo (con banda); no guarda errores ni mueve el nivel."""
    raw = sum(r.correct for r in results)
    cur = conn.execute(
        "INSERT INTO receptive_attempt(date, week, skill, test_id, unit, raw, total, band, qtype, seconds) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (clock.timestamp(), week, skill, td.test_id, unit, raw, len(results),
         band_for(skill, raw, len(results)), qtype, seconds))
    aid = cur.lastrowid
    spelling_ids = []
    for r in ([] if aggregate else results):
        if not r.correct:
            c = conn.execute("INSERT INTO receptive_error(attempt_id, q, qtype, user_answer, correct_answer, cause) "
                             "VALUES (?,?,?,?,?,?)", (aid, r.q, r.qtype, r.user, r.expected, ""))
            if skill == "listening" and r.near_miss:
                spelling_ids.append(c.lastrowid)
    conn.commit()
    for eid in spelling_ids:     # casi acertada: en Listening la ortografía cuenta → causa automática
        save_cause(conn, skill, eid, SPELLING)
    if results and not aggregate:
        db.record_attempt(conn, skill, raw / len(results), f"{td.test_id}:{unit}")
    return aid


def save_cause(conn: sqlite3.Connection, skill: str, error_id: int, cause: str) -> None:
    """Guarda la causa y la refleja en el error log (los fallos de ortografía generan tarjeta SRS)."""
    row = conn.execute("SELECT * FROM receptive_error WHERE id=?", (error_id,)).fetchone()
    conn.execute("UPDATE receptive_error SET cause=? WHERE id=?", (cause, error_id))
    conn.commit()
    if not row or not cause:
        return
    category = "spelling" if cause == SPELLING else "other"
    correction = row["correct_answer"].split(" / ")[0]
    db.log_error(conn, skill, row["user_answer"] or "(vacío)", correction, category,
                 f"{cause} (pregunta {row['q']}, {row['qtype']})")


def attempt_errors(conn: sqlite3.Connection, attempt_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM receptive_error WHERE attempt_id=? ORDER BY q", (attempt_id,)).fetchall()


def latest_attempts(conn: sqlite3.Connection, skill: str | None = None, limit: int = 5) -> list[sqlite3.Row]:
    q, args = "SELECT * FROM receptive_attempt", []
    if skill:
        q += " WHERE skill=?"
        args.append(skill)
    return conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()


# ------------------------------------------------------------------ selección de unidades
@dataclass
class Unit:
    skill: str
    td: TestData
    key: str            # p1 / l3
    n: int
    qtypes: set[str]
    groups: list[Group]

    @property
    def label(self) -> str:
        what = "Pasaje" if self.skill == "reading" else "Parte"
        return f"{self.td.book_title.replace(' Academic', '')} · Test {self.td.test} · {what} {self.n}"


def verified_tests() -> list[TestData]:
    return [t for t in list_tests() if t.verified]


def all_units(skill: str, tests: list[TestData]) -> list[Unit]:
    out = []
    for t in tests:
        units = t.reading if skill == "reading" else t.listening
        for u in units:
            n = u.n if skill == "reading" else u.part
            out.append(Unit(skill, t, f"{'p' if skill == 'reading' else 'l'}{n}", n,
                            {g.type for g in u.groups}, u.groups))
    return out


def pick_unit(conn: sqlite3.Connection, skill: str, units: list[Unit], *, types: list[str] | None = None,
              part: int | None = None) -> Unit | None:
    """La unidad menos practicada (y más temprana) que cumpla el filtro de tipo/parte."""
    cand = [u for u in units
            if (not types or u.qtypes & set(types)) and (part is None or u.n == part)
            and (skill != "listening" or u.td.listening[u.n - 1].audio)]
    if not cand:
        return None
    seen = {(r["test_id"], r["unit"]): 0 for r in conn.execute(
        "SELECT test_id, unit FROM receptive_attempt WHERE skill=?", (skill,))}
    counts: dict[tuple[str, str], int] = {}
    for r in conn.execute("SELECT test_id, unit FROM receptive_attempt WHERE skill=?", (skill,)):
        counts[(r["test_id"], r["unit"])] = counts.get((r["test_id"], r["unit"]), 0) + 1
    del seen
    return min(cand, key=lambda u: (counts.get((u.td.test_id, u.key), 0), u.td.test, u.n))
