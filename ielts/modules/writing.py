"""Writing: enunciados, evaluación (checklist + LLM), reescritura y exportación del feedback."""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from .. import db
from ..checklist import checklist_summary, run_checklist
from ..config import LLMConfig, load_llm_config
from ..llm.base import LLMProvider
from ..llm.client import generate_json, load_prompt
from ..llm.schemas import RewriteEvaluation, WritingEvaluation
from ..scoring import round_band
from ..text import word_count
from .. import clock

PROMPTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "writing_prompts.yaml"
TASK_LABEL = {"t1": "Academic Writing Task 1", "t2": "Academic Writing Task 2"}
CRITERIA = {
    "t1": ("Task Achievement (TA)", "accurate selection and reporting of key features, a clear overview, "
           "data support, comparisons; no opinion."),
    "t2": ("Task Response (TR)", "all parts of the question answered, a clear position throughout, "
           "ideas that are extended and supported with relevant examples."),
}
BANNER = "banda estimada (aproximada)"
NO_CHART_DATA = "__book_chart__"   # el gráfico es una imagen del libro: el evaluador no ve los datos


@lru_cache(maxsize=1)
def _t2_prompts() -> dict[str, list[str]]:
    with open(PROMPTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def pick_t2_prompt(task_types: list[str], conn: sqlite3.Connection | None = None, rng: random.Random | None = None):
    """Devuelve (tipo, enunciado), evitando repetir enunciados ya escritos si hay alternativas."""
    rng = rng or random.Random()
    used: set[str] = set()
    if conn is not None:
        used = {r["prompt"] for r in conn.execute("SELECT prompt FROM writing_submission WHERE task='t2'")}
    pool = [(t, p) for t in task_types for p in _t2_prompts().get(t, [])]
    fresh = [x for x in pool if x[1] not in used]
    return rng.choice(fresh or pool)


def overall_writing_band(ev: WritingEvaluation) -> float:
    return round_band([ev.ta_tr.banda, ev.cc.banda, ev.lr.banda, ev.gra.banda])


def evaluate_writing(provider: LLMProvider, task: str, prompt: str, text: str, *, data_text: str = "",
                     cfg: LLMConfig | None = None) -> tuple[WritingEvaluation, list]:
    cfg = cfg or load_llm_config()
    checks = run_checklist(text, task)
    ta_name, ta_desc = CRITERIA[task]
    if data_text == NO_CHART_DATA:
        data_block = ("\nThe chart/diagram is an image you cannot see. Do NOT judge the accuracy of the figures or details; "
                      "assess Task Achievement only on structure, the overview, grouping of information and consistent "
                      "reporting, and state in the justification that accuracy could not be verified.\n")
    else:
        data_block = f"\nUnderlying chart data (for checking accuracy):\n{data_text}\n" if data_text else ""
    system = load_prompt("writing_evaluate", task_label=TASK_LABEL[task], ta_name=ta_name, ta_desc=ta_desc,
                         prompt=prompt, data_block=data_block, checklist=checklist_summary(checks),
                         words=word_count(text), text=text)
    ev = generate_json(provider, WritingEvaluation, system, "Assess the response now.",
                       temperature=cfg.temperature_eval, max_retries=cfg.max_retries)
    return ev, checks


def evaluate_rewrites(provider: LLMProvider, pairs: list[tuple[str, str]],
                      cfg: LLMConfig | None = None) -> RewriteEvaluation:
    cfg = cfg or load_llm_config()
    payload = json.dumps([{"original": o, "reescrita": r} for o, r in pairs], ensure_ascii=False, indent=1)
    system = load_prompt("writing_rewrite", pairs=payload)
    return generate_json(provider, RewriteEvaluation, system, "Judge the rewrites now.",
                         temperature=cfg.temperature_eval, max_retries=cfg.max_retries)


def save_submission(conn: sqlite3.Connection, week: int, task: str, task_type: str, prompt: str,
                    text: str, ev: WritingEvaluation) -> int:
    cur = conn.execute(
        "INSERT INTO writing_submission(date, week, task, task_type, prompt, text, evaluation) VALUES (?,?,?,?,?,?,?)",
        (clock.timestamp(), week, task, task_type, prompt, text, ev.model_dump_json()))
    conn.commit()
    for e in ev.errores:
        db.log_error(conn, "writing", e.fragmento, e.correccion, e.categoria.value, e.explicacion_es)
    return cur.lastrowid


def latest_submission(conn: sqlite3.Connection, week: int, task: str | None = None) -> sqlite3.Row | None:
    q, args = "SELECT * FROM writing_submission WHERE week=?", [week]
    if task:
        q += " AND task=?"
        args.append(task)
    return conn.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()


def save_rewrite(conn: sqlite3.Connection, submission_id: int, result: RewriteEvaluation) -> None:
    conn.execute("UPDATE writing_submission SET rewrite=? WHERE id=?", (result.model_dump_json(), submission_id))
    conn.commit()
    for r in result.resultados:
        if not r.correcta:
            db.log_error(conn, "writing_rewrite", r.reescrita, r.mejor_version, "other", r.problema_restante_es)


def score_fraction(ev: WritingEvaluation) -> float:
    """Banda → 0..1 para la ventana de dificultad (6.5+ ≈ 0.85; 5.0 ≈ 0.5)."""
    return max(0.0, min(1.0, (overall_writing_band(ev) - 2.0) / 5.0))


def feedback_markdown(task: str, prompt: str, text: str, ev: WritingEvaluation) -> str:
    """Ensayo + feedback exportable para la profesora."""
    lines = [f"# {TASK_LABEL[task]}", "", f"**Enunciado:** {prompt}", "", "## Ensayo", "", text, "",
             f"## Bandas ({BANNER})", "",
             f"- TA/TR: {ev.ta_tr.banda} — {ev.ta_tr.justificacion_es}",
             f"- CC: {ev.cc.banda} — {ev.cc.justificacion_es}",
             f"- LR: {ev.lr.banda} — {ev.lr.justificacion_es}",
             f"- GRA: {ev.gra.banda} — {ev.gra.justificacion_es}",
             f"- **Global ({BANNER}): {overall_writing_band(ev)}**", "", "## Errores", ""]
    for e in ev.errores:
        lines.append(f"- ❌ *{e.fragmento}* → ✅ **{e.correccion}** ({e.categoria.value}): {e.explicacion_es}")
    lines += ["", "## Oraciones a reescribir", ""]
    lines += [f"- {s.original} — {s.problema_es}" for s in ev.oraciones_a_reescribir]
    lines += ["", "## Párrafo mejorado", "", ev.parrafo_mejorado.mejorado, "", ev.parrafo_mejorado.notas_es]
    return "\n".join(lines)


def book_t1_tasks(task_types: list[str], conn: sqlite3.Connection | None = None, tests=None) -> list[dict]:
    """Tareas de Writing Task 1 extraídas de los libros (imagen + enunciado), aún no escritas por el usuario."""
    from ..ingest import schema
    tests = schema.list_tests() if tests is None else tests
    used: set[str] = set()
    if conn is not None:
        used = {r["prompt"] for r in conn.execute("SELECT prompt FROM writing_submission WHERE task='t1'")}
    out = []
    for t in tests:
        for wt in t.writing:
            if wt.task != 1 or not wt.image or wt.prompt in used or wt.task_type not in task_types:
                continue
            store = schema.derived_store()
            if store.exists(wt.image):
                out.append({"prompt": wt.prompt, "task_type": wt.task_type, "png": store.read_bytes(wt.image),
                            "source": f"{t.book_title} · Test {t.test}"})
    return out
