import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from .fakes import FakeProvider
from .test_llm import EVAL

APP = str(Path(__file__).resolve().parent.parent / "app.py")
ESSAY = ("It is clear that education matters. " * 4 + "\n\n" + "However, although costs rise, people benefit. " * 4)
EXERCISE = {"kind": "gap_fill", "instruction": "Fill the gap.", "items": [
    {"prompt": "____ is important to study.", "answer": "It", "options": ["It", "Is", "There"], "explicacion_es": "sujeto"},
    {"prompt": "____ are many reasons.", "answer": "There", "explicacion_es": "there are"}]}
REWRITE = {"resultados": [
    {"original": "s0", "reescrita": "a", "correcta": True, "mejor_version": "a"},
    {"original": "s1", "reescrita": "b", "correcta": False, "problema_restante_es": "mal", "mejor_version": "B"},
    {"original": "s2", "reescrita": "c", "correcta": True, "mejor_version": "c"}]}
PRODUCTION = {"errores": [{"fragmento": "x", "correccion": "y", "categoria": "articles", "explicacion_es": "z"}],
              "comentario_es": "bien", "version_corregida": "ok", "topic_used_correctly": True}


def next_button(at):
    return next(b for b in at.button if b.label.startswith(("Siguiente", "Terminar")))


def test_monday_writing_rewrite_grammar_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    fake = FakeProvider(json.dumps(EVAL), json.dumps(REWRITE), json.dumps(EXERCISE), json.dumps(PRODUCTION))
    monkeypatch.setattr("ielts.llm.client.get_provider", lambda cfg=None: fake)

    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["session"] = {"weekday": "monday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    assert not at.exception

    # --- Writing Task 2 ---
    at.text_area(key="wr_1_monday_writing_t2_text").input(ESSAY).run()
    assert any("Palabras" in m.value for m in at.markdown)
    at.button(key="wr_1_monday_writing_t2_send").click().run()
    assert not at.exception, at.exception
    assert any("banda estimada (aproximada)" in s.value for s in at.subheader)
    assert any(m.value.startswith("Is important") or "Is important" in m.value for m in at.markdown)
    next_button(at).click().run()

    # --- Reescritura: bloqueada hasta evaluar ---
    assert next_button(at).disabled
    for i in (1, 2, 3):
        at.text_input(key=f"rw_1_r{i}").input(f"rewrite {i}")
    submit = next(b for b in at.button if b.label == "Evaluar reescritura")
    submit.click().run()
    assert not at.exception, at.exception
    assert not next_button(at).disabled
    next_button(at).click().run()

    # --- Gramática ---
    at.button(key="gram_1_monday_grammar_go").click().run()
    assert not at.exception, at.exception
    assert any("gap_fill" in c.value for c in at.caption)
    at.text_input[0].input("There") if at.text_input else None
    next(b for b in at.button if b.label == "Corregir").click().run()
    assert not at.exception, at.exception
    assert any("Aciertos" == m.label for m in at.metric)

    conn = __import__("ielts.db", fromlist=["x"]).connect(tmp_path / "t.db")
    assert conn.execute("SELECT COUNT(*) c FROM error_log").fetchone()["c"] >= 2
    assert conn.execute("SELECT COUNT(*) c FROM attempt WHERE skill='writing'").fetchone()["c"] == 2
