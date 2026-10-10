import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ielts import audit, db, export, progress
from ielts.curriculum import load_curriculum
from ielts.llm.schemas import WritingEvaluation
from ielts.modules import writing as w

from .test_llm import EVAL

APP = str(Path(__file__).resolve().parent.parent / "app.py")
D = date(2026, 11, 22)


def writing_eval(ta, cc, lr, gra) -> WritingEvaluation:
    ev = json.loads(json.dumps(EVAL))
    for k, v in zip(("ta_tr", "cc", "lr", "gra"), (ta, cc, lr, gra)):
        ev[k]["banda"] = v
    return WritingEvaluation.model_validate(ev)


def add_writing(conn, week, bands, text="It is clear that Is important.", day=None):
    ev = writing_eval(*bands)
    sid = w.save_submission(conn, week, "t2", "opinion", "Prompt?", text, ev)
    if day:
        conn.execute("UPDATE writing_submission SET date=? WHERE id=?", (day.isoformat() + "T10:00:00", sid))
        conn.commit()
    return sid


def add_speaking(conn, bands, day=None):
    ev = {"fc": {"banda": bands[0], "justificacion_es": "x"}, "lr": {"banda": bands[1], "justificacion_es": "x"},
          "gra": {"banda": bands[2], "justificacion_es": "x"}, "errores": [], "pronunciacion_es": "p",
          "consejos_es": [], "respuesta_mejorada_en": "b"}
    conn.execute("INSERT INTO speaking_session(date, week, part, prompt, transcript, metrics, evaluation) VALUES (?,?,?,?,?,?,?)",
                 ((day or D).isoformat() + "T10:00:00", 6, "p2", "Describe", "hello", "{}", json.dumps(ev)))
    conn.commit()


def add_full(conn, skill, raw, day=None):
    from ielts.ingest.schema import TestData
    from ielts.modules import receptive as rc
    td = TestData(book="b", book_title="B", test=1)
    res = [rc.QResult(q, "x", q <= raw, "y") for q in range(1, 41)]
    aid = rc.record_attempt(conn, week=6, skill=skill, td=td, unit="all", results=res, aggregate=True)
    if day:
        conn.execute("UPDATE receptive_attempt SET date=? WHERE id=?", (day.isoformat() + "T10:00:00", aid))
        conn.commit()


def test_checkpoint_needs_all_four_skills():
    conn = db.connect(":memory:")
    assert progress.checkpoint(conn) is None
    assert set(progress.missing_for_checkpoint(conn)) == {"listening", "reading", "writing", "speaking"}
    add_writing(conn, 6, (6, 6, 6, 6))
    add_speaking(conn, (6, 6, 6))
    add_full(conn, "reading", 27)
    assert progress.missing_for_checkpoint(conn) == ["listening"]


@pytest.mark.parametrize("lis,rea,wr,sp,overall,advice", [
    (30, 30, (7, 7, 7, 7), (7, 7, 7), 7.0, "keep"),
    (23, 23, (6, 6, 6, 6), (6, 6, 6), 6.0, "keep"),           # justo 6.0 → mantener
    (18, 19, (5.5, 5.5, 5.5, 5.5), (5.5, 5.5, 5.5), 5.5, "consult"),
    (13, 15, (5, 5, 5, 5), (5, 5, 5), 5.0, "reschedule"),
])
def test_checkpoint_rules(lis, rea, wr, sp, overall, advice):
    conn = db.connect(":memory:")
    add_full(conn, "listening", lis)
    add_full(conn, "reading", rea)
    add_writing(conn, 6, wr)
    add_speaking(conn, sp)
    cp = progress.checkpoint(conn)
    assert cp["advice"] == advice and cp["overall"] == overall
    assert cp["text"]


def test_checkpoint_uses_latest_two_writing_evaluations_and_full_tests_only():
    conn = db.connect(":memory:")
    add_writing(conn, 5, (4, 4, 4, 4))
    add_writing(conn, 6, (6, 6, 6, 6))
    add_writing(conn, 6, (6.5, 6.5, 6.5, 6.5))
    assert progress.latest_bands(conn)["writing"] == 6.5             # media de las 2 últimas (6.25 → 6.5)
    from ielts.ingest.schema import TestData
    from ielts.modules import receptive as rc
    rc.record_attempt(conn, week=1, skill="reading", td=TestData(book="b", book_title="B", test=1), unit="p1",
                      results=[rc.QResult(1, "a", True, "a")])     # sección suelta: sin banda
    assert progress.latest_bands(conn)["reading"] is None


