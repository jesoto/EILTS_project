"""Recorre la app con los datos REALES de Cambridge 17 (copia temporal verificada). Se salta si no hay ingesta."""
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ielts import db
from ielts.ingest import schema
from ielts.ingest.schema import load_test, save_test

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "data" / "derived" / "c17"
APP = str(ROOT / "app.py")

pytestmark = pytest.mark.skipif(not (REAL / "test1.json").exists() or not (ROOT / "resources").exists(),
                                reason="falta la ingesta de c17 (uv run python scripts/ingest.py)")


@pytest.fixture()
def env(monkeypatch, tmp_path):
    derived = tmp_path / "derived"
    shutil.copytree(REAL, derived / "c17")
    for n in (1, 2, 3, 4):
        t = load_test("c17", n, derived)
        t.mark_verified()
        save_test(t, derived)
    monkeypatch.setattr(schema, "DERIVED_DIR", derived)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    return tmp_path


def session(weekday, week, phase, nexts=0) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["session"] = {"weekday": weekday, "week": week, "phase": phase, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    for _ in range(nexts):
        next(b for b in at.button if b.label.startswith("Siguiente")).click().run()
    assert not at.exception, at.exception
    return at


def submit(at):
    next(b for b in at.button if b.label.startswith("Corregir")).click().run()
    assert not at.exception, at.exception


def test_phase1_reading_week1_uses_a_passage_with_tfng(env):
    at = session("wednesday", 1, 1)
    heads = [m.value for m in at.markdown if m.value.startswith("## ")]
    assert heads and "Pasaje" in heads[0]
    assert any("tfng" in m.value or "ynng" in m.value for m in at.markdown)
    submit(at)
    assert any(m.label == "Aciertos" for m in at.metric)


def test_phase1_listening_week1_is_part1_with_audio_and_speed(env):
    at = session("tuesday", 1, 1)
    assert any("Parte 1" in m.value for m in at.markdown if m.value.startswith("## "))
    assert at.radio and at.radio[0].value == "1.0x"
    submit(at)
    raw = next(m.value for m in at.metric if m.label == "Aciertos")
    assert raw.startswith("0/10")
    spell = db.connect(env / "t.db").execute("SELECT COUNT(*) c FROM receptive_error").fetchone()["c"]
    assert spell == 10          # 10 respuestas vacías = 10 errores registrados


def test_week8_listening_defaults_to_125x(env):
    at = session("tuesday", 8, 2)
    assert at.radio[0].value == "1.25x"


def test_phase1_saturday_sections_filter_question_type(env):
    at = session("saturday", 3, 1)            # semana 3: Completion · Listening sec. 3
    heads = [m.value for m in at.markdown if m.value.startswith("## ")]
    assert len(heads) in (1, 2) and all("Parte 3" in h for h in heads)
    at = session("saturday", 3, 1, nexts=1)   # bloque 2: Reading por tipo
    groups = [m.value for m in at.markdown if m.value.startswith("**Preguntas")]
    assert groups and all("completion" in g for g in groups)


def test_phase2_full_reading_gives_a_band(env):
    at = session("saturday", 5, 2, nexts=1)   # bloque 2: Reading completo (3 pasajes, 40 preguntas)
    assert len([m for m in at.markdown if m.value.startswith("## ")]) == 3
    submit(at)
    assert any(m.label == "Aciertos" and m.value == "0/40" for m in at.metric)
    assert any(m.label == "Banda estimada (aproximada)" for m in at.metric)
    a = db.connect(env / "t.db").execute("SELECT band FROM receptive_attempt WHERE unit='all'").fetchone()
    assert a is not None and a["band"] is not None


def test_phase3_simulacro_renders_three_tabs(env):
    at = session("saturday", 9, 3)
    assert len(at.tabs) == 3 and not at.exception


def test_listening_full_skips_test_without_all_audio(env):
    at = session("saturday", 5, 2)            # bloque 1: Listening completo
    heads = [m.value for m in at.markdown if m.value.startswith("## ")]
    assert len(heads) == 4 and not any("Test 2" in h for h in heads)     # Test 2 no tiene la parte 4
