"""generate_json: llamada al LLM con salida JSON validada por pydantic y reintentos."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import LLMConfig, load_llm_config
from .base import LLMError, LLMProvider

T = TypeVar("T", bound=BaseModel)
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def get_provider(cfg: LLMConfig | None = None) -> LLMProvider:
    cfg = cfg or load_llm_config()
    if cfg.provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(cfg)
    if cfg.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    raise ValueError(f"provider desconocido: {cfg.provider}")


def load_prompt(name: str, **fields: str) -> str:
    """Lee ielts/llm/prompts/<name>.md y sustituye {{campo}}."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for k, v in fields.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    if not raw.startswith(("{", "[")):
        start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
        if start >= 0:
            raw = raw[start:]
    return raw


def generate_json(provider: LLMProvider, model_cls: type[T], system: str, user: str, *,
                  temperature: float, max_retries: int = 2, seed: int | None = None) -> T:
    """Pide JSON, valida con pydantic y reintenta (máx. `max_retries`) si no valida."""
    schema = model_cls.model_json_schema()
    prompt = user
    last_error = ""
    for attempt in range(max_retries + 1):
        raw = provider.chat(system, prompt, temperature=temperature, json_schema=schema,
                            seed=None if seed is None else seed + attempt)
        try:
            return model_cls.model_validate(json.loads(_extract_json(raw)))
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = str(e)[:600]
            prompt = (f"{user}\n\nYour previous answer was invalid JSON for the required schema:\n"
                      f"{last_error}\nReturn ONLY corrected JSON that matches the schema.")
    raise LLMError(f"El LLM no devolvió JSON válido tras {max_retries + 1} intentos: {last_error}")
