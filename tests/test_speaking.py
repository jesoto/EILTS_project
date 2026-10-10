import json
import random
from pathlib import Path
from types import SimpleNamespace as NS

from streamlit.testing.v1 import AppTest

from ielts import db
from ielts.config import load_stt_config
from ielts.curriculum import load_curriculum
from ielts.modules import speaking as sp
from ielts.speaking_metrics import compare_transcripts, compute_metrics, tokenize
from ielts.stt import FasterWhisperTranscriber, Word

from .fakes import FakeProvider

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def words(spec):
    """spec: lista de (texto, inicio, fin[, prob])."""
    return [Word(*s) for s in spec]


def test_wpm_and_pauses():
    seg = words([("I", 0, 0.3), ("think", 0.4, 0.8), ("um", 3.0, 3.3), ("it", 3.4, 3.6), ("is", 3.7, 3.9),
                 ("good", 4.0, 60.0)])
    m = compute_metrics([seg])
    assert m.words == 6 and m.speaking_seconds == 60
    assert m.wpm == 6.0
    assert [(p.after, p.seconds) for p in m.pauses] == [("think", 2.2)]   # 0.8 → 3.0; el hueco 4.0.. no existe


def test_pause_threshold_is_strict_and_not_across_recordings():
    a = words([("one", 0, 1), ("two", 2.5, 3)])         # hueco exacto 1.5 → no cuenta
    b = words([("three", 100, 101)])                     # otra grabación: sin pausa entre a y b
    m = compute_metrics([a, b])
    assert m.pauses == []


def test_fillers_repetition_diversity():
    text = "um I think like technology is like very important you know technology helps technology and technology um"
    seg = [Word(t, i * 0.4, i * 0.4 + 0.3) for i, t in enumerate(text.split())]
    m = compute_metrics([seg])
    assert m.fillers["um"] == 2 and m.fillers["like"] == 2 and m.fillers["you know"] == 1
    assert m.filler_total == 5
    assert m.repeated == [("technology", 4)]
    assert 0 < m.ttr < 1 and m.mattr == m.ttr        # <50 palabras: MATTR = TTR


def test_low_confidence_and_empty():
    m = compute_metrics([words([("hello", 0, 1, 0.3), ("world", 1, 2, 0.9)])])
    assert m.low_confidence == ["hello"]
    assert compute_metrics([]).words == 0
    assert tokenize("It’s GOOD, right?") == ["it's", "good", "right"]


def test_compare_transcripts_for_shadowing():
    r = compare_transcripts("the number of students is rising", "number of student is rising")
    assert r["similarity"] < 1
    assert "the" in r["missing"] and "the" in r["weak_forms_missing"]
    assert compare_transcripts("same words", "Same words.")["similarity"] == 1.0


class FakeModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, src, **kw):
        self.kwargs = kw
        seg = NS(text=" Hello there ", words=[NS(word=" Hello", start=0.0, end=0.5, probability=0.9),
                                              NS(word=" there", start=0.6, end=1.0, probability=0.2)])
        return iter([seg]), NS(duration=12.5)


def test_transcriber_wrapper_converts_and_passes_options():
    model = FakeModel()
    t = FasterWhisperTranscriber(model=model).transcribe(b"RIFFxxxx", start=5, end=25)
    assert t.text == "Hello there" and t.duration == 12.5
    assert [w.text for w in t.words] == ["Hello", "there"] and t.words[1].prob == 0.2
    assert model.kwargs["word_timestamps"] is True and model.kwargs["clip_timestamps"] == "5,25"
    assert model.kwargs["language"] == "en" and "um" in model.kwargs["initial_prompt"].lower()


def test_stt_config_defaults():
    cfg = load_stt_config()
    assert cfg.device == "cpu" and cfg.model


