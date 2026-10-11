from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ielts import clock
from ielts.calendar import Mode, day_info, week_number
from ielts.config import load_app_config
from ielts.curriculum import derive_plan_dates, load_curriculum


# ---------------------------------------------------------------- zona horaria
def test_now_uses_configured_timezone(monkeypatch):
    monkeypatch.setenv("IELTS_TZ", "America/Lima")
    lima = datetime.now(ZoneInfo("America/Lima")).replace(tzinfo=None)
    assert abs((clock.now() - lima).total_seconds()) < 5
    monkeypatch.setenv("IELTS_TZ", "Pacific/Auckland")
    assert clock.now() - lima > timedelta(hours=15)             # Auckland va ~18 h por delante de Lima


def test_evening_in_lima_is_still_today_even_though_utc_is_tomorrow(monkeypatch):
    monkeypatch.setenv("IELTS_TZ", "America/Lima")
    fake_utc = datetime(2026, 11, 3, 2, 30, tzinfo=ZoneInfo("UTC"))      # 21:30 del día 2 en Lima

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_utc.astimezone(tz) if tz else fake_utc.replace(tzinfo=None)
    monkeypatch.setattr(clock, "datetime", FakeDT)
    assert clock.today() == date(2026, 11, 2)
    assert clock.timestamp() == "2026-11-02T21:30:00"
    monkeypatch.setenv("IELTS_TZ", "UTC")
    assert clock.today() == date(2026, 11, 3)                             # el mismo instante, en UTC, ya es el día siguiente


def test_today_override_and_invalid_timezone(monkeypatch):
    monkeypatch.setenv("IELTS_TODAY", "2026-10-14")
    assert clock.today() == date(2026, 10, 14)
    monkeypatch.delenv("IELTS_TODAY")
    monkeypatch.setenv("IELTS_TZ", "Mars/Olympus")
    assert clock.tz() is None and isinstance(clock.now(), datetime)       # zona inválida: cae a la del sistema


# ---------------------------------------------------------------- fechas del plan
def test_default_dates_come_from_the_yaml():
    cur = load_curriculum()
    assert (cur.start_date, cur.exam_date) == (date(2026, 10, 12), date(2026, 12, 29))


def test_derive_plan_dates_reproduces_the_original_calendar():
    d = derive_plan_dates(date(2026, 12, 29))
    assert d["start_date"] == date(2026, 10, 12)
    assert d["checkpoint_date"] == date(2026, 11, 22) and d["rest_day"] == date(2026, 12, 28)


@pytest.mark.parametrize("exam", [date(2027, 3, 8), date(2027, 3, 11), date(2027, 3, 13), date(2027, 3, 14)])
def test_any_exam_weekday_gives_a_monday_start_11_weeks_before_the_exam_week(exam):
    d = derive_plan_dates(exam)
    assert d["start_date"].weekday() == 0
    assert (exam - d["start_date"]).days // 7 == 11 or exam.weekday() == 6
    assert d["checkpoint_date"].weekday() == 6 and d["checkpoint_date"] == d["start_date"] + timedelta(weeks=5, days=6)


def test_exam_date_override_rebuilds_calendar_and_phases(monkeypatch):
    monkeypatch.setenv("IELTS_EXAM_DATE", "2027-03-16")                    # martes; su lunes es el 15-mar
    cur = load_curriculum()
    start = date(2026, 12, 28)                                              # 15-mar menos 11 semanas
    assert cur.start_date == start and cur.exam_date == date(2027, 3, 16) and cur.free_days == []
    assert cur.checkpoint_date == date(2027, 2, 7) and cur.checkpoint_date.weekday() == 6
    assert [(p.start, p.end) for p in cur.phases] == [
        (date(2026, 12, 28), date(2027, 1, 24)), (date(2027, 1, 25), date(2027, 2, 21)),
        (date(2027, 2, 22), date(2027, 3, 14))]
    assert week_number(start, cur) == 1 and week_number(date(2027, 3, 14), cur) == 11
    assert day_info(date(2027, 3, 15), cur).mode is Mode.REST and day_info(date(2027, 3, 16), cur).mode is Mode.EXAM
    assert day_info(date(2026, 12, 27), cur).mode is Mode.DIAGNOSTIC


def test_free_days_from_config_and_default_not_polluted(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[plan]\nexam_date = "2027-03-16"\nfree_days = ["2027-02-01"]\n[app]\nmode = "cloud"\n', encoding="utf-8")
    app = load_app_config(cfg)
    assert app.exam_date == "2027-03-16" and app.free_days == ("2027-02-01",) and app.is_cloud
    assert load_app_config().exam_date == "" and not load_app_config().is_cloud    # config.toml del repo: sin override
