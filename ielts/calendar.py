"""Cálculo de semana, fase y modo del día. Todo sale de curriculum.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .curriculum import WEEKDAYS, Curriculum, load_curriculum


class Mode(str, Enum):
    DIAGNOSTIC = "diagnostic"  # antes del inicio
    TRAINING = "training"
    FREE = "free"              # 24 y 25 dic
    REST = "rest"              # 28 dic
    EXAM = "exam"              # 29 dic
    AFTER = "after"


@dataclass(frozen=True)
class DayInfo:
    day: date
    mode: Mode
    week: int          # 0 antes del inicio
    phase: int         # 0 antes del inicio
    weekday: str       # monday..sunday


def week_number(d: date, cur: Curriculum | None = None) -> int:
    """Semana N = ((fecha - inicio).days // 7) + 1. 0 antes del inicio."""
    cur = cur or load_curriculum()
    delta = (d - cur.start_date).days
    return 0 if delta < 0 else delta // 7 + 1


def phase_of(d: date, cur: Curriculum | None = None) -> int:
    cur = cur or load_curriculum()
    w = week_number(d, cur)
    return 0 if w == 0 else cur.phase_of_week(w).id


def day_mode(d: date, cur: Curriculum | None = None) -> Mode:
    cur = cur or load_curriculum()
    if d < cur.start_date:
        return Mode.DIAGNOSTIC
    if d == cur.exam_date:
        return Mode.EXAM
    if d > cur.exam_date:
        return Mode.AFTER
    if d == cur.rest_day:
        return Mode.REST
    if d in cur.free_days:
        return Mode.FREE
    return Mode.TRAINING


def day_info(d: date, cur: Curriculum | None = None) -> DayInfo:
    cur = cur or load_curriculum()
    return DayInfo(d, day_mode(d, cur), week_number(d, cur), phase_of(d, cur), WEEKDAYS[d.weekday()])


def days_to_exam(d: date, cur: Curriculum | None = None) -> int:
    cur = cur or load_curriculum()
    return (cur.exam_date - d).days


def effective_week(d: date, cur: Curriculum | None = None) -> int:
    """Semana usada para cargar contenido: 1 en diagnóstico, 11 tras la semana 11."""
    cur = cur or load_curriculum()
    return min(max(week_number(d, cur), 1), len(cur.weeks))
