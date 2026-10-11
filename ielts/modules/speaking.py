"""Speaking: contenido por tema, análisis (STT + métricas), feedback LLM y shadowing."""
from __future__ import annotations

import dataclasses
import json
import random
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from .. import db
from ..config import LLMConfig, load_llm_config
from ..llm.base import LLMProvider
from ..llm.client import generate_json, load_prompt
from ..llm.schemas import SpeakingEvaluation
from ..scoring import round_band
from ..speaking_metrics import SpeakingMetrics, compare_transcripts, compute_metrics
from ..stt import Transcriber, Transcript
from .. import clock

ROOT = Path(__file__).resolve().parent.parent.parent
CONTENT_PATH = ROOT / "data" / "speaking_content.yaml"
PART_LABEL = {"p2": "Speaking Part 2 (long turn)", "p13": "Speaking Parts 1 and 3"}
BANNER = "banda estimada (aproximada)"


@lru_cache(maxsize=1)
def load_content() -> dict:
    with open(CONTENT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["themes"]


def theme_content(theme: str, rng: random.Random | None = None) -> tuple[str, dict]:
    """Contenido del tema semanal; en semanas de repaso ('Repaso …') elige un tema al azar."""
    rng = rng or random.Random()
    themes = load_content()
    if theme not in themes:
        theme = rng.choice(list(themes))
    return theme, themes[theme]


def part2_card(theme: str, rng: random.Random | None = None) -> tuple[str, dict]:
    rng = rng or random.Random()
    name, content = theme_content(theme, rng)
    return name, rng.choice(content["cards"])


def card_text(card: dict) -> str:
    pts = "\n".join(f"- {p}" for p in card["points"])
    return f"{card['topic']}\nYou should say:\n{pts}"


def part13_questions(theme: str, rng: random.Random | None = None, n1: int = 3, n3: int = 2) -> list[tuple[str, str]]:
    rng = rng or random.Random()
    _, content = theme_content(theme, rng)
    q1 = rng.sample(content["part1"], min(n1, len(content["part1"])))
    q3 = rng.sample(content["part3"], min(n3, len(content["part3"])))
    return [("Part 1", q) for q in q1] + [("Part 3", q) for q in q3]


def analyze(transcriber: Transcriber, audios: list[bytes]) -> tuple[list[Transcript], SpeakingMetrics]:
    transcripts = [transcriber.transcribe(a) for a in audios]
    return transcripts, compute_metrics([t.words for t in transcripts if t.words])


def evaluate_speaking(provider: LLMProvider, part: str, prompt: str, transcript: str,
                      metrics: SpeakingMetrics, cfg: LLMConfig | None = None) -> SpeakingEvaluation:
    cfg = cfg or load_llm_config()
    system = load_prompt("speaking_evaluate", part_label=PART_LABEL[part], prompt=prompt,
                         metrics=metrics.summary(), low_conf=", ".join(metrics.low_confidence) or "none",
                         transcript=transcript)
    return generate_json(provider, SpeakingEvaluation, system, "Assess the answer now.",
                         temperature=cfg.temperature_eval, max_retries=cfg.max_retries)


def overall_speaking(ev: SpeakingEvaluation) -> float:
    """Promedio de FC/LR/GRA (la pronunciación no se puntúa). Aproximado."""
    return round_band([ev.fc.banda, ev.lr.banda, ev.gra.banda])


def save_session(conn: sqlite3.Connection, week: int, part: str, prompt: str, transcript: str,
                 metrics: SpeakingMetrics, ev: SpeakingEvaluation | None, audio_path: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO speaking_session(date, week, part, prompt, transcript, metrics, evaluation, audio_path) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (clock.timestamp(), week, part, prompt, transcript,
         json.dumps(dataclasses.asdict(metrics), ensure_ascii=False), ev.model_dump_json() if ev else None, audio_path))
    conn.commit()
    if ev:
        for e in ev.errores:
            db.log_error(conn, "speaking", e.fragmento, e.correccion, e.categoria.value, e.explicacion_es)
        db.record_attempt(conn, "speaking", max(0.0, min(1.0, (overall_speaking(ev) - 2.0) / 5.0)), part)
    return cur.lastrowid


def save_recording(audio: bytes, week: int, part: str) -> str:
    """Guarda la grabación (carpeta local o bucket) y devuelve su clave (nombre de archivo)."""
    from ..storage import recordings_store
    name = f"w{week}_{part}_{clock.now():%Y%m%d_%H%M%S}.wav"
    recordings_store().write_bytes(name, audio, content_type="audio/wav")
    return name


def latest_session(conn: sqlite3.Connection, part: str | None = None) -> sqlite3.Row | None:
    q, args = "SELECT * FROM speaking_session", []
    if part:
        q += " WHERE part=?"
        args.append(part)
    return conn.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()


# ---- shadowing
def list_shadowing_audios() -> list[str]:
    """Claves (en resources/) de los mp3 de Listening de los libros Cambridge: solo lectura."""
    from ..storage import resources_store
    return [k for k in resources_store().list("") if k.lower().endswith(".mp3")
            and "cambr" in k.lower() and "grammar" not in k.lower()]


def shadowing_compare(reference: str, spoken: str) -> dict:
    return compare_transcripts(reference, spoken)
