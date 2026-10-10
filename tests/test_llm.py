import json

import pytest

from ielts.config import load_llm_config
from ielts.llm.base import LLMError
from ielts.llm.client import generate_json, load_prompt
from ielts.llm.schemas import ErrorItem, GrammarExercise, RewriteEvaluation, WritingEvaluation

from .fakes import FakeProvider

EVAL = {
    "ta_tr": {"banda": 5.7, "justificacion_es": "ok"}, "cc": {"banda": 6, "justificacion_es": "ok"},
    "lr": {"banda": 5.5, "justificacion_es": "ok"}, "gra": {"banda": 5, "justificacion_es": "ok"},
    "errores": [{"fragmento": "Is important", "correccion": "It is important", "categoria": "subject_omission",
                 "explicacion_es": "falta sujeto"},
                {"fragmento": "x", "correccion": "y", "categoria": "not_a_category", "explicacion_es": "z"}],
    "oraciones_a_reescribir": [{"original": f"s{i}", "problema_es": "p"} for i in range(3)],
    "parrafo_mejorado": {"original": "a", "mejorado": "b", "notas_es": "c"},
}


def test_valid_json_first_try():
    p = FakeProvider(json.dumps(EVAL))
    ev = generate_json(p, WritingEvaluation, "sys", "user", temperature=0.2)
    assert ev.ta_tr.banda == 5.5            # 5.7 → media banda más cercana
    assert ev.errores[1].categoria.value == "other"  # categoría desconocida → other
    assert len(p.calls) == 1
    assert p.calls[0]["schema"]["title"] == "WritingEvaluation"


def test_retry_then_success_and_error_is_fed_back():
    p = FakeProvider("not json at all", json.dumps({**EVAL, "oraciones_a_reescribir": []}), "```json\n" + json.dumps(EVAL) + "\n```")
    ev = generate_json(p, WritingEvaluation, "sys", "user", temperature=0.2, max_retries=2)
    assert ev.cc.banda == 6.0
    assert len(p.calls) == 3
    assert "invalid JSON" in p.calls[1]["user"]


def test_gives_up_after_max_retries():
    p = FakeProvider("bad", "bad", "bad", "bad")
    with pytest.raises(LLMError):
        generate_json(p, RewriteEvaluation, "s", "u", temperature=0.2, max_retries=2)
    assert len(p.calls) == 3  # intento inicial + 2 reintentos


def test_seed_changes_between_retries():
    p = FakeProvider("bad", json.dumps({"resultados": []}))
    generate_json(p, RewriteEvaluation, "s", "u", temperature=0.2, seed=10)
    assert [c["seed"] for c in p.calls] == [10, 11]


def test_prompt_loader_and_config():
    text = load_prompt("grammar_generate", topic="T", kind="gap_fill", n_items=3, level=2, phase=1,
                       frequent_errors="x", interference="y", seed=1)
    assert "{{" not in text and "gap_fill" in text
    cfg = load_llm_config()
    assert cfg.temperature_eval <= 0.3 and cfg.model


def test_env_override(monkeypatch):
    monkeypatch.setenv("IELTS_LLM_MODEL", "qwen2.5:7b-instruct")
    assert load_llm_config().model == "qwen2.5:7b-instruct"


def test_schema_validation_of_exercise():
    GrammarExercise.model_validate({"kind": "gap_fill", "instruction": "i",
                                    "items": [{"prompt": "a ____", "answer": "b"}]})
    with pytest.raises(Exception):
        GrammarExercise.model_validate({"kind": "gap_fill", "instruction": "i", "items": []})
    assert ErrorItem(fragmento="a", correccion="b", categoria="articles", explicacion_es="c")
