"""Lee config.toml (con overrides por variables de entorno)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
ENV_PATH = ROOT / ".env"


def load_env_file(path: Path | None = None) -> None:
    """Carga KEY=VALUE de .env en os.environ (sin pisar variables ya definidas). Nunca imprime valores."""
    p = path or ENV_PATH
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"            # ollama | openai
    model: str = "gemma3:12b"           # modelo de Ollama
    host: str = "http://localhost:11434"
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_key_env: str = "OPENAI_API_KEY"
    price_in_per_m: float = 0.0         # USD por millón de tokens de entrada (para estimar el gasto)
    price_out_per_m: float = 0.0        # USD por millón de tokens de salida
    num_ctx: int = 8192
    timeout_s: float = 300
    max_retries: int = 2
    temperature_eval: float = 0.2
    temperature_gen: float = 0.8

    @property
    def active_model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.model


def load_llm_config(path: Path | None = None) -> LLMConfig:
    load_env_file()
    data: dict = {}
    p = path or CONFIG_PATH
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f).get("llm", {})
    cfg = LLMConfig(**{k: v for k, v in data.items() if k in LLMConfig.__dataclass_fields__})
    env = {"provider": "IELTS_LLM_PROVIDER", "model": "IELTS_LLM_MODEL", "host": "IELTS_OLLAMA_HOST",
           "openai_model": "IELTS_OPENAI_MODEL"}
    overrides = {k: os.environ[v] for k, v in env.items() if os.environ.get(v)}
    if overrides:
        cfg = LLMConfig(**{**cfg.__dict__, **overrides})
    return cfg


@dataclass(frozen=True)
class STTConfig:
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "en"
    initial_prompt: str = ""


def load_stt_config(path: Path | None = None) -> STTConfig:
    data: dict = {}
    p = path or CONFIG_PATH
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f).get("stt", {})
    cfg = STTConfig(**{k: v for k, v in data.items() if k in STTConfig.__dataclass_fields__})
    if os.environ.get("IELTS_STT_MODEL"):
        cfg = STTConfig(**{**cfg.__dict__, "model": os.environ["IELTS_STT_MODEL"]})
    return cfg