def test_streak_counts_consecutive_days_ending_today_or_yesterday():
    conn = db.connect(":memory:")
    for i in (0, 1, 2, 4):                                          # hueco el día 3
        conn.execute("INSERT INTO block_log(week, weekday, block_id, seconds, done_at) VALUES (1,'monday',?,1,?)",
                     (f"b{i}", (D - timedelta(days=i)).isoformat() + "T09:00:00"))
    conn.commit()
    assert progress.streak(conn, D) == 3
    assert progress.streak(conn, D + timedelta(days=1)) == 3        # hoy sin actividad: cuenta desde ayer
    assert progress.streak(conn, D + timedelta(days=2)) == 0


def test_week_summary_filters_by_week_dates():
    conn = db.connect(":memory:")
    cur = load_curriculum()
    start, end = progress.week_range(6, cur)
    assert (start, end) == (date(2026, 11, 16), date(2026, 11, 22))
    add_writing(conn, 6, (6, 6, 6, 6), day=start)
    add_writing(conn, 5, (4, 4, 4, 4), day=start - timedelta(days=1))   # semana anterior
    add_speaking(conn, (5.5, 5.5, 5.5), day=end)
    db.log_error(conn, "writing", "x", "y", "articles")
    conn.execute("DELETE FROM error_event")                                              # ignora los errores de add_writing
    db.log_error(conn, "writing", "x2", "y2", "articles")
    db.log_error(conn, "writing", "old", "older", "verb_tense")
    conn.execute("UPDATE error_event SET date=? WHERE category='articles'", (start.isoformat(),))       # semana 6
    conn.execute("UPDATE error_event SET date=? WHERE category='verb_tense'", ((start - timedelta(days=3)).isoformat(),))
    s = progress.week_summary(conn, 6, cur)
    assert s["writing_bands"] == [6.0] and s["speaking_bands"] == [5.5]
    assert s["writing_avg"] == 6.0 and s["top_errors"] == [("articles", 1)]


# ---------------------------------------------------------------- auditoría
def test_audit_save_update_and_goal_carry_over():
    conn = db.connect(":memory:")
    audit.save_audit(conn, 6, measured={"a": 1}, where_lost="articles", why="prisa", change_goal="Revisar sujetos",
                     energy=4, anxiety=2, today=D)
    audit.save_audit(conn, 6, measured={}, where_lost="", why="", change_goal="Revisar sujetos y artículos",
                     energy=4, anxiety=2, today=D)
    assert len(audit.audits(conn)) == 1
    assert audit.current_goal(conn, 7) == "Revisar sujetos y artículos" and audit.current_goal(conn, 6) is None
    with pytest.raises(ValueError):
        audit.save_audit(conn, 7, measured={}, where_lost="", why="", change_goal="x", energy=0, anxiety=3)


def test_low_energy_two_consecutive_weeks_suggests_reducing_load():
    conn = db.connect(":memory:")
    save = lambda wk, e, a: audit.save_audit(conn, wk, measured={}, where_lost="", why="", change_goal="g",  # noqa: E731
                                             energy=e, anxiety=a)
    save(3, 2, 3)
    assert audit.load_warning(conn) is None                         # una sola semana baja
    save(4, 4, 4)                                                   # ansiedad alta (≥4) también cuenta
    assert audit.load_warning(conn) is not None
    save(5, 5, 1)
    assert audit.load_warning(conn) is None                         # última semana buena
    save(7, 1, 5)
    assert audit.load_warning(conn) is None                         # no son semanas consecutivas (5 y 7)


def test_doubts_dedupe_and_suggestions_skip_receptive_errors():
    conn = db.connect(":memory:")
    for _ in range(3):
        db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission")
    db.log_error(conn, "reading", "FALSE", "NOT GIVEN", "other")
    db.log_error(conn, "reading", "FALSE", "NOT GIVEN", "other")
    sug = audit.suggest_doubts(conn)
    assert len(sug) == 1 and "Is clear" in sug[0] and "3 veces" in sug[0]
    assert audit.add_doubt(conn, 6, sug[0], "error_log") and not audit.add_doubt(conn, 6, "  " + sug[0])
    assert not audit.add_doubt(conn, 6, "   ")
    assert len(audit.list_doubts(conn, 6)) == 1 and audit.list_doubts(conn, 7) == []


