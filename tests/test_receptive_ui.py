from pathlib import Path

from streamlit.testing.v1 import AppTest

from ielts import db
from ielts.ingest import schema
from ielts.ingest.schema import save_test

from .test_ingest import mk_test

APP = str(Path(__file__).resolve().parent.parent / "app.py")
KEY = "rc_1_wednesday_reading"


def setup_env(monkeypatch, tmp_path, verified=True):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(schema, "DERIVED_DIR", tmp_path / "derived")
    save_test(mk_test(verified=verified), tmp_path / "derived")


def wednesday() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["session"] = {"weekday": "wednesday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py")
    return at


def test_reading_blocked_until_verified(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path, verified=False)
    at = wednesday().run()
    assert not at.exception, at.exception
    assert any("verificados" in w.value for w in at.warning)
    assert not [b for b in at.button if b.label.startswith("Corregir")]


def test_reading_flow_grades_and_records_causes(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    at = wednesday().run()
    assert not at.exception, at.exception
    assert any("Test Book · Test 1 · Pasaje 1" in m.value for m in at.markdown)
    pre = f"{KEY}_tb/test1_ans_"
    for q, v in {1: "TRUE", 2: "TRUE", 3: "NOT GIVEN", 6: "D", 7: "A"}.items():
        at.selectbox(key=pre + str(q)).select(v)
    at.text_input(key=pre + "4").input("orangutan")
    at.text_input(key=pre + "5").input("ceiling")
    next(b for b in at.button if b.label.startswith("Corregir")).click().run()
    assert not at.exception, at.exception
    assert any(m.label == "Aciertos" and m.value == "5/7" for m in at.metric)

    conn = db.connect(tmp_path / "t.db")
    errs = conn.execute("SELECT id, q FROM receptive_error ORDER BY q").fetchall()
    assert [e["q"] for e in errs] == [2, 5]
    at.selectbox(key=f"rs1_cause_{errs[0]['id']}").select("Not Given vs False").run()
    assert conn.execute("SELECT cause FROM receptive_error WHERE q=2").fetchone()["cause"] == "Not Given vs False"
    assert conn.execute("SELECT COUNT(*) c FROM error_log WHERE module='reading'").fetchone()["c"] == 1

    # siguiente bloque: análisis de errores, con los mismos fallos
    next(b for b in at.button if b.label.startswith("Siguiente")).click().run()
    assert not at.exception, at.exception
    assert any("P5" in m.value for m in at.markdown)


def test_verification_page_requires_confirmation_then_marks_verified(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path, verified=False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/4_Verificar_claves.py").run()
    assert not at.exception, at.exception
    mark = next(b for b in at.button if "Marcar como verificado" in b.label)
    assert mark.disabled
    at.checkbox[0].check().run()
    next(b for b in at.button if "Marcar como verificado" in b.label).click().run()
    assert not at.exception, at.exception
    assert schema.load_test("tb", 1, tmp_path / "derived").verified


def test_verification_page_empty_state(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(schema, "DERIVED_DIR", tmp_path / "nothing")
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/4_Verificar_claves.py").run()
    assert not at.exception and any("scripts/ingest.py" in i.value for i in at.info)
