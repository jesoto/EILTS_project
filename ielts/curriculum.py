"""Carga y validación de data/curriculum.yaml (única fuente del plan)."""
from __future__ import annotations

from datetime import date
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
    srs_block: Block
    days: dict[str, Day]
    phase_overrides: dict[int, dict[str, list[Block]]] = {}
    diagnostic: dict
    rest_day_checklist: list[str]

    def week(self, n: int) -> Week:
        return self.weeks[min(max(n, 1), len(self.weeks)) - 1]

    def phase_of_week(self, n: int) -> Phase:
        for p in self.phases:
            if p.weeks[0] <= n <= p.weeks[1]:
                return p
        return self.phases[-1] if n > 0 else self.phases[0]

    def blocks_for(self, weekday: str, phase_id: int) -> list[Block]:
        """Bloques del día para la fase, con el SRS de 15 min siempre al final."""
        override = self.phase_overrides.get(phase_id, {}).get(weekday)
        blocks = list(override if override is not None else self.days[weekday].blocks)
        return blocks + [self.srs_block]

    def diagnostic_blocks(self) -> list[Block]:
        return [Block(**b) for b in self.diagnostic["blocks"]] + [self.srs_block]


@lru_cache(maxsize=1)
def load_curriculum(path: str | None = None) -> Curriculum:
    with open(path or CURRICULUM_PATH, encoding="utf-8") as f:
        return Curriculum.model_validate(yaml.safe_load(f))
