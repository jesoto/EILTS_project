"""Progreso: historial de bandas, rachas, resumen semanal y punto de control del 22 nov."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from . import db
from .curriculum import Curriculum, load_curriculum
from .scoring import checkpoint_advice, overall_band, round_band

ADVICE_TEXT = {
    "keep": "Mantén la fecha del examen (29 dic).",
    "consult": "Resultado intermedio: consúltalo con tu profesora antes de decidir.",
    "reschedule": "Considera mover la fecha del examen y reforzar con tu profesora.",
}


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


# ------------------------------------------------------------------ historiales
def writing_history(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT date, task, task_type, evaluation FROM writing_submission ORDER BY id"):
        ev = json.loads(r["evaluation"])
        band = round_band([ev[k]["banda"] for k in ("ta_tr", "cc", "lr", "gra")])
        out.append({"date": _d(r["date"]), "task": r["task"], "type": r["task_type"], "band": band})
    return out


def speaking_history(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT date, part, evaluation FROM speaking_session WHERE evaluation IS NOT NULL ORDER BY id"):
        ev = json.loads(r["evaluation"])
        out.append({"date": _d(r["date"]), "part": r["part"],
                    "band": round_band([ev[k]["banda"] for k in ("fc", "lr", "gra")])})
    return out


def receptive_history(conn: sqlite3.Connection, skill: str) -> list[dict]:
    rows = conn.execute("SELECT date, test_id, unit, raw, total, band FROM receptive_attempt WHERE skill=? ORDER BY id",
                        (skill,)).fetchall()
    return [{"date": _d(r["date"]), "test": r["test_id"], "unit": r["unit"], "raw": r["raw"], "total": r["total"],
             "pct": round(100 * r["raw"] / r["total"]) if r["total"] else 0, "band": r["band"]} for r in rows]


# ------------------------------------------------------------------ racha
def activity_days(conn: sqlite3.Connection) -> set[date]:
    queries = ["SELECT done_at FROM block_log", "SELECT date FROM attempt", "SELECT date FROM receptive_attempt",
               "SELECT date FROM writing_submission", "SELECT date FROM speaking_session",
               "SELECT date FROM review_log", "SELECT date FROM audit"]
    days: set[date] = set()
    for q in queries:
        days |= {_d(r[0]) for r in conn.execute(q)}
    return days


def streak(conn: sqlite3.Connection, today: date) -> int:
    """Días consecutivos con actividad hasta hoy (si hoy aún no hay actividad, cuenta desde ayer)."""
    days = activity_days(conn)
    cur = today if today in days else today - timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


# ------------------------------------------------------------------ resumen y punto de control
def week_range(week: int, cur: Curriculum | None = None) -> tuple[date, date]:
    cur = cur or load_curriculum()
    start = cur.start_date + timedelta(days=7 * (max(week, 1) - 1))
    return start, start + timedelta(days=6)


def week_summary(conn: sqlite3.Connection, week: int, cur: Curriculum | None = None) -> dict:
    """«¿Qué medí?»: números de la semana para la auditoría del domingo."""
    start, end = week_range(week, cur)
    inside = lambda d: start <= d <= end  # noqa: E731
    w = [h for h in writing_history(conn) if inside(h["date"])]
    s = [h for h in speaking_history(conn) if inside(h["date"])]
    rd = [h for h in receptive_history(conn, "reading") if inside(h["date"])]
    ls = [h for h in receptive_history(conn, "listening") if inside(h["date"])]
    graded = lambda hs: hs and round_band([h["band"] for h in hs])  # noqa: E731
    vocab = conn.execute("SELECT COUNT(*) c FROM review_log WHERE date BETWEEN ? AND ?",
                         (start.isoformat(), end.isoformat())).fetchone()["c"]
    gram = [r["score"] for r in conn.execute(
        "SELECT score FROM attempt WHERE skill='grammar' AND substr(date,1,10) BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()))]
    top = db.top_categories(conn, since=start.isoformat(), limit=3)
    return {
        "week": week, "from": start.isoformat(), "to": end.isoformat(),
        "writing_bands": [h["band"] for h in w], "speaking_bands": [h["band"] for h in s],
        "reading": [(h["raw"], h["total"]) for h in rd], "listening": [(h["raw"], h["total"]) for h in ls],
        "writing_avg": graded(w) or None, "speaking_avg": graded(s) or None,
        "grammar_pct": round(100 * sum(gram) / len(gram)) if gram else None,
        "vocab_reviews": vocab, "top_errors": top,
    }


def latest_bands(conn: sqlite3.Connection) -> dict[str, float | None]:
    """Última banda estimada por habilidad. Reading/Listening: solo tests completos (40 preguntas)."""
    def last_full(skill):
        r = conn.execute("SELECT band FROM receptive_attempt WHERE skill=? AND band IS NOT NULL ORDER BY id DESC LIMIT 1",
                         (skill,)).fetchone()
        return r["band"] if r else None

    def recent(hist):
        vals = [h["band"] for h in hist[-2:]]
        return round_band(vals) if vals else None
    return {"listening": last_full("listening"), "reading": last_full("reading"),
            "writing": recent(writing_history(conn)), "speaking": recent(speaking_history(conn))}


def checkpoint(conn: sqlite3.Connection) -> dict | None:
    """Overall estimado y consejo del punto de control; None si falta alguna habilidad."""
    b = latest_bands(conn)
    if any(v is None for v in b.values()):
        return None
    overall = overall_band(b["listening"], b["reading"], b["writing"], b["speaking"])
    advice = checkpoint_advice(overall)
    return {"bands": b, "overall": overall, "advice": advice, "text": ADVICE_TEXT[advice]}


def missing_for_checkpoint(conn: sqlite3.Connection) -> list[str]:
    return [k for k, v in latest_bands(conn).items() if v is None]