def test_content_covers_all_vocab_themes():
    cur = load_curriculum()
    themes = sp.load_content()
    for w in cur.weeks:
        if not w.vocab.startswith("Repaso"):
            assert w.vocab in themes, w.vocab
    for name, c in themes.items():
        assert len(c["cards"]) >= 1 and len(c["part1"]) >= 3 and len(c["part3"]) >= 2, name
        for card in c["cards"]:
            assert card["points"][-1].startswith("and explain")


def test_review_weeks_pick_a_random_theme_and_questions():
    rng = random.Random(1)
    name, card = sp.part2_card("Repaso global", rng)
    assert name in sp.load_content() and "You should say" in sp.card_text(card)
    qs = sp.part13_questions("Salud", rng)
    assert [p for p, _ in qs] == ["Part 1"] * 3 + ["Part 3"] * 2


EVAL = {"fc": {"banda": 5.5, "justificacion_es": "ok"}, "lr": {"banda": 5.0, "justificacion_es": "ok"},
        "gra": {"banda": 5.0, "justificacion_es": "ok"},
        "errores": [{"fragmento": "I am agree", "correccion": "I agree", "categoria": "cohesion", "explicacion_es": "x"}],
        "pronunciacion_es": "posible", "consejos_es": ["a", "b"], "respuesta_mejorada_en": "better"}


def test_evaluate_and_save_session():
    conn = db.connect(":memory:")
    m = compute_metrics([words([("I", 0, 0.2), ("am", 0.3, 0.5), ("agree", 0.6, 1.0, 0.3)])])
    p = FakeProvider(json.dumps(EVAL))
    ev = sp.evaluate_speaking(p, "p2", "Describe a teacher", "I am agree", m)
    sys_prompt = p.calls[0]["system"]
    assert "Whisper" in sys_prompt and "wpm=" in sys_prompt and "agree" in sys_prompt   # métricas + low-confidence
    assert "Do NOT give a pronunciation band" in sys_prompt and p.calls[0]["temperature"] <= 0.3
    assert sp.overall_speaking(ev) == 5.0    # (5.5+5+5)/3 = 5.17 → 5.0
    sid = sp.save_session(conn, 1, "p2", "Describe a teacher", "I am agree", m, ev)
    assert conn.execute("SELECT part FROM speaking_session WHERE id=?", (sid,)).fetchone()["part"] == "p2"
    assert conn.execute("SELECT category FROM error_log WHERE module='speaking'").fetchone()["category"] == "cohesion"
    assert conn.execute("SELECT COUNT(*) c FROM attempt WHERE skill='speaking'").fetchone()["c"] == 1


def test_session_without_llm_still_saved():
    conn = db.connect(":memory:")
    m = compute_metrics([words([("hi", 0, 1)])])
    sp.save_session(conn, 1, "p13", "q", "hi", m, None)
    assert conn.execute("SELECT evaluation FROM speaking_session").fetchone()["evaluation"] is None


def test_speaking_pages_render(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    from ielts import audit
    audit.save_audit(db.connect(tmp_path / "t.db"), 1, measured={}, where_lost="", why="", change_goal="x",
                     energy=3, anxiety=2)      # el domingo la auditoría debe estar guardada para avanzar
    for weekday, skip, expect in [("thursday", 0, "Part 2"), ("sunday", 1, "Part 1")]:   # domingo: 1.º auditoría
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["session"] = {"weekday": weekday, "week": 1, "phase": 1, "diagnostic": False}
        at.switch_page("pages/1_Sesion.py").run()
        for _ in range(skip):
            next(b for b in at.button if b.label.startswith("Siguiente")).click().run()
        assert not at.exception, (weekday, at.exception)
        assert any(expect in m.value for m in at.markdown)
    at = AppTest.from_file(APP, default_timeout=60)   # miércoles: bloque 3 = shadowing
    at.session_state["session"] = {"weekday": "wednesday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    for _ in range(2):
        next(b for b in at.button if b.label.startswith("Siguiente")).click().run()
    assert not at.exception, at.exception
