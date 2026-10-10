"""Auditoría semanal del domingo y lista de dudas para la profesora."""
from __future__ import annotations

import json
import sqlite3
from datetime import date

LOW_ENERGY = 2      # energía ≤ 2 → baja
HIGH_ANXIETY = 4    # ansiedad ≥ 4 → alta
LOAD_ADVICE = ("Llevas dos semanas seguidas con energía baja o ansiedad alta. Considera reducir la carga: "
               "quita un bloque por día o convierte el sábado en medio simulacro, y habla con tu profesora.")


def save_audit(conn: sqlite3.Connection, week: int, *, measured: dict, where_lost: str, why: str,
               change_goal: str, energy: int, anxiety: int, today: date | None = None) -> None:
    if not (1 <= energy <= 5 and 1 <= anxiety <= 5):
        raise ValueError("energía y ansiedad van de 1 a 5")
    conn.execute(
        """INSERT INTO audit(week, date, measured, where_lost, why, change_goal, energy, anxiety)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(week) DO UPDATE SET date=excluded.date, measured=excluded.measured, where_lost=excluded.where_lost,
             why=excluded.why, change_goal=excluded.change_goal, energy=excluded.energy, anxiety=excluded.anxiety""",
        (week, (today or date.today()).isoformat(), json.dumps(measured, ensure_ascii=False, default=str),
         where_lost, why, change_goal, energy, anxiety))
    conn.commit()


def get_audit(conn: sqlite3.Connection, week: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM audit WHERE week=?", (week,)).fetchone()


def audits(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM audit ORDER BY week").fetchall()


def is_low(row: sqlite3.Row) -> bool:
    return row["energy"] <= LOW_ENERGY or row["anxiety"] >= HIGH_ANXIETY


def load_warning(conn: sqlite3.Connection) -> str | None:
    """Si las dos últimas auditorías (semanas consecutivas) son «malas», sugiere reducir la carga."""
    rows = conn.execute("SELECT * FROM audit ORDER BY week DESC LIMIT 2").fetchall()
    if len(rows) == 2 and rows[0]["week"] - rows[1]["week"] == 1 and all(is_low(r) for r in rows):
        return LOAD_ADVICE
    return None


def current_goal(conn: sqlite3.Connection, week: int) -> str | None:
    """El objetivo concreto de la auditoría de la semana anterior."""
    row = get_audit(conn, week - 1)
    return row["change_goal"] if row and row["change_goal"].strip() else None


# ------------------------------------------------------------------ dudas para la profesora
def add_doubt(conn: sqlite3.Connection, week: int, text: str, source: str = "manual",
              today: date | None = None) -> bool:
    text = " ".join(text.split())
    if not text:
        return False
    cur = conn.execute("INSERT OR IGNORE INTO doubt(date, week, text, source) VALUES (?,?,?,?)",
                       ((today or date.today()).isoformat(), week, text, source))
    conn.commit()
    return cur.rowcount > 0


def delete_doubt(conn: sqlite3.Connection, doubt_id: int) -> None:
    conn.execute("DELETE FROM doubt WHERE id=?", (doubt_id,))
    conn.commit()


def list_doubts(conn: sqlite3.Connection, week: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM doubt WHERE week=? ORDER BY id", (week,)).fetchall()


def suggest_doubts(conn: sqlite3.Connection, limit: int = 5) -> list[str]:
    """Dudas candidatas: los errores que más se repiten en el error log."""
    rows = conn.execute("SELECT fragment, correction, category, count FROM error_log WHERE count >= 2 "
                        "AND module NOT IN ('reading', 'listening') ORDER BY count DESC, date DESC LIMIT ?", (limit,))
    return [f"¿Por qué «{r['fragment']}» se corrige a «{r['correction']}»? ({r['category']}, {r['count']} veces)"
            for r in rows]
