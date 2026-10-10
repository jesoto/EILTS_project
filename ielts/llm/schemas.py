"""Esquemas pydantic de todas las respuestas JSON del LLM."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ErrorCategory(str, Enum):
    subject_omission = "subject_omission"
    sv_agreement = "sv_agreement"
    articles = "articles"
    verb_tense = "verb_tense"
    prepositions = "prepositions"
    false_friend = "false_friend"
    collocation = "collocation"
    word_form = "word_form"
    spelling = "spelling"
    punctuation = "punctuation"
    cohesion = "cohesion"
    task_response = "task_response"
    other = "other"


def _half_band(v: float) -> float:
    v = max(0.0, min(9.0, float(v)))
    return round(v * 2) / 2


class ErrorItem(BaseModel):
    fragmento: str = Field(description="Exact wrong fragment copied from the learner's text")
    correccion: str = Field(description="Corrected English fragment")
    categoria: ErrorCategory
    explicacion_es: str = Field(description="Short explanation in Spanish")

    @field_validator("categoria", mode="before")
    @classmethod
    def _unknown_to_other(cls, v):
        return v if v in {c.value for c in ErrorCategory} else "other"


class CriterionScore(BaseModel):
    banda: float
    justificacion_es: str

    @field_validator("banda")
    @classmethod
    def _round(cls, v):
        return _half_band(v)


class SentenceToRewrite(BaseModel):
    original: str
    problema_es: str


class ImprovedParagraph(BaseModel):
    original: str
    mejorado: str = Field(description="Improved English version")
    notas_es: str


class WritingEvaluation(BaseModel):
    ta_tr: CriterionScore = Field(description="Task Achievement (T1) / Task Response (T2)")
    cc: CriterionScore
    lr: CriterionScore
    gra: CriterionScore
    errores: list[ErrorItem]
    oraciones_a_reescribir: list[SentenceToRewrite] = Field(min_length=3, max_length=3)
    parrafo_mejorado: ImprovedParagraph


class RewriteCheck(BaseModel):
    original: str
    reescrita: str
    correcta: bool
    problema_restante_es: str = ""
    mejor_version: str = ""


class RewriteEvaluation(BaseModel):
    resultados: list[RewriteCheck]


# ---- Gramática ----
ExerciseKind = Literal["gap_fill", "error_correction", "transformation", "word_order", "free_writing"]


class ExerciseItem(BaseModel):
    prompt: str = Field(description="Sentence with gap '____', erroneous sentence, source sentence, "
                                    "or scrambled words, depending on the kind")
    answer: str = Field(description="The single best answer (for free_writing: a model answer)")
    accepted: list[str] = Field(default_factory=list, description="Other fully correct answers")
    options: list[str] = Field(default_factory=list, description="Optional choices (gap_fill with distractors)")
    explicacion_es: str = ""


class GrammarExercise(BaseModel):
    kind: ExerciseKind
    instruction: str
    items: list[ExerciseItem] = Field(min_length=1)


class ProductionFeedback(BaseModel):
    errores: list[ErrorItem]
    comentario_es: str
    version_corregida: str
    topic_used_correctly: bool
