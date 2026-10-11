"""Proveedor de OpenAI (Chat Completions, modo JSON). La clave se lee de OPENAI_API_KEY (.env o secrets)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from ..config import LLMConfig, load_llm_config
from .base import LLMError, LLMProvider
from .usage import USAGE_PATH, FileUsage, UsageTracker, calls_today


class OpenAIProvider(LLMProvider):
    def __init__(self, config: LLMConfig | None = None, *, transport: httpx.BaseTransport | None = None,
                 usage_path: Path | None = None, usage: UsageTracker | None = None, sleep=time.sleep):
        self.cfg = config or load_llm_config()
        self._transport = transport          # inyectable en tests
        self.usage = usage or FileUsage(usage_path or USAGE_PATH)
        self._sleep = sleep

    # -- utilidades
    def _key(self) -> str:
        key = os.environ.get(self.cfg.openai_key_env, "").strip()
        if not key:
            raise LLMError(f"Falta {self.cfg.openai_key_env}: añádela al archivo .env de la carpeta principal.")
        return key

    def _redact(self, text: str) -> str:
        key = os.environ.get(self.cfg.openai_key_env, "")
        return text.replace(key, "***") if key else text

    def _log_usage(self, usage: dict) -> None:
        self.usage.record(self.cfg.openai_model, int(usage.get("prompt_tokens", 0)),
                          int(usage.get("completion_tokens", 0)))

    def _check_daily_cap(self) -> None:
        cap = self.cfg.max_calls_per_day
        if cap and calls_today(self.usage) >= cap:
            raise LLMError(f"Límite diario de llamadas al LLM alcanzado ({cap}). Se reinicia mañana; "
                           "puedes subirlo en config.toml (max_calls_per_day).")

    # -- API
    def chat(self, system, user, *, temperature, json_schema=None, seed=None) -> str:
        key = self._key()
        self._check_daily_cap()
        if json_schema is not None:
            system = (f"{system}\n\nRespond with ONE JSON object that conforms to this JSON Schema "
                      f"(no extra text):\n{json.dumps(json_schema)}")
        payload: dict = {"model": self.cfg.openai_model, "temperature": temperature,
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if seed is not None:
            payload["seed"] = seed
        headers = {"Authorization": f"Bearer {key}"}
        url = f"{self.cfg.openai_base_url}/chat/completions"
        dropped_temperature = False
        for attempt in range(3):
            try:
                with httpx.Client(transport=self._transport, timeout=self.cfg.timeout_s) as client:
                    r = client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"No se pudo conectar con OpenAI: {self._redact(str(e))}") from e
            if r.status_code == 200:
                data = r.json()
                self._log_usage(data.get("usage", {}))
                return data["choices"][0]["message"]["content"]
            body = self._redact(r.text[:400])
            if r.status_code == 400 and "temperature" in body and not dropped_temperature:
                payload.pop("temperature", None)          # algunos modelos solo admiten la temperatura por defecto
                dropped_temperature = True
                continue
            if r.status_code == 401:
                raise LLMError("OpenAI rechazó la clave (401): revisa OPENAI_API_KEY en .env.")
            if r.status_code == 429 and "insufficient_quota" in body:
                raise LLMError("Sin crédito en la cuenta de OpenAI (insufficient_quota).")
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                self._sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"OpenAI devolvió {r.status_code}: {body}")
        raise LLMError("OpenAI no respondió tras varios intentos.")
