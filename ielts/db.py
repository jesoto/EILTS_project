"""SQLite: progreso de bloques y niveles por habilidad (más tablas en hitos posteriores)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from . import clock

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ielts.db"
SKILLS = ["grammar", "writing", "reading", "listening", "speaking", "vocab"]
DEFAULT_LEVEL = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS block_log (
    week INTEGER NOT NULL,
    weekday TEXT NOT NULL,
    block_id TEXT NOT NULL,
    seconds INTEGER NOT NULL DEFAULT 0,
    done_at TEXT NOT NULL,
    PRIMARY KEY (week, weekday, block_id)
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS skill_level (
    skill TEXT PRIMARY KEY,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 10)
);
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module TEXT NOT NULL,
    fragment TEXT NOT NULL,
    correction TEXT NOT NULL,
    category TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 1,
    UNIQUE (module, fragment, correction, category)
);
CREATE TABLE IF NOT EXISTS error_event (      -- una fila por ocurrencia: permite contar «errores de esta semana»
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    skill TEXT NOT NULL,
    score REAL NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS skill_window (skill TEXT PRIMARY KEY, start_id INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS generated_exercise (
    hash TEXT PRIMARY KEY, kind TEXT NOT NULL, topic TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS card (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending (sin detalles) | ready
    source TEXT NOT NULL DEFAULT 'manual',    -- error_log | weekly | false_friend | awl | collocation | manual
    theme TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    family TEXT NOT NULL DEFAULT '{}',
    collocations TEXT NOT NULL DEFAULT '[]',
    definition_es TEXT NOT NULL DEFAULT '',
    example_en TEXT NOT NULL DEFAULT '',
    note_es TEXT NOT NULL DEFAULT '',
    user_sentence TEXT NOT NULL DEFAULT '',
    ease REAL NOT NULL DEFAULT 2.5,
    interval INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    due TEXT NOT NULL,
    created TEXT NOT NULL,
    last_review TEXT
);
CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    quality INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS speaking_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    week INTEGER NOT NULL,
    part TEXT NOT NULL,             -- p2 | p13
    prompt TEXT NOT NULL,
    transcript TEXT NOT NULL,
    metrics TEXT NOT NULL,
    evaluation TEXT,
    audio_path TEXT
);
CREATE TABLE IF NOT EXISTS receptive_attempt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    week INTEGER NOT NULL,
    skill TEXT NOT NULL,            -- reading | listening
    test_id TEXT NOT NULL,          -- p. ej. c17/test1
    unit TEXT NOT NULL,             -- p1 | p1,p2,p3 | l1 ... (pasajes/partes)
    raw INTEGER NOT NULL,
    total INTEGER NOT NULL,
    band REAL,                      -- solo si se hizo el test completo (40)
    qtype TEXT NOT NULL DEFAULT '', -- tipo de pregunta practicado (secciones sueltas)
    seconds INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS receptive_error (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    q INTEGER NOT NULL,
    qtype TEXT NOT NULL,
    user_answer TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    cause TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
    week INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    measured TEXT NOT NULL DEFAULT '{}',
    where_lost TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '',
    change_goal TEXT NOT NULL DEFAULT '',
    energy INTEGER NOT NULL,
    anxiety INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS doubt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    week INTEGER NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',   -- manual | error_log | speaking
    UNIQUE (week, text)
);
CREATE TABLE IF NOT EXISTS writing_submission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    week INTEGER NOT NULL,
    task TEXT NOT NULL,
    task_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    text TEXT NOT NULL,
    evaluation TEXT NOT NULL,
    rewrite TEXT
);
"""


def connect(path: str | Path | None = None, factory: type | None = None) -> sqlite3.Connection:
    p = Path(path or os.environ.get("IELTS_DB") or DB_PATH)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    # Streamlit ejecuta cada rerun en un hilo distinto y la conexión se cachea.
    conn = sqlite3.connect(str(p), check_same_thread=False, **({'factory': factory} if factory else {}))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO skill_level(skill, level) VALUES (?, ?)",
                     [(s, DEFAULT_LEVEL) for s in SKILLS])
    conn.commit()
    return conn


def mark_block_done(conn: sqlite3.Connection, week: int, weekday: str, block_id: str, seconds: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO block_log(week, weekday, block_id, seconds, done_at) VALUES (?,?,?,?,?)",
        (week, weekday, block_id, int(seconds), clock.timestamp()),
    )
    conn.commit()


def done_blocks(conn: sqlite3.Connection, week: int, weekday: str) -> set[str]:
    rows = conn.execute("SELECT block_id FROM block_log WHERE week=? AND weekday=?", (week, weekday))
    return {r["block_id"] for r in rows}


def day_is_done(conn: sqlite3.Connection, week: int, weekday: str, block_ids: list[str]) -> bool:
    return bool(block_ids) and set(block_ids) <= done_blocks(conn, week, weekday)


