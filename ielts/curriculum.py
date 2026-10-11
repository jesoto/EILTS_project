"""Carga y validación de data/curriculum.yaml (única fuente del plan)."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CURRICULUM_PATH = Path(__file__).resolve().parent.parent / "data" / "curriculum.yaml"

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class Block(BaseModel):
    id: str
    title: str
    minutes: int
    module: str
    strategy: str = ""
    timed_from_phase: int | None = None


class Phase(BaseModel):
    id: int
    name: str
    weeks: tuple[int, int]
    start: date
    end: date
    timed_writing: bool
    full_tests: bool


class Week(BaseModel):
    n: int
    grammar: str
    writing: str
    receptive: str
    vocab: str
    listening_speed: float = 1.0
    light: bool = False


class WeekFocus(BaseModel):
    grammar_topics: list[str]
    t1: list[str]
    t2: list[str]


class ReceptiveFocus(BaseModel):
    reading_types: list[str]
    listening_part: int


class Day(BaseModel):
    label: str
    where: str
    blocks: list[Block]


class Curriculum(BaseModel):
    start_date: date
    exam_date: date
    checkpoint_date: date
    free_days: list[date]
    rest_day: date
    phases: list[Phase]
    weeks: list[Week]
    week_focus: dict[int, WeekFocus]
    receptive_focus: dict[int, ReceptiveFocus] = {}
    srs_block: Block
    days: dict[str, Day]
    phase_overrides: dict[int, dict[str, list[Block]]] = {}
    week_overrides: dict[int, dict[str, list[Block]]] = {}
    diagnostic: dict
    rest_day_checklist: list[str]

    def week(self, n: int) -> Week:
        return self.weeks[min(max(n, 1), len(self.weeks)) - 1]

    def focus(self, n: int) -> WeekFocus:
        return self.week_focus[min(max(n, 1), len(self.weeks))]

    def receptive(self, n: int) -> ReceptiveFocus | None:
        return self.receptive_focus.get(n)

    def phase_of_week(self, n: int) -> Phase:
        for p in self.phases:
            if p.weeks[0] <= n <= p.weeks[1]:
                return p
        return self.phases[-1] if n > 0 else self.phases[0]

    def blocks_for(self, weekday: str, phase_id: int, week: int = 0) -> list[Block]:
        """Bloques del día (semana > fase > plan base), con el SRS de 15 min siempre al final."""
        override = self.week_overrides.get(week, {}).get(weekday)
        if override is None:
            override = self.phase_overrides.get(phase_id, {}).get(weekday)
        blocks = list(override if override is not None else self.days[weekday].blocks)
        return blocks + [self.srs_block]

    def diagnostic_blocks(self) -> list[Block]:
        return [Block(**b) for b in self.diagnostic["blocks"]] + [self.srs_block]


def derive_plan_dates(exam: date, free_days: tuple[date, ...] = ()) -> dict:
    """Fechas del plan de 11 semanas a partir de la fecha de examen.

    Inicio = lunes de 11 semanas antes de la semana del examen (examen 29-dic-2026 → inicio 12-oct-2026);
    punto de control = domingo de la semana 6; día de descanso = víspera del examen.
    """
    exam_monday = exam - timedelta(days=exam.weekday())
    start = exam_monday - timedelta(weeks=11)
    return {"start_date": start, "exam_date": exam, "checkpoint_date": start + timedelta(days=41),
            "rest_day": exam - timedelta(days=1), "free_days": list(free_days)}


def _apply_exam_date(cur: Curriculum, exam: date, free_days: tuple[date, ...]) -> Curriculum:
    dates = derive_plan_dates(exam, free_days)
    phases = []
    for ph in cur.phases:
        first = dates["start_date"] + timedelta(weeks=ph.weeks[0] - 1)
        last = dates["start_date"] + timedelta(weeks=ph.weeks[1]) - timedelta(days=1)
        phases.append(ph.model_copy(update={"start": first, "end": last}))
    return cur.model_copy(update={**dates, "phases": phases})


@lru_cache(maxsize=8)
def _load(path: str, exam_iso: str, free_days: tuple[str, ...]) -> Curriculum:
    with open(path, encoding="utf-8") as f:
        cur = Curriculum.model_validate(yaml.safe_load(f))
    if exam_iso:
        cur = _apply_exam_date(cur, date.fromisoformat(exam_iso), tuple(date.fromisoformat(d) for d in free_days))
    return cur


def load_curriculum(path: str | None = None) -> Curriculum:
    """Currículo; si hay `exam_date` en config.toml/IELTS_EXAM_DATE, las fechas se derivan de ella."""
    from .config import load_app_config
    app = load_app_config()
    return _load(str(path or CURRICULUM_PATH), app.exam_date, app.free_days)
