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


def bridge_streamlit_secrets() -> None:
    """Copia los *secrets* planos de Streamlit (texto) a os.environ, sin pisar variables ya definidas."""
    try:
        import streamlit as st
        secrets = st.secrets
        keys = list(secrets.keys())
    except Exception:  # noqa: BLE001 — sin secrets.toml o fuera de Streamlit
        return
    for k in keys:
        try:
            v = secrets[k]
        except Exception:  # noqa: BLE001
            continue
        if isinstance(v, str):
            os.environ.setdefault(k, v)


def load_env() -> None:
    """.env (local) + secrets de Streamlit (cloud)."""
    load_env_file()
    bridge_streamlit_secrets()


def secret(name: str, default: str | None = None) -> str | None:
    """Valor de configuración sensible: variable de entorno o secret de Streamlit (`a.b` = tabla anidada)."""
    load_env()
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        node = st.secrets
        for part in name.split("."):
            node = node[part]
        return str(node) if not hasattr(node, "keys") else default
    except Exception:  # noqa: BLE001
        return default


def secret_section(name: str) -> dict:
    """Tabla anidada de los secrets (p. ej. `gcp_service_account`) como dict normal."""
    try:
        import streamlit as st
        return {k: v for k, v in dict(st.secrets[name]).items()}
    except Exception:  # noqa: BLE001
        return {}


def _toml_section(name: str, path: Path | None = None) -> dict:
    p = path or CONFIG_PATH
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f).get(name, {})


@dataclass(frozen=True)
class AppConfig:
    mode: str = "local"               # local | cloud
    timezone: str = ""                # p. ej. America/Lima; vacío = zona del sistema
    exam_date: str = ""               # YYYY-MM-DD; vacío = fechas de data/curriculum.yaml
    free_days: tuple[str, ...] = ()   # días libres extra (YYYY-MM-DD) cuando se usa exam_date

    @property
    def is_cloud(self) -> bool:
        return self.mode == "cloud"


def load_app_config(path: Path | None = None) -> AppConfig:
    load_env()
    app, plan = _toml_section("app", path), _toml_section("plan", path)
    cfg = AppConfig(mode=str(app.get("mode", "local")), timezone=str(app.get("timezone", "")),
                    exam_date=str(plan.get("exam_date", "")), free_days=tuple(plan.get("free_days", ())))
    env = {"mode": "IELTS_MODE", "timezone": "IELTS_TZ", "exam_date": "IELTS_EXAM_DATE"}
    over = {k: os.environ[v] for k, v in env.items() if os.environ.get(v)}
    return AppConfig(**{**cfg.__dict__, **over}) if over else cfg


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
    max_calls_per_day: int = 0          # tope diario de llamadas al LLM (0 = sin tope); protege tu crédito
    num_ctx: int = 8192
    timeout_s: float = 300
    max_retries: int = 2
    temperature_eval: float = 0.2
    temperature_gen: float = 0.8

    @property
    def active_model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.model


def load_llm_config(path: Path | None = None) -> LLMConfig:
    load_env()
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
    provider: str = "auto"            # auto (cloud→openai, local→local) | local (faster-whisper) | openai (API)
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "en"
    initial_prompt: str = ""
    openai_model: str = "whisper-1"   # el único de la API que devuelve timestamps por palabra


def load_stt_config(path: Path | None = None) -> STTConfig:
    load_env()
    data: dict = {}
    p = path or CONFIG_PATH
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f).get("stt", {})
    cfg = STTConfig(**{k: v for k, v in data.items() if k in STTConfig.__dataclass_fields__})
    if os.environ.get("IELTS_STT_MODEL"):
        cfg = STTConfig(**{**cfg.__dict__, "model": os.environ["IELTS_STT_MODEL"]})
    if os.environ.get("IELTS_STT_PROVIDER"):
        cfg = STTConfig(**{**cfg.__dict__, "provider": os.environ["IELTS_STT_PROVIDER"]})
    return cfg
