from datetime import date

import pytest

from ielts.calendar import Mode, day_info, days_to_exam, effective_week, week_number
from ielts.curriculum import WEEKDAYS, load_curriculum


@pytest.mark.parametrize("d,week", [
    (date(2026, 10, 11), 0),
    (date(2026, 10, 12), 1),
    (date(2026, 10, 18), 1),
    (date(2026, 10, 19), 2),
    (date(2026, 11, 8), 4),
    (date(2026, 11, 9), 5),
    (date(2026, 11, 22), 6),
    (date(2026, 12, 6), 8),
    (date(2026, 12, 7), 9),
    (date(2026, 12, 27), 11),
])
def test_week_number(d, week):
    assert week_number(d) == week


@pytest.mark.parametrize("d,phase", [
    (date(2026, 10, 12), 1), (date(2026, 11, 8), 1),
    (date(2026, 11, 9), 2), (date(2026, 12, 6), 2),
    (date(2026, 12, 7), 3), (date(2026, 12, 27), 3),
])
def test_phase(d, phase):
    assert day_info(d).phase == phase


def test_phase_dates_match_weeks():
    cur = load_curriculum()
    for p in cur.phases:
        assert week_number(p.start) == p.weeks[0]
        assert week_number(p.end) == p.weeks[1]


def test_modes():
    assert day_info(date(2026, 10, 10)).mode is Mode.DIAGNOSTIC
    assert day_info(date(2026, 10, 12)).mode is Mode.TRAINING
    assert day_info(date(2026, 12, 24)).mode is Mode.FREE
    assert day_info(date(2026, 12, 25)).mode is Mode.FREE
    assert day_info(date(2026, 12, 28)).mode is Mode.REST
    assert day_info(date(2026, 12, 29)).mode is Mode.EXAM


def test_weekday_and_checkpoint():
    cur = load_curriculum()
    assert day_info(cur.start_date).weekday == "monday"
    assert day_info(cur.checkpoint_date).weekday == "sunday"
    assert day_info(cur.exam_date).weekday == "tuesday"


def test_days_to_exam_and_effective_week():
    assert days_to_exam(date(2026, 10, 10)) == 80
    assert effective_week(date(2026, 10, 10)) == 1
    assert effective_week(date(2026, 12, 28)) == 11


def test_curriculum_consistency():
    cur = load_curriculum()
    assert [w.n for w in cur.weeks] == list(range(1, 12))
    assert set(cur.days) == set(WEEKDAYS)
    assert cur.week(8).listening_speed == 1.25
    assert cur.week(1).listening_speed == 1.0


def test_blocks_include_srs_and_phase_variants():
    cur = load_curriculum()
    assert cur.blocks_for("monday", 1)[-1].id == "srs"
    assert [b.id for b in cur.blocks_for("saturday", 1)][0] == "listening_sections"
    assert [b.id for b in cur.blocks_for("saturday", 2)][0] == "listening_full"
    assert [b.id for b in cur.blocks_for("saturday", 3)][0] == "sim_full"
    assert [b.id for b in cur.blocks_for("monday", 3)][0] == "sim_writing"
    # lunes de fase 1 y 2 usan el plan base
    assert [b.id for b in cur.blocks_for("monday", 2)][0] == "writing_t2"
