"""Interfaz común de proveedores de LLM."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """Fallo de conexión o de validación tras agotar reintentos."""


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, system: str, user: str, *, temperature: float,
             json_schema: dict | None = None, seed: int | None = None) -> str:
        """Devuelve el texto de la respuesta. Si hay json_schema, debe ser JSON."""
