"""Consulta y exportación del error log."""
from __future__ import annotations

import csv
import io
import sqlite3

COLUMNS = ["date", "module", "fragment", "correction", "category", "explanation", "count"]


def query_errors(conn: sqlite3.Connection, *, modules: list[str] | None = None,
                 categories: list[str] | None = None, since: str | None = None,
                 until: str | None = None, min_count: int = 1, text: str = "") -> list[dict]:
    where, args = ["count >= ?"], [min_count]
    if modules:
        where.append(f"module IN ({','.join('?' * len(modules))})")
        args += modules
    if categories:
        where.append(f"category IN ({','.join('?' * len(categories))})")
        args += categories
    if since:
        where.append("date >= ?")
        args.append(since)
    if until:
        where.append("date <= ?")
        args.append(until)
    if text.strip():
        where.append("(fragment LIKE ? OR correction LIKE ? OR explanation LIKE ?)")
        args += [f"%{text.strip()}%"] * 3
    rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM error_log WHERE {' AND '.join(where)} "
                        "ORDER BY count DESC, date DESC, id DESC", args).fetchall()
    return [dict(r) for r in rows]


def distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    assert column in ("module", "category")
    return [r[0] for r in conn.execute(f"SELECT DISTINCT {column} FROM error_log ORDER BY 1")]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def to_markdown(rows: list[dict]) -> str:
    lines = ["# Error log", "", "| Fecha | Módulo | Fragmento | Corrección | Categoría | Explicación | Veces |",
             "|---|---|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for r in rows:
        lines.append("| " + " | ".join(esc(r[c]) for c in COLUMNS) + " |")
    return "\n".join(lines)
