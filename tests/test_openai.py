import json

import httpx
import pytest

from ielts import config as cfgmod
from ielts.config import LLMConfig, load_env_file, load_llm_config
from ielts.llm.base import LLMError
from ielts.llm.client import generate_json, get_provider
from ielts.llm.openai_provider import OpenAIProvider
from ielts.llm.schemas import RewriteEvaluation
from ielts.llm.usage import usage_summary

KEY = "sk-test-SECRET-0123456789"
OK = {"resultados": []}


def completion(content, usage=(100, 50)):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}})


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)


def provider(handler, tmp_path, **cfg):
    config = LLMConfig(provider="openai", openai_model="gpt-4.1-mini", price_in_per_m=0.4, price_out_per_m=1.6, **cfg)
    return OpenAIProvider(config, transport=httpx.MockTransport(handler), usage_path=tmp_path / "usage.jsonl",
                          sleep=lambda s: None)


def test_request_shape_auth_json_mode_schema_and_usage_log(env, tmp_path):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return completion(json.dumps(OK), usage=(1200, 300))

    p = provider(handler, tmp_path)
    out = generate_json(p, RewriteEvaluation, "Judge the rewrites. Return JSON.", "go", temperature=0.2, seed=7)
    assert out.resultados == []
    assert seen["auth"] == f"Bearer {KEY}" and seen["url"] == "https://api.openai.com/v1/chat/completions"
    b = seen["body"]
    assert b["model"] == "gpt-4.1-mini" and b["temperature"] == 0.2 and b["seed"] == 7
    assert b["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in b["messages"][0]["content"] and "resultados" in b["messages"][0]["content"]
    s = usage_summary(tmp_path / "usage.jsonl", p.cfg)
    assert (s["calls"], s["prompt_tokens"], s["completion_tokens"]) == (1, 1200, 300)
    assert s["cost_usd"] == pytest.approx(1200 * 0.4e-6 + 300 * 1.6e-6)


def test_invalid_json_is_retried_through_generate_json(env, tmp_path):
    replies = iter(["not json", json.dumps(OK)])
    p = provider(lambda r: completion(next(replies)), tmp_path)
    assert generate_json(p, RewriteEvaluation, "s", "u", temperature=0.2).resultados == []
    assert usage_summary(tmp_path / "usage.jsonl", p.cfg)["calls"] == 2


def test_retries_without_temperature_when_model_rejects_it(env, tmp_path):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0.2"}})
        return completion("{}")

    assert provider(handler, tmp_path).chat("s", "u", temperature=0.2) == "{}"
    assert "temperature" in bodies[0] and "temperature" not in bodies[1] and len(bodies) == 2


def test_rate_limit_is_retried_but_no_quota_is_not(env, tmp_path):
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "slow down"}}) if len(calls) < 3 else completion("{}")
    assert provider(flaky, tmp_path).chat("s", "u", temperature=0.2) == "{}" and len(calls) == 3

    calls.clear()

    def no_quota(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"code": "insufficient_quota", "message": "insufficient_quota"}})
    with pytest.raises(LLMError, match="Sin crédito"):
        provider(no_quota, tmp_path).chat("s", "u", temperature=0.2)
    assert len(calls) == 1


def test_errors_never_leak_the_key(env, tmp_path):
    with pytest.raises(LLMError, match="rechazó la clave") as e1:
        provider(lambda r: httpx.Response(401, text=f"bad key {KEY}"), tmp_path).chat("s", "u", temperature=0.2)
    assert KEY not in str(e1.value)
    with pytest.raises(LLMError) as e2:
        provider(lambda r: httpx.Response(400, text=f"oops {KEY} oops"), tmp_path).chat("s", "u", temperature=0.2)
    assert KEY not in str(e2.value) and "***" in str(e2.value)


def test_missing_key_gives_actionable_message(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError, match=r"\.env"):
        provider(lambda r: completion("{}"), tmp_path).chat("s", "u", temperature=0.2)


def test_usage_log_failure_does_not_break_the_call(env, tmp_path):
    p = provider(lambda r: completion("{}"), tmp_path)
    p._usage_path = tmp_path            # un directorio: abrirlo para escribir falla
    assert p.chat("s", "u", temperature=0.2) == "{}"


def test_get_provider_selects_openai_and_env_override(monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("IELTS_OPENAI_MODEL", "gpt-5.4-mini")
    cfg = load_llm_config()
    assert cfg.provider == "openai" and cfg.active_model == "gpt-5.4-mini"
    assert isinstance(get_provider(cfg), OpenAIProvider)
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "ollama")
    assert load_llm_config().active_model == "gemma3:12b"


def test_config_toml_uses_openai_with_cheap_model_and_low_eval_temperature():
    cfg = load_llm_config()
    assert cfg.openai_model and cfg.temperature_eval <= 0.3 and cfg.price_in_per_m > 0


def test_load_env_file_parses_without_overriding(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# comentario\nOPENAI_API_KEY="sk-from-file"\nexport OTHER = plain \nEMPTY=\nnotakeyline\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    monkeypatch.setenv("EMPTY", "keep")
    load_env_file(f)
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-from-file" and os.environ["OTHER"] == "plain" and os.environ["EMPTY"] == "keep"
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    load_env_file(f)
    assert os.environ["OPENAI_API_KEY"] == "already-set"          # no pisa lo ya definido
    load_env_file(tmp_path / "no-existe")                           # archivo inexistente: sin error
    assert cfgmod.ENV_PATH.name == ".env"
