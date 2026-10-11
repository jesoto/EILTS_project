"""Resumen del gasto en tokens de OpenAI a partir de data/llm_usage.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import LLMConfig, load_llm_config
from .openai_provider import USAGE_PATH


def usage_summary(path: Path | None = None, cfg: LLMConfig | None = None) -> dict:
    """Totales de llamadas/tokens y coste estimado con los precios de config.toml (USD por millón de tokens)."""
    cfg = cfg or load_llm_config()
    p = path or USAGE_PATH
    calls = pin = pout = 0
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            calls += 1
            pin += int(row.get("prompt_tokens", 0))
            pout += int(row.get("completion_tokens", 0))
    cost = (pin * cfg.price_in_per_m + pout * cfg.price_out_per_m) / 1_000_000
    return {"calls": calls, "prompt_tokens": pin, "completion_tokens": pout, "cost_usd": round(cost, 6),
            "priced": bool(cfg.price_in_per_m or cfg.price_out_per_m)}
