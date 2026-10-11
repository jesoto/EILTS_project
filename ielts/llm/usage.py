"""Registro del gasto de tokens de OpenAI: archivo local (.jsonl) o tabla `llm_usage` de la base de datos."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .. import clock
from ..config import ROOT, LLMConfig, load_llm_config

USAGE_PATH = ROOT / "data" / "llm_usage.jsonl"       # ignorado por git


class UsageTracker(Protocol):
    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None: ...
    def rows(self) -> list[dict]: ...


def _today_prefix() -> str:
    return clock.now().date().isoformat()


class FileUsage:
    def __init__(self, path: Path | None = None):
        self.path = path or USAGE_PATH

    def record(self, model, prompt_tokens, completion_tokens):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": clock.timestamp(), "model": model, "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens}) + "\n")
        except OSError:
            pass    # el registro de gasto nunca debe romper una evaluación

    def rows(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class DbUsage:
    """Tabla llm_usage: persiste junto al resto de datos (también en la nube)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, model, prompt_tokens, completion_tokens):
        try:
            self.conn.execute("INSERT INTO llm_usage(ts, model, prompt_tokens, completion_tokens) VALUES (?,?,?,?)",
                              (clock.timestamp(), model, prompt_tokens, completion_tokens))
            self.conn.commit()
        except sqlite3.Error:
            pass

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT ts, model, prompt_tokens, completion_tokens FROM llm_usage")]


def calls_today(tracker: UsageTracker) -> int:
    prefix = _today_prefix()
    return sum(1 for r in tracker.rows() if str(r.get("ts", "")).startswith(prefix))


def usage_summary(path: Path | None = None, cfg: LLMConfig | None = None, tracker: UsageTracker | None = None) -> dict:
    """Totales de llamadas/tokens y coste estimado con los precios de config.toml (USD por millón de tokens)."""
    cfg = cfg or load_llm_config()
    rows = (tracker or FileUsage(path)).rows()
    pin = sum(int(r.get("prompt_tokens", 0)) for r in rows)
    pout = sum(int(r.get("completion_tokens", 0)) for r in rows)
    cost = (pin * cfg.price_in_per_m + pout * cfg.price_out_per_m) / 1_000_000
    return {"calls": len(rows), "prompt_tokens": pin, "completion_tokens": pout, "cost_usd": round(cost, 6),
            "priced": bool(cfg.price_in_per_m or cfg.price_out_per_m), "calls_today": calls_today(tracker or FileUsage(path))}