# ---------------------------------------------------------------- export
def test_annotate_markdown_and_html_handle_overlaps_and_missing_fragments():
    ev = writing_eval(6, 6, 6, 6)
    errs = [type("E", (), {"fragmento": f, "correccion": c})() for f, c in
            [("Is important", "It is important"), ("Is", "X"), ("not in text", "y")]]
    text = "Is important that people learn.\n\nSecond paragraph."
    md = export.annotate_markdown(text, errs)
    assert md.startswith("~~Is important~~ **It is important** that people") and "not in text" not in md
    assert md.count("~~") == 2                                       # «Is» solapado no se marca dos veces
    h = export.annotate_html("a < b & Is", errs)
    assert "&lt;" in h and "&amp;" in h and "<del" in h
    assert ev is not None


def sub_row(conn):
    add_writing(conn, 6, (6, 6, 5.5, 5.5), text="Is important that people learn.\n\nSecond paragraph, with a mistke.")
    return conn.execute("SELECT * FROM writing_submission").fetchone()


def test_teacher_exports_markdown_and_real_pdf():
    conn = db.connect(":memory:")
    sub = sub_row(conn)
    md = export.teacher_essay_markdown(sub)
    assert "banda estimada (aproximada)" in md and "~~Is important~~ **It is important**" in md
    pdf = export.html_to_pdf(export.teacher_essay_html(sub))
    assert pdf[:5] == b"%PDF-"
    import pymupdf
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    text = " ".join(p.get_text() for p in doc)
    assert doc.page_count >= 1 and "Ensayo con errores marcados" in text and "It is important" in text


def test_doubts_export_includes_speaking_transcript():
    conn = db.connect(":memory:")
    add_speaking(conn, (5.5, 5, 5))
    s = conn.execute("SELECT * FROM speaking_session").fetchone()
    md = export.doubts_markdown(6, ["¿Cuándo uso the?"], s)
    assert "1. ¿Cuándo uso the?" in md and "hello" in md and "banda estimada (aproximada)" in md
    assert export.html_to_pdf(export.doubts_html(6, [], s))[:5] == b"%PDF-"
    assert "sin dudas" in export.doubts_markdown(6, [], None)


# ---------------------------------------------------------------- calendario especial
def test_week_overrides_for_checkpoint_and_light_week():
    cur = load_curriculum()
    assert [b.id for b in cur.blocks_for("sunday", 2, 6)][:2] == ["checkpoint", "audit"]
    assert [b.id for b in cur.blocks_for("sunday", 2, 5)][0] == "audit"          # otras semanas: auditoría normal
    assert [b.id for b in cur.blocks_for("monday", 3, 11)] == ["sim_writing", "srs"]
    assert [b.id for b in cur.blocks_for("tuesday", 3, 11)] == ["sim_full", "srs"]
    assert [b.id for b in cur.blocks_for("monday", 3, 9)][0] == "sim_writing"    # fase 3 normal


# ---------------------------------------------------------------- pantallas
def page(monkeypatch, tmp_path, target, today="2026-11-22"):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("IELTS_TODAY", today)
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page(target)
    return at


def test_progress_page_empty_and_filled(monkeypatch, tmp_path):
    at = page(monkeypatch, tmp_path, "pages/5_Progreso.py").run()
    assert not at.exception, at.exception
    assert any("Aún no hay bandas" in i.value for i in at.info)
    conn = db.connect(tmp_path / "t.db")
    add_writing(conn, 6, (6, 6, 6, 6))
    add_speaking(conn, (6, 6, 6))
    add_full(conn, "listening", 23)
    add_full(conn, "reading", 23)
    at = page(monkeypatch, tmp_path, "pages/5_Progreso.py").run()
    assert not at.exception, at.exception
    assert any(m.label == "Overall (aprox.)" and m.value == "6.0" for m in at.metric)
    assert any("Punto de control" in s.value for s in at.success)


