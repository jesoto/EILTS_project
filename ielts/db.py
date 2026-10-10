"""SQLite: progreso de bloques y niveles por habilidad (más tablas en hitos posteriores)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

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
CREATE TABLE IF NOT EXISTS skill_level (
    skill TEXT PRIMARY KEY,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 10)
);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path or os.environ.get("IELTS_DB") or DB_PATH)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    # Streamlit ejecuta cada rerun en un hilo distinto y la conexión se cachea.
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO skill_level(skill, level) VALUES (?, ?)",
                     [(s, DEFAULT_LEVEL) for s in SKILLS])
    conn.commit()
    return conn


def mark_block_done(conn: sqlite3.Connection, week: int, weekday: str, block_id: str, seconds: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO block_log(week, weekday, block_id, seconds, done_at) VALUES (?,?,?,?,?)",
        (week, weekday, block_id, int(seconds), datetime.now().isoformat(timespec="seconds")),
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
