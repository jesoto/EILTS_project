import json

from ielts import db
from ielts.checklist import run_checklist
from ielts.modules import writing as w
from ielts.modules.charts import CHART_TYPES, make_chart
from ielts.text import word_count

from .fakes import FakeProvider
from .test_llm import EVAL


def by_id(items):
    return {i.id: i for i in items}


def test_word_count():
    assert word_count("It's a state-of-the-art plan, isn't it? 25%") == 7
    assert word_count("") == 0


def test_checklist_catches_spanish_interference():
    text = ("Is important that students learn.\n\nActually, people is happy. They are but he don't know. "
            "Exist many reasons so we realize it so quickly but so what. About this about that about it.")
    c = by_id(run_checklist(text, "t2"))
    assert not c["explicit_subject"].ok
    assert not c["agreement"].ok
    assert not c["false_friends"].ok and "actually" in c["false_friends"].evidence
    assert not c["connector_variety"].ok
    assert not c["word_count"].ok
    assert not c["clear_position"].ok


def test_checklist_t1_overview_without_figures():
    good = ("The graph shows trends in internet use.\n\nOverall, usage rose in every country.\n\n"
            "In 2000, Canada stood at 40%.\n\nBrazil rose to 60% by 2020.")
    assert by_id(run_checklist(good, "t1"))["overview_no_figures"].ok
    assert by_id(run_checklist(good, "t1"))["paragraph_structure"].ok
    bad = good.replace("rose in every country", "rose from 40% to 80%")
    assert not by_id(run_checklist(bad, "t1"))["overview_no_figures"].ok


def test_checklist_t2_position_detected():
    text = "I strongly agree that education should be free.\n\nSecond.\n\nThird.\n\nIn conclusion, I agree."
    assert by_id(run_checklist(text, "t2"))["clear_position"].ok


def test_charts_all_types_render_png():
    for kind in CHART_TYPES:
        c = make_chart(kind, seed=1)
        assert c.png[:8] == b"\x89PNG\r\n\x1a\n" and c.data_text and "150 words" in c.prompt
    assert make_chart("line", seed=3).data_text == make_chart("line", seed=3).data_text


def test_pick_t2_prompt_avoids_used():
    conn = db.connect(":memory:")
    import random
    kind, first = w.pick_t2_prompt(["opinion"], conn, random.Random(0))
    assert kind == "opinion"
    ev = w.WritingEvaluation.model_validate(EVAL)
    w.save_submission(conn, 1, "t2", "opinion", first, "text", ev)
    for _ in range(20):
        assert w.pick_t2_prompt(["opinion"], conn)[1] != first


def test_evaluate_and_persist_logs_errors():
    conn = db.connect(":memory:")
    p = FakeProvider(json.dumps(EVAL))
    text = "Is important that people learn. " * 3
    ev, checks = w.evaluate_writing(p, "t2", "Prompt?", text)
    sys_prompt = p.calls[0]["system"]
    assert "Task Response" in sys_prompt and "explicit_subject" in sys_prompt and text.strip() in sys_prompt
    assert p.calls[0]["temperature"] <= 0.3
    assert w.overall_writing_band(ev) == 5.5   # (5.5+6+5.5+5)/4 = 5.5
    sid = w.save_submission(conn, 1, "t2", "opinion", "Prompt?", text, ev)
    assert w.latest_submission(conn, 1, "t2")["id"] == sid
    assert conn.execute("SELECT count FROM error_log WHERE category='subject_omission'").fetchone()["count"] == 1
    md = w.feedback_markdown("t2", "Prompt?", text, ev)
    assert "banda estimada (aproximada)" in md and "Is important" in md


def test_rewrite_evaluation_saved_and_wrong_ones_logged():
    conn = db.connect(":memory:")
    ev = w.WritingEvaluation.model_validate(EVAL)
    sid = w.save_submission(conn, 1, "t2", "opinion", "P", "T", ev)
    resp = {"resultados": [
        {"original": "a", "reescrita": "A.", "correcta": True, "mejor_version": "A."},
        {"original": "b", "reescrita": "Bad b", "correcta": False, "problema_restante_es": "falta sujeto", "mejor_version": "It b"},
        {"original": "c", "reescrita": "C.", "correcta": True, "mejor_version": "C."}]}
    p = FakeProvider(json.dumps(resp))
    res = w.evaluate_rewrites(p, [("a", "A."), ("b", "Bad b"), ("c", "C.")])
    w.save_rewrite(conn, sid, res)
    assert json.loads(conn.execute("SELECT rewrite FROM writing_submission").fetchone()["rewrite"])["resultados"][1]["correcta"] is False
    assert conn.execute("SELECT COUNT(*) c FROM error_log WHERE module='writing_rewrite'").fetchone()["c"] == 1


# ---------------------------------------------------------------- gráficos de los libros
def test_book_t1_tasks_filter_by_type_and_unused(tmp_path, monkeypatch):
    from ielts.ingest import schema
    from ielts.ingest.schema import TestData, WritingTask, save_test
    derived = tmp_path / "derived"
    monkeypatch.setattr(schema, "DERIVED_DIR", derived)
    (derived / "tb" / "images").mkdir(parents=True)
    (derived / "tb" / "images" / "a.png").write_bytes(b"\x89PNG-a")
    td = TestData(book="tb", book_title="Book", test=1, writing=[
        WritingTask(task=1, prompt="The map below...", task_type="map", image="tb/images/a.png"),
        WritingTask(task=1, prompt="The line graph...", task_type="line", image="tb/images/missing.png"),
        WritingTask(task=2, prompt="Essay?", task_type="opinion")])
    save_test(td, derived)
    conn = db.connect(":memory:")
    assert [t["task_type"] for t in w.book_t1_tasks(["map", "line"], conn)] == ["map"]    # la imagen que falta se omite
    assert w.book_t1_tasks(["bar"], conn) == []
    ev = w.WritingEvaluation.model_validate(EVAL)
    w.save_submission(conn, 6, "t1", "map", "The map below...", "text", ev)
    assert w.book_t1_tasks(["map"], conn) == []                                          # ya escrita: no se repite


def test_evaluator_is_told_it_cannot_see_book_charts():
    p = FakeProvider(json.dumps(EVAL))
    w.evaluate_writing(p, "t1", "The map below...", "Overall, the area changed. " * 10, data_text=w.NO_CHART_DATA)
    system = p.calls[0]["system"]
    assert "cannot see" in system and "accuracy could not be verified" in system and "__book_chart__" not in system


def test_t1_block_prefers_book_chart_and_can_switch_to_synthetic(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ielts.ingest import schema
    from ielts.ingest.schema import TestData, WritingTask, save_test
    derived = tmp_path / "derived"
    monkeypatch.setattr(schema, "DERIVED_DIR", derived)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    from ielts.modules.charts import make_chart
    (derived / "tb" / "images").mkdir(parents=True)
    (derived / "tb" / "images" / "a.png").write_bytes(make_chart("line", seed=1).png)
    save_test(TestData(book="tb", book_title="Book", test=1, writing=[
        WritingTask(task=1, prompt="The line graph below shows X.", task_type="line", image="tb/images/a.png")]), derived)
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)
    at.session_state["session"] = {"weekday": "friday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    assert not at.exception, at.exception
    assert any("The line graph below shows X." in i.value for i in at.info)
    assert any("Fuente: Book · Test 1" in c.value for c in at.caption)
    next(b for b in at.button if "gráfico generado" in b.label).click().run()
    assert not at.exception, at.exception
    assert any("Fuente: gráfico generado" in c.value for c in at.caption)
