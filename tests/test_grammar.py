import json

from ielts import db
from ielts.llm.schemas import ExerciseItem
from ielts.modules import grammar as g
from ielts.text import normalize_answer

from .fakes import FakeProvider


def ex_json(prompt="____ is important that we act.", answer="It"):
    return json.dumps({"kind": "gap_fill", "instruction": "Fill the gap.",
                       "items": [{"prompt": prompt, "answer": answer, "accepted": ["it"]}]})


def test_normalize_answer():
    assert normalize_answer("  The   Government. ") == "the government"
    assert normalize_answer("It’s") == "it's"
    assert normalize_answer("rise") != normalize_answer("rize")  # la ortografía cuenta


def test_closed_grading():
    item = ExerciseItem(prompt="p", answer="It is clear that", accepted=["It's clear that"])
    assert g.is_correct(item, "  it is CLEAR that.  ")
    assert g.is_correct(item, "It’s clear that")
    assert not g.is_correct(item, "Is clear that")
    assert not g.is_correct(item, "")


def test_kind_rotation_never_repeats():
    k = None
    seen = []
    for _ in range(11):
        nk = g.next_kind(k)
        assert nk != k
        seen.append(nk)
        k = nk
    assert set(seen) == set(g.KIND_ROTATION)


def test_resolve_topics_uses_error_log():
    conn = db.connect(":memory:")
    assert g.resolve_topics(["articles"], conn) == ["articles"]
    # sin historial → temas de respaldo
    assert g.resolve_topics(["error_log"], conn) == g.FALLBACK_TOPICS
    for _ in range(3):
        db.log_error(conn, "writing", "the people", "people", "articles")
    db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission")
    topics = g.resolve_topics(["error_log"], conn)
    assert topics[:2] == ["articles", "subject_agreement"] and len(topics) == 3


def test_generate_avoids_repeats():
    conn = db.connect(":memory:")
    p = FakeProvider(ex_json(), ex_json(), ex_json("____ exist many reasons.", "There"))
    first = g.generate_exercise(p, conn, "subject_agreement", "gap_fill", level=3, phase=1)
    assert first.items[0].answer == "It" and len(p.calls) == 1
    second = g.generate_exercise(p, conn, "subject_agreement", "gap_fill", level=3, phase=1)
    assert second.items[0].answer == "There"      # el duplicado se descartó
    assert len(p.calls) == 3
    assert p.calls[0]["temperature"] >= 0.7        # generación: temperatura alta


def test_evaluation_temperature_low():
    p = FakeProvider(json.dumps({"errores": [], "comentario_es": "bien", "version_corregida": "x",
                                 "topic_used_correctly": True}))
    fb = g.evaluate_production(p, "articles", "write", "People need education.")
    assert fb.topic_used_correctly and p.calls[0]["temperature"] <= 0.3


def test_error_log_counts_and_top():
    conn = db.connect(":memory:")
    for _ in range(3):
        db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission", "x")
    db.log_error(conn, "grammar", "a", "b", "articles")
    row = conn.execute("SELECT count FROM error_log WHERE category='subject_omission'").fetchone()
    assert row["count"] == 3
    assert db.top_categories(conn) == [("subject_omission", 3), ("articles", 1)]


def test_difficulty_window():
    conn = db.connect(":memory:")
    for _ in range(4):
        db.record_attempt(conn, "grammar", 0.9)
    assert db.get_level(conn, "grammar") == db.DEFAULT_LEVEL          # aún no hay 5 sesiones
    db.record_attempt(conn, "grammar", 0.9)
    assert db.get_level(conn, "grammar") == db.DEFAULT_LEVEL + 1      # >80 % → +1
    db.record_attempt(conn, "grammar", 0.1)                            # ventana reiniciada
    assert db.get_level(conn, "grammar") == db.DEFAULT_LEVEL + 1
    for _ in range(4):
        db.record_attempt(conn, "grammar", 0.2)
    assert db.get_level(conn, "grammar") == db.DEFAULT_LEVEL           # <50 % → −1
    for _ in range(5):
        db.record_attempt(conn, "grammar", 0.6)
    assert db.get_level(conn, "grammar") == db.DEFAULT_LEVEL           # 50-80 % → igual