def get_level(conn: sqlite3.Connection, skill: str) -> int:
    return conn.execute("SELECT level FROM skill_level WHERE skill=?", (skill,)).fetchone()["level"]


def set_level(conn: sqlite3.Connection, skill: str, level: int) -> None:
    conn.execute("UPDATE skill_level SET level=? WHERE skill=?", (max(1, min(10, level)), skill))
    conn.commit()


# ---- error log ----
def log_error(conn: sqlite3.Connection, module: str, fragment: str, correction: str,
              category: str, explanation: str = "") -> None:
    """Guarda un error; si ya existe (módulo/fragmento/corrección/categoría) suma al conteo."""
    conn.execute(
        """INSERT INTO error_log(date, module, fragment, correction, category, explanation)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(module, fragment, correction, category)
           DO UPDATE SET count = count + 1, date = excluded.date""",
        (clock.now().date().isoformat(), module, fragment.strip(), correction.strip(), category, explanation),
    )
    conn.execute("INSERT INTO error_event(date, module, category) VALUES (?,?,?)",
                 (clock.now().date().isoformat(), module, category))
    if category in LEXICAL_CATEGORIES:
        queue_card_from_error(conn, fragment, correction, category, explanation)
    conn.commit()


LEXICAL_CATEGORIES = {"collocation", "false_friend", "word_form", "spelling"}


def queue_card_from_error(conn: sqlite3.Connection, fragment: str, correction: str, category: str,
                          explanation: str = "") -> None:
    """Los errores léxicos generan una tarjeta pendiente (los detalles los completa el LLM después)."""
    word = " ".join(correction.lower().split()).strip(" .,;:")
    if not word or len(word.split()) > 5:   # solo palabras/chunks, no oraciones enteras
        return
    today = clock.now().date().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO card(word, status, source, context, due, created)
           VALUES (?, 'pending', 'error_log', ?, ?, ?)""",
        (word, f"{fragment.strip()} → {correction.strip()} ({category}): {explanation}".strip(), today, today))


def top_categories(conn: sqlite3.Connection, since: str | None = None, limit: int = 3) -> list[tuple[str, int]]:
    """Categorías con más ocurrencias (desde `since`, inclusive). Las causas «other» de Reading/Listening
    (p. ej. «Not Given vs False») no son categorías lingüísticas y no cuentan."""
    q = ("SELECT category, COUNT(*) AS n FROM error_event "
         "WHERE NOT (module IN ('reading', 'listening') AND category = 'other')")
    args: tuple = ()
    if since:
        q += " AND date >= ?"
        args = (since,)
    q += " GROUP BY category ORDER BY n DESC, category LIMIT ?"
    return [(r["category"], r["n"]) for r in conn.execute(q, (*args, limit))]


# ---- rendimiento y dificultad ----
def record_attempt(conn: sqlite3.Connection, skill: str, score: float, detail: str = "") -> None:
    """score en 0..1. Ajusta el nivel con la ventana móvil de las últimas 5 sesiones."""
    conn.execute("INSERT INTO attempt(date, skill, score, detail) VALUES (?,?,?,?)",
                 (clock.timestamp(), skill, float(score), detail))
    conn.commit()
    adjust_level(conn, skill)


def adjust_level(conn: sqlite3.Connection, skill: str, window: int = 5) -> int:
    """>80 % medio → +1; <50 % → −1. Tras cambiar, la ventana se reinicia."""
    row = conn.execute("SELECT start_id FROM skill_window WHERE skill=?", (skill,)).fetchone()
    start = row["start_id"] if row else 0
    recent = conn.execute("SELECT id, score FROM attempt WHERE skill=? AND id>? ORDER BY id DESC LIMIT ?",
                          (skill, start, window)).fetchall()
    level = get_level(conn, skill)
    if len(recent) < window:
        return level
    avg = sum(r["score"] for r in recent) / window
    new = level + 1 if avg > 0.8 else level - 1 if avg < 0.5 else level
    new = max(1, min(10, new))
    if new != level:
        set_level(conn, skill, new)
        conn.execute("INSERT OR REPLACE INTO skill_window(skill, start_id) VALUES (?,?)", (skill, recent[0]["id"]))
        conn.commit()
    return new


def exercise_seen(conn: sqlite3.Connection, h: str) -> bool:
    return conn.execute("SELECT 1 FROM generated_exercise WHERE hash=?", (h,)).fetchone() is not None


def remember_exercise(conn: sqlite3.Connection, h: str, kind: str, topic: str) -> None:
    conn.execute("INSERT OR IGNORE INTO generated_exercise(hash, kind, topic, created) VALUES (?,?,?,?)",
                 (h, kind, topic, clock.timestamp()))
    conn.commit()
