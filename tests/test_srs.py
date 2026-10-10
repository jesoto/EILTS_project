import json
from datetime import date, timedelta

import pytest

from ielts import db, srs
from ielts.modules import errorlog as el

from .fakes import FakeProvider

D0 = date(2026, 10, 12)


def card_json(word, extra=None):
    return {"word": word, "family": {"noun": "n", "verb": "v", "adjective": "", "adverb": ""},
            "collocations": ["a b", "c d"], "definition_es": "def", "example_en": "Example.",
            "false_friend_note_es": "", **(extra or {})}


def test_sm2_progression_and_ease():
    ease, iv, reps = srs.sm2(2.5, 0, 0, 4)
    assert (iv, reps) == (1, 1) and ease == 2.5
    ease, iv, reps = srs.sm2(ease, iv, reps, 4)
    assert (iv, reps) == (6, 2)
    ease, iv, reps = srs.sm2(ease, iv, reps, 5)
    assert iv == round(6 * 2.5) == 15 and reps == 3 and ease == pytest.approx(2.6)


def test_sm2_failure_resets_and_ease_floor():
    ease, iv, reps = srs.sm2(2.5, 15, 3, 1)
    assert (iv, reps, ease) == (1, 0, 2.5)
    e = 1.4
    for _ in range(5):
        e, _, _ = srs.sm2(e, 6, 2, 3)   # "difícil" repetido baja la ease
    assert e == srs.MIN_EASE
    with pytest.raises(ValueError):
        srs.sm2(2.5, 1, 1, 6)


def test_sm2_interval_always_grows():
    assert srs.sm2(1.3, 1, 2, 3)[1] >= 2


def test_lexical_errors_queue_cards_but_not_grammar_ones():
    conn = db.connect(":memory:")
    db.log_error(conn, "writing", "make a research", "conduct research", "collocation", "colocación")
    db.log_error(conn, "writing", "the people", "people", "articles")
    db.log_error(conn, "writing", "a very long sentence that is not a card at all", "a very long sentence that is "
                 "not a card at all fixed", "word_form")
    db.log_error(conn, "writing", "make a research", "conduct research", "collocation")  # duplicado
    words = [r["word"] for r in srs.pending_cards(conn)]
    assert words == ["conduct research"]
    assert "make a research" in srs.pending_cards(conn)[0]["context"]


def test_fill_pending_with_llm_and_review_cycle():
    conn = db.connect(":memory:")
    srs.add_pending(conn, ["Pose a Threat", "mitigate the effects"], "collocation", today=D0)
    p = FakeProvider(json.dumps({"cards": [card_json("pose a threat"), card_json("mitigate the effects")]}))
    assert srs.fill_pending(p, conn) == 2
    assert p.calls[0]["temperature"] <= 0.3
    assert srs.stats(conn, D0) == {"due": 2, "total": 2, "pending": 0}

    c = srs.due_cards(conn, D0)[0]
    assert json.loads(c["collocations"]) == ["a b", "c d"]
    after = srs.review_card(conn, c["id"], 4, D0, "This pose a threat.")
    assert after["interval"] == 1 and after["due"] == (D0 + timedelta(days=1)).isoformat()
    assert after["user_sentence"] == "This pose a threat."
    # ya no sale hoy; mañana sí
    assert c["id"] not in [x["id"] for x in srs.due_cards(conn, D0)]
    assert c["id"] in [x["id"] for x in srs.due_cards(conn, D0 + timedelta(days=1))]


def test_fill_pending_maps_by_position_when_word_changed():
    conn = db.connect(":memory:")
    srs.add_pending(conn, ["colour"], "manual", today=D0)
    p = FakeProvider(json.dumps({"cards": [card_json("color")]}))
    assert srs.fill_pending(p, conn) == 1


def test_new_cards_capped_per_day():
    conn = db.connect(":memory:")
    srs.add_pending(conn, [f"word{i}" for i in range(12)], "weekly", today=D0)
    conn.execute("UPDATE card SET status='ready'")
    conn.commit()
    assert len(srs.due_cards(conn, D0)) == srs.NEW_PER_DAY
    srs.review_card(conn, srs.due_cards(conn, D0)[0]["id"], 4, D0)
    assert len(srs.due_cards(conn, D0)) == srs.NEW_PER_DAY - 1   # 1 nueva ya vista hoy
    # al día siguiente: la repasada vuelve a vencer y entran 8 nuevas
    assert len(srs.due_cards(conn, D0 + timedelta(days=1))) == 1 + srs.NEW_PER_DAY


def test_seed_words_follow_week_and_phase():
    s1 = srs.seed_words_for("Educación", 1)
    assert "curriculum" in s1["weekly"] and "actually" in s1["false_friend"] and "analyse" in s1["awl"]
    assert "awl" not in srs.seed_words_for("Educación", 2)         # sublistas 6-10 aún sin cargar
    assert "conduct research" in srs.seed_words_for("Repaso colocaciones", 2)["collocation"]
    assert "weekly" not in srs.seed_words_for("Repaso global", 3)


def test_error_log_filters_and_export():
    conn = db.connect(":memory:")
    for _ in range(3):
        db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission", "falta sujeto")
    db.log_error(conn, "grammar", "the people|x", "people", "articles")
    assert len(el.query_errors(conn)) == 2
    assert el.query_errors(conn)[0]["count"] == 3                      # ordenado por veces
    assert len(el.query_errors(conn, modules=["grammar"])) == 1
    assert len(el.query_errors(conn, categories=["subject_omission"], min_count=2)) == 1
    assert len(el.query_errors(conn, text="sujeto")) == 1
    assert len(el.query_errors(conn, since="2999-01-01")) == 0
    rows = el.query_errors(conn)
    assert el.to_csv(rows).splitlines()[0] == "date,module,fragment,correction,category,explanation,count"
    assert r"\|" in el.to_markdown(rows)                                # el | se escapa