def test_home_shows_streak_goal_and_checkpoint(monkeypatch, tmp_path):
    conn = db.connect(tmp_path / "t.db")
    audit.save_audit(conn, 5, measured={}, where_lost="", why="", change_goal="Revisar sujetos", energy=3, anxiety=2)
    for sk, raw in (("listening", 23), ("reading", 23)):
        add_full(conn, sk, raw)
    add_writing(conn, 6, (6, 6, 6, 6))
    add_speaking(conn, (6, 6, 6))
    at = AppTest.from_file(APP, default_timeout=60)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("IELTS_TODAY", "2026-11-22")
    at.run()
    assert not at.exception, at.exception
    assert any("Racha" == m.label for m in at.metric)
    assert any("Revisar sujetos" in i.value for i in at.info)
    assert any("Punto de control" in s.value for s in at.success)


def test_audit_block_requires_saving_and_warns_on_low_load(monkeypatch, tmp_path):
    conn = db.connect(tmp_path / "t.db")
    audit.save_audit(conn, 4, measured={}, where_lost="", why="", change_goal="g", energy=1, anxiety=5)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["session"] = {"weekday": "sunday", "week": 5, "phase": 2, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    assert not at.exception, at.exception
    assert next(b for b in at.button if b.label.startswith("Siguiente")).disabled
    at.text_input(key="audit_5_goal").input("Releer cada oración buscando el sujeto")
    at.slider(key="audit_5_e").set_value(2)
    at.slider(key="audit_5_a").set_value(4)
    next(b for b in at.button if b.label == "Guardar auditoría").click().run()
    assert not at.exception, at.exception
    assert not next(b for b in at.button if b.label.startswith("Siguiente")).disabled
    assert any("reducir la carga" in w.value for w in at.warning)
    assert audit.current_goal(db.connect(tmp_path / "t.db"), 6) == "Releer cada oración buscando el sujeto"


def test_checkpoint_sunday_week6_shows_simulacro_then_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("IELTS_TODAY", "2026-11-22")
    at = AppTest.from_file(APP, default_timeout=60).run()
    sunday = next(b for b in at.button if b.key == "day_sunday")
    assert sunday.proto.type == "primary"
    at.session_state["session"] = {"weekday": "sunday", "week": 6, "phase": 2, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    assert not at.exception, at.exception
    assert any("punto de control" in m.value.lower() or "Simulacro completo" in m.value for m in at.subheader)
    assert len(at.tabs) == 3


def test_teacher_prep_and_doubts_blocks_render(monkeypatch, tmp_path):
    conn = db.connect(tmp_path / "t.db")
    sub = sub_row(conn)
    for _ in range(2):
        db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission")
    add_speaking(conn, (5.5, 5, 5))
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    for weekday, nexts in (("tuesday", 1), ("thursday", 1)):
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["session"] = {"weekday": weekday, "week": 6, "phase": 2, "diagnostic": False}
        at.switch_page("pages/1_Sesion.py").run()
        for _ in range(nexts):
            next(b for b in at.button if b.label.startswith("Siguiente")).click().run()
        assert not at.exception, (weekday, at.exception)
    # jueves: marcar una sugerencia crea la duda
    at.checkbox(key="dsug_6_0").check().run()
    assert len(audit.list_doubts(db.connect(tmp_path / "t.db"), 6)) == 1 and sub is not None


def test_top_categories_counts_events_not_cumulative_totals():
    conn = db.connect(":memory:")
    for _ in range(5):                                                   # 5 veces en semanas anteriores
        db.log_error(conn, "writing", "the people", "people", "articles")
    conn.execute("UPDATE error_event SET date='2026-11-01'")
    db.log_error(conn, "writing", "the people", "people", "articles")    # 1 vez esta semana (mismo error → count=6)
    db.log_error(conn, "writing", "Is clear", "It is clear", "subject_omission")
    db.log_error(conn, "reading", "FALSE", "NOT GIVEN", "other")          # causa de Reading: no es categoría lingüística
    conn.execute("UPDATE error_event SET date='2026-11-20' WHERE id > 5")
    assert conn.execute("SELECT count FROM error_log WHERE category='articles'").fetchone()["count"] == 6
    assert db.top_categories(conn, since="2026-11-16") == [("articles", 1), ("subject_omission", 1)]
    assert db.top_categories(conn) == [("articles", 6), ("subject_omission", 1)]
