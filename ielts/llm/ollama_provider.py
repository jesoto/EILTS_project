from __future__ import annotations

import httpx

from ..config import LLMConfig, load_llm_config
from .base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, config: LLMConfig | None = None):
        self.cfg = config or load_llm_config()

    def chat(self, system, user, *, temperature, json_schema=None, seed=None) -> str:
        options = {"temperature": temperature, "num_ctx": self.cfg.num_ctx}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": self.cfg.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": options,
        }
        if json_schema is not None:
            payload["format"] = json_schema  # salida estructurada de Ollama
        try:
            r = httpx.post(f"{self.cfg.host}/api/chat", json=payload, timeout=self.cfg.timeout_s)
            r.raise_for_status()
        except httpx.HTTPError as e:
            body = e.response.text[:500] if isinstance(e, httpx.HTTPStatusError) else ""
            raise LLMError(f"No se pudo usar Ollama ({self.cfg.host}, modelo {self.cfg.model}): {e} {body}") from e
        return r.json()["message"]["content"]
