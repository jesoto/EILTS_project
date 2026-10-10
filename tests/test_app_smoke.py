from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _home(monkeypatch, tmp_path, today: str) -> AppTest:
    monkeypatch.setenv("IELTS_TODAY", today)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "test.db"))
    at = AppTest.from_file(APP,default_timeout=30).run()
    assert not at.exception
    return at


def test_home_diagnostic_before_start(monkeypatch, tmp_path):
    at = _home(monkeypatch, tmp_path, "2026-10-10")
    assert any("diagnóstico" in i.value for i in at.info)
    assert len([b for b in at.button if b.key and b.key.startswith("day_")]) == 7


def test_home_highlights_today(monkeypatch, tmp_path):
    at = _home(monkeypatch, tmp_path, "2026-10-14")  # miércoles, semana 1
    primary = [b.key for b in at.button if b.proto.type == "primary"]
    assert primary == ["day_wednesday"]


def test_home_rest_day(monkeypatch, tmp_path):
    at = _home(monkeypatch, tmp_path, "2026-12-28")
    assert at.checkbox


def test_session_flow_runs_to_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "test.db"))
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["session"] = {"weekday": "thursday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py")
    at.run()
    assert not at.exception
    n = 3  # speaking_p2, doubts, srs
    for _ in range(n):
        next(b for b in at.button if b.label.startswith(("Siguiente", "Terminar"))).click().run()
        assert not at.exception
    assert any("completada" in s.value for s in at.success)
