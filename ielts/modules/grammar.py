"""Gramática: temas, generación de ejercicios, corrección cerrada (sin LLM) y producción (LLM)."""
from __future__ import annotations

import hashlib
import random
import sqlite3
from functools import lru_cache
from pathlib import Path

import yaml

from .. import db
from ..config import LLMConfig, load_llm_config
from ..llm.base import LLMProvider
from ..llm.client import generate_json, load_prompt
from ..llm.schemas import ExerciseItem, GrammarExercise, ProductionFeedback
from ..text import normalize_answer

TOPICS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "grammar_topics.yaml"
KIND_ROTATION = ["gap_fill", "error_correction", "transformation", "word_order", "free_writing"]
FALLBACK_TOPICS = ["subject_agreement", "articles", "t1_tenses_prepositions"]


@lru_cache(maxsize=1)
def load_topics() -> dict:
    with open(TOPICS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_topics(topic_ids: list[str], conn: sqlite3.Connection) -> list[str]:
    """Sustituye 'error_log' por los temas de las 3 categorías con más errores."""
    data = load_topics()
    out: list[str] = []
    for t in topic_ids:
        if t != "error_log":
            out.append(t)
            continue
        for cat, _ in db.top_categories(conn, limit=5):
            topic = data["category_topics"].get(cat)
            if topic and topic not in out:
                out.append(topic)
    if "error_log" in topic_ids:
        out = out[:3]
        for t in FALLBACK_TOPICS:  # sin historial suficiente
            if len(out) >= 3:
                break
            if t not in out:
                out.append(t)
    return out


def next_kind(last_kind: str | None) -> str:
    """Rota los formatos; nunca repite el mismo dos veces seguidas."""
    if last_kind not in KIND_ROTATION:
        return KIND_ROTATION[0]
    return KIND_ROTATION[(KIND_ROTATION.index(last_kind) + 1) % len(KIND_ROTATION)]


def last_generated_kind(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT kind FROM generated_exercise ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
    return row["kind"] if row else None


def exercise_hash(topic: str, ex: GrammarExercise) -> str:
    body = "|".join(normalize_answer(i.prompt, strip_final_punct=False) for i in ex.items)
    return hashlib.sha256(f"{topic}|{ex.kind}|{body}".encode()).hexdigest()[:24]


def generate_exercise(provider: LLMProvider, conn: sqlite3.Connection, topic_id: str, kind: str, *,
                      level: int, phase: int, frequent_errors: list[str] | None = None,
                      n_items: int = 6, cfg: LLMConfig | None = None, max_tries: int = 3) -> GrammarExercise:
    """Genera un ejercicio nuevo; si el hash ya existe, vuelve a generar con otra semilla."""
    cfg = cfg or load_llm_config()
    topic = load_topics()["topics"][topic_id]
    last: GrammarExercise | None = None
    for _ in range(max_tries):
        seed = random.randint(1, 10_000_000)
        system = load_prompt(
            "grammar_generate", topic=topic["name"], kind=kind, n_items=n_items, level=level, phase=phase,
            frequent_errors=", ".join(frequent_errors or []) or "none recorded yet",
            interference=topic["interference"], seed=seed)
        ex = generate_json(provider, GrammarExercise, system, "Generate the exercise now.",
                           temperature=cfg.temperature_gen, max_retries=cfg.max_retries, seed=seed)
        ex.kind = kind  # el formato lo decide la rotación, no el modelo
        last = ex
        h = exercise_hash(topic_id, ex)
        if not db.exercise_seen(conn, h):
            db.remember_exercise(conn, h, kind, topic_id)
            return ex
    assert last is not None
    return last  # tras varios intentos aceptamos el último aunque se parezca


def is_correct(item: ExerciseItem, user_answer: str) -> bool:
    """Corrección cerrada sin LLM: solo se normalizan mayúsculas, espacios y punto final."""
    given = normalize_answer(user_answer)
    if not given:
        return False
    valid = {normalize_answer(a) for a in [item.answer, *item.accepted]}
    return given in valid


def grade_closed(ex: GrammarExercise, answers: list[str]) -> list[bool]:
    return [is_correct(item, a) for item, a in zip(ex.items, answers)]


def evaluate_production(provider: LLMProvider, topic_id: str, task: str, text: str,
                        cfg: LLMConfig | None = None) -> ProductionFeedback:
    cfg = cfg or load_llm_config()
    topic = load_topics()["topics"][topic_id]
    system = load_prompt("grammar_production", topic=topic["name"], task=task, text=text)
    return generate_json(provider, ProductionFeedback, system, "Evaluate the paragraph now.",
                         temperature=cfg.temperature_eval, max_retries=cfg.max_retries)


def log_feedback_errors(conn: sqlite3.Connection, module: str, errors) -> None:
    for e in errors:
        db.log_error(conn, module, e.fragmento, e.correccion, e.categoria.value, e.explicacion_es)
