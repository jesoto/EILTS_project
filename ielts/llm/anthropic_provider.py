from __future__ import annotations

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    """Stub para el futuro: la app corre 100 % local con Ollama."""

    def chat(self, system, user, *, temperature, json_schema=None, seed=None) -> str:
        raise NotImplementedError("AnthropicProvider aún no está implementado; usa provider = \"ollama\".")
