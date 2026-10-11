"""Esquema de un test ingerido (se guarda en data/derived/<libro>/test<N>.json, ignorado por git)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from .. import clock

DERIVED_DIR = Path(os.environ.get("IELTS_DERIVED") or Path(__file__).resolve().parent.parent.parent / "data" / "derived")
INPUT_KINDS = ("text", "choice", "tfng", "ynng", "headings")


class Group(BaseModel):
    start: int
    end: int
    type: str                       # tfng, ynng, mcq, multi, completion, matching_headings, matching_info, matching, other
    input: str = "text"             # cómo se responde en la UI (INPUT_KINDS)
    options: list[str] = Field(default_factory=list)
    instruction: str = ""
    text: str = ""                  # enunciado tal como aparece en el libro (para mostrar al usuario)

    @property
    def qnums(self) -> list[int]:
        return list(range(self.start, self.end + 1))


class ListeningPart(BaseModel):
    part: int
    qstart: int
    qend: int
    groups: list[Group] = Field(default_factory=list)
    transcript: str = ""
    audio: str | None = None        # ruta relativa a resources/
    pages: list[int] = Field(default_factory=list)


class Passage(BaseModel):
    n: int
    title: str = ""
    text: str = ""
    qstart: int = 0
    qend: int = 0
    groups: list[Group] = Field(default_factory=list)
    paragraph_letters: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)


class WritingTask(BaseModel):
    task: int
    prompt: str
    task_type: str = ""
    page: int = 0
    image: str | None = None        # ruta relativa a data/derived/


class KeyEntry(BaseModel):
    """Una o dos preguntas. `answers[i]` = respuestas aceptadas de la pregunta qnums[i].

    any_order=True: las preguntas de `qnums` (p. ej. 15&16) se pueden contestar en cualquier orden.
    """
    qnums: list[int]
    answers: list[list[str]]
    any_order: bool = False


class TestData(BaseModel):
    __test__ = False   # no es una clase de test para pytest

    book: str
    book_title: str
    test: int
    source_pdf: str = ""
    key_pages: list[int] = Field(default_factory=list)
    listening: list[ListeningPart] = Field(default_factory=list)
    reading: list[Passage] = Field(default_factory=list)
    writing: list[WritingTask] = Field(default_factory=list)
    key_listening: list[KeyEntry] = Field(default_factory=list)
    key_reading: list[KeyEntry] = Field(default_factory=list)
    verified: bool = False
    verified_at: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def test_id(self) -> str:
        return f"{self.book}/test{self.test}"

    def key(self, skill: str) -> list[KeyEntry]:
        return self.key_listening if skill == "listening" else self.key_reading

    def key_map(self, skill: str) -> dict[int, KeyEntry]:
        return {q: e for e in self.key(skill) for q in e.qnums}

    def mark_verified(self) -> None:
        self.verified, self.verified_at = True, clock.timestamp()


def test_path(book: str, test: int, root: Path | None = None) -> Path:
    return (root or DERIVED_DIR) / book / f"test{test}.json"


def save_test(t: TestData, root: Path | None = None) -> Path:
    p = test_path(t.book, t.test, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t.model_dump_json(indent=1), encoding="utf-8")
    return p


def load_test(book: str, test: int, root: Path | None = None) -> TestData | None:
    p = test_path(book, test, root)
    return TestData.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def list_tests(root: Path | None = None) -> list[TestData]:
    base = root or DERIVED_DIR
    out = []
    for p in sorted(base.glob("*/test*.json")) if base.exists() else []:
        out.append(TestData.model_validate(json.loads(p.read_text(encoding="utf-8"))))
    return out
