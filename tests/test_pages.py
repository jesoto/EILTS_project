import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ielts import db, srs

from .fakes import FakeProvider
from .test_srs import card_json

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_page(monkeypatch, tmp_path, page, provider=None, today="2026-10-12"):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("IELTS_TODAY", today)
    if provider:
        monkeypatch.setattr("ielts.llm.client.get_provider", lambda cfg=None: provider)
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page(page)
    return at


def test_error_log_page_empty_and_filled(monkeypatch, tmp_path):
    at = run_page(monkeypatch, tmp_path, "pages/2_Error_log.py").run()
    assert not at.exception and any("Aún no hay errores" in i.value for i in at.info)

    conn = db.connect(tmp_path / "t.db")
    db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission", "falta sujeto")
    at = run_page(monkeypatch, tmp_path, "pages/2_Error_log.py").run()
    assert not at.exception and at.dataframe and at.multiselect
    assert any(m.label == "subject_omission" for m in at.metric)


def test_vocab_page_fills_pending_and_reviews(monkeypatch, tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.log_error(conn, "writing", "make a research", "conduct research", "collocation", "colocación")
    p = FakeProvider(json.dumps({"cards": [card_json("conduct research")]}))
    at = run_page(monkeypatch, tmp_path, "pages/3_Vocabulario.py", p).run()
    assert not at.exception, at.exception
    assert any(m.value == "1" and m.label == "Por repasar hoy" for m in at.metric)
    assert any("conduct research" in m.value for m in at.markdown)
    at.text_input[0].input("Scientists conduct research.").run()
    next(b for b in at.button if b.label == "Mostrar respuesta").click().run()
    next(b for b in at.button if b.label == "Bien").click().run()
    assert not at.exception, at.exception
    row = db.connect(tmp_path / "t.db").execute("SELECT * FROM card").fetchone()
    assert row["reps"] == 1 and row["user_sentence"] == "Scientists conduct research."
    assert any("No quedan tarjetas" in s.value for s in at.success)


def test_vocab_add_seed_cards_fills_lazily(monkeypatch, tmp_path):
    words = ["curriculum", "tuition fees", "compulsory education", "literacy", "academic attainment",
             "vocational training", "peer pressure", "distance learning"]
    p = FakeProvider(json.dumps({"cards": [card_json(w) for w in words[:6]]}),
                     json.dumps({"cards": [card_json(w) for w in words[6:]]}))
    at = run_page(monkeypatch, tmp_path, "pages/3_Vocabulario.py", p).run()
    assert not at.exception and not p.calls                      # sin tarjetas ni pendientes: no llama al LLM
    next(b for b in at.button if b.label.startswith("Tema de la semana")).click().run()
    assert not at.exception, at.exception
    stt = srs.stats(db.connect(tmp_path / "t.db"))
    assert len(p.calls) == 2 and stt["total"] == 8 and stt["pending"] == 2   # 8 listas (tope diario); 2 quedan en cola
