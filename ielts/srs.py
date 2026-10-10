"""SRS de vocabulario: algoritmo SM-2 propio sobre SQLite + generación de tarjetas con el LLM."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from .config import LLMConfig, load_llm_config
from .llm.base import LLMProvider
from .llm.client import generate_json, load_prompt
from .llm.schemas import VocabCardBatch

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "vocab_seed.yaml"
NEW_PER_DAY = 8
MIN_EASE = 1.3
# Botones de la UI → calidad SM-2 (0-5)
RATINGS = {"Otra vez": 1, "Difícil": 3, "Bien": 4, "Fácil": 5}


def sm2(ease: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """Un paso de SM-2. Devuelve (ease, interval_días, repeticiones)."""
    if not 0 <= quality <= 5:
        raise ValueError("quality debe estar entre 0 y 5")
    if quality < 3:
        return ease, 1, 0          # fallo: reinicia repeticiones (la ease no cambia)
    if reps == 0:
        new_interval = 1
    elif reps == 1:
        new_interval = 6
    else:
        new_interval = max(interval + 1, round(interval * ease))
    ease = max(MIN_EASE, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return round(ease, 4), new_interval, reps + 1


def review_card(conn: sqlite3.Connection, card_id: int, quality: int, today: date | None = None,
                user_sentence: str | None = None) -> sqlite3.Row:
    today = today or date.today()
    row = conn.execute("SELECT * FROM card WHERE id=?", (card_id,)).fetchone()
    ease, interval, reps = sm2(row["ease"], row["interval"], row["reps"], quality)
    due = today + timedelta(days=interval)
    sentence = user_sentence.strip() if user_sentence and user_sentence.strip() else row["user_sentence"]
    conn.execute("UPDATE card SET ease=?, interval=?, reps=?, due=?, last_review=?, user_sentence=? WHERE id=?",
                 (ease, interval, reps, due.isoformat(), today.isoformat(), sentence, card_id))
    conn.execute("INSERT INTO review_log(card_id, date, quality) VALUES (?,?,?)",
                 (card_id, today.isoformat(), quality))
    conn.commit()
    return conn.execute("SELECT * FROM card WHERE id=?", (card_id,)).fetchone()


def _new_today(conn: sqlite3.Connection, today: date) -> int:
    """Tarjetas que se vieron por primera vez hoy."""
    return conn.execute(
        """SELECT COUNT(*) c FROM (SELECT card_id FROM review_log GROUP BY card_id HAVING MIN(date)=?)""",
        (today.isoformat(),)).fetchone()["c"]


def due_cards(conn: sqlite3.Connection, today: date | None = None, limit: int = 50) -> list[sqlite3.Row]:
    """Repasos vencidos primero; tarjetas nuevas limitadas a NEW_PER_DAY por día."""
    today = today or date.today()
    iso = today.isoformat()
    reviews = conn.execute(
        """SELECT * FROM card WHERE status='ready' AND due<=?
           AND id IN (SELECT card_id FROM review_log) ORDER BY due, id LIMIT ?""", (iso, limit)).fetchall()
    room = max(0, NEW_PER_DAY - _new_today(conn, today))
    new = conn.execute(
        """SELECT * FROM card WHERE status='ready' AND id NOT IN (SELECT card_id FROM review_log)
           ORDER BY (source='error_log') DESC, id LIMIT ?""", (room,)).fetchall()
    return (list(reviews) + list(new))[:limit]


def pending_cards(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    """Pendientes de completar; los errores propios van primero."""
    return conn.execute("SELECT * FROM card WHERE status='pending' ORDER BY (source='error_log') DESC, id LIMIT ?",
                        (limit,)).fetchall()


def unseen_ready(conn: sqlite3.Connection) -> int:
    """Tarjetas completas que aún no se han repasado nunca."""
    return conn.execute("SELECT COUNT(*) c FROM card WHERE status='ready' "
                        "AND id NOT IN (SELECT card_id FROM review_log)").fetchone()["c"]


def stats(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()
    due = due_cards(conn, today)
    q = lambda sql: conn.execute(sql).fetchone()["c"]  # noqa: E731
    return {"due": len(due), "total": q("SELECT COUNT(*) c FROM card WHERE status='ready'"),
            "pending": q("SELECT COUNT(*) c FROM card WHERE status='pending'")}


# ---- semillas ----
@lru_cache(maxsize=1)
def load_seed() -> dict:
    with open(SEED_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def seed_words_for(theme: str, phase: int) -> dict[str, list[str]]:
    """Listas de semillas disponibles para la semana: tema, colocaciones C1, falsos amigos, AWL de la fase."""
    seed = load_seed()
    out: dict[str, list[str]] = {}
    if theme in seed["themes"]:
        out["weekly"] = seed["themes"][theme]
    if theme == "Repaso colocaciones":
        out["collocation"] = seed["c1_collocations"]
    out["false_friend"] = seed["false_friends"]
    sublists = seed["awl"]
    wanted = range(1, 6) if phase <= 1 else range(6, 11)
    awl = [w for k in wanted for w in sublists.get(k, [])]
    if awl:
        out["awl"] = awl
    return out


def add_pending(conn: sqlite3.Connection, words: list[str], source: str, theme: str = "",
                today: date | None = None) -> int:
    today = (today or date.today()).isoformat()
    n = 0
    for w in words:
        word = " ".join(w.lower().split())
        cur = conn.execute("INSERT OR IGNORE INTO card(word, status, source, theme, due, created) VALUES (?,?,?,?,?,?)",
                           (word, "pending", source, theme, today, today))
        n += cur.rowcount
    conn.commit()
    return n


# ---- completar tarjetas con el LLM ----
def fill_pending(provider: LLMProvider, conn: sqlite3.Connection, batch: int = 6,
                 cfg: LLMConfig | None = None) -> int:
    """Pide al LLM los detalles de hasta `batch` tarjetas pendientes. Devuelve cuántas completó."""
    cfg = cfg or load_llm_config()
    rows = pending_cards(conn, batch)
    if not rows:
        return 0
    items = [{"word": r["word"], "context": r["context"]} for r in rows]
    system = load_prompt("vocab_cards", items=json.dumps(items, ensure_ascii=False, indent=1))
    result = generate_json(provider, VocabCardBatch, system, "Create the cards now.",
                           temperature=0.3, max_retries=cfg.max_retries)
    by_word = {c.word.lower().strip(): c for c in result.cards}
    done = 0
    for i, r in enumerate(rows):
        card = by_word.get(r["word"]) or (result.cards[i] if len(result.cards) == len(rows) else None)
        if card is None:
            continue
        conn.execute(
            """UPDATE card SET status='ready', family=?, collocations=?, definition_es=?, example_en=?, note_es=?
               WHERE id=?""",
            (card.family.model_dump_json(), json.dumps(card.collocations[:2], ensure_ascii=False),
             card.definition_es, card.example_en, card.false_friend_note_es, r["id"]))
        done += 1
    conn.commit()
    return done
