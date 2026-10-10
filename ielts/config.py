"""Lee config.toml (con overrides por variables de entorno)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    model: str = "gemma3:12b"
    host: str = "http://localhost:11434"
    num_ctx: int = 8192
    timeout_s: float = 300
    max_retries: int = 2
    temperature_eval: float = 0.2
    temperature_gen: float = 0.8


def load_llm_config(path: Path | None = None) -> LLMConfig:
    data: dict = {}
    p = path or CONFIG_PATH
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f).get("llm", {})
    cfg = LLMConfig(**{k: v for k, v in data.items() if k in LLMConfig.__dataclass_fields__})
    env = {"provider": "IELTS_LLM_PROVIDER", "model": "IELTS_LLM_MODEL", "host": "IELTS_OLLAMA_HOST"}
    overrides = {k: os.environ[v] for k, v in env.items() if os.environ.get(v)}
    if overrides:
        cfg = LLMConfig(**{**cfg.__dict__, **overrides})
    return cfg
