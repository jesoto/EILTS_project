import pytest

from ielts.scoring import checkpoint_advice, listening_band, overall_band, reading_band, round_band


@pytest.mark.parametrize("raw,band", [
    (30, 7.0), (32, 7.0), (27, 6.5), (29, 6.5), (23, 6.0), (26, 6.0),
    (33, 7.5), (34, 7.5), (35, 8.0), (36, 8.0), (22, 5.5), (40, 9.0),
])
def test_reading_band(raw, band):
    assert reading_band(raw) == band


@pytest.mark.parametrize("raw,band", [
    (30, 7.0), (31, 7.0), (26, 6.5), (29, 6.5), (23, 6.0), (25, 6.0),
    (32, 7.5), (34, 7.5), (35, 8.0), (36, 8.0), (22, 5.5), (0, 2.0),
])
def test_listening_band(raw, band):
    assert listening_band(raw) == band


def test_raw_out_of_range():
    with pytest.raises(ValueError):
        reading_band(41)
    with pytest.raises(ValueError):
        listening_band(-1)


@pytest.mark.parametrize("values,expected", [
    ([6.5, 6.5, 6.0, 6.0], 6.5),   # 6.25 → 6.5
    ([6.5, 7.0, 7.0, 6.5], 7.0),   # 6.75 → 7.0
    ([6.0, 6.0, 6.0, 6.5], 6.0),   # 6.125 → 6.0
    ([6.5, 6.5, 6.5, 6.0], 6.5),   # 6.375 → 6.5
    ([6.0, 6.0, 6.5, 6.5], 6.5),
    ([5.5, 5.5, 5.5, 5.5], 5.5),
    ([5.0, 5.5, 5.5, 6.0], 5.5),   # 5.5 exacto
    ([7.0, 6.5, 6.5, 6.5], 6.5),   # 6.625 → 6.5
    ([7.0, 7.0, 6.5, 7.0], 7.0),   # 6.875 → 7.0
])
def test_round_band(values, expected):
    assert round_band(values) == expected


def test_overall_band():
    assert overall_band(6.5, 6.5, 6.0, 6.0) == 6.5


def test_checkpoint_advice():
    assert checkpoint_advice(6.0) == "keep"
    assert checkpoint_advice(6.5) == "keep"
    assert checkpoint_advice(5.5) == "consult"
    assert checkpoint_advice(5.0) == "reschedule"
