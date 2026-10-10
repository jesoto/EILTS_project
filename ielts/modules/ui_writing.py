"""Bloques de Writing: editor con contador, checklist, evaluación y reescritura obligatoria."""
from __future__ import annotations

import random

import streamlit as st

from .. import db
from ..checklist import MIN_WORDS, SUGGESTED_WORDS, run_checklist
from ..curriculum import load_curriculum
from ..llm.base import LLMError
from ..llm.schemas import WritingEvaluation
from ..text import word_count
from ..ui import get_conn, get_provider
from . import writing as w
from .charts import CHART_TYPES, make_chart

LIMIT_MIN = {"t1": 20, "t2": 40}


def _task_for_block(block) -> str | None:
    return {"writing_t1": "t1", "writing_t2": "t2"}.get(block.id)


def render(block, ctx) -> bool:
    if block.id == "rewrite":
        return _render_rewrite(block, ctx)
    task = _task_for_block(block)
    key = f"wr_{ctx['week']}_{ctx['weekday']}_{block.id}"
    if task is None:  # simulacro / diagnóstico: Task 1 y Task 2 seguidas
        choice = st.radio("Tarea", ["Task 1", "Task 2"], horizontal=True, key=f"{key}_choice")
        task = "t1" if choice == "Task 1" else "t2"
        key = f"{key}_{task}"
    return _render_task(task, key, ctx)


def _render_task(task: str, key: str, ctx) -> bool:
    conn, week = get_conn(), ctx["week"]
    focus = load_curriculum().focus(week)
    s = st.session_state.setdefault(key, {})

    if "prompt" not in s:
        _new_task(s, task, focus, conn)

    timed = ctx["phase"] >= 2
    st.markdown(f"### {w.TASK_LABEL[task]} · `{s['task_type']}`")
    if timed:
        st.warning(f"Fase cronometrada: límite {LIMIT_MIN[task]} min. Sigue el temporizador del bloque.")
    else:
        st.caption("Fase 1: sin cronómetro. Escribe con calma y aplica la estructura.")
    st.info(s["prompt"])
    if s.get("png"):
        st.image(s["png"])
    if task == "t1":
        st.caption(f"Fuente: {s.get('source', '')}")
        if "evaluation" not in s and s.get("source") != "gráfico generado":
            if st.button("Usar un gráfico generado en su lugar", key=f"{key}_synth"):
                for k in ("prompt", "png", "data_text", "task_type", "source"):
                    s.pop(k, None)
                s["force_synthetic"] = True
                st.rerun()
    if task == "t1":
        st.caption("Estructura: Introducción (paráfrasis) → Overview (2 tendencias, sin cifras) → Cuerpo 1 → Cuerpo 2.")
    else:
        st.caption("Cuerpo: idea → explicación → ejemplo → vínculo con la pregunta. Posición clara desde la introducción.")

    done = "evaluation" in s
    text = st.text_area("Tu respuesta (separa los párrafos con una línea en blanco)", key=f"{key}_text",
                        height=320, disabled=done)
    n = word_count(text)
    mn, sg = MIN_WORDS[task], SUGGESTED_WORDS[task]
    color = "green" if n >= sg else "orange" if n >= mn else "red"
    st.markdown(f"**Palabras:** :{color}[{n}] · mínimo {mn} · sugerido {sg}")

    if not done:
        with st.expander("Checklist automática (sin LLM)"):
            for c in run_checklist(text, task) if text.strip() else []:
                st.markdown(f"{'✅' if c.ok else '⚠️'} {c.message_es}" + (f"  \n`{'; '.join(c.evidence[:3])}`" if c.evidence else ""))
        if st.button("Enviar a evaluación", key=f"{key}_send", type="primary", disabled=n < 30):
            try:
                with st.spinner("El modelo local está evaluando (puede tardar ~1 min)…"):
                    ev, _ = w.evaluate_writing(get_provider(), task, s["prompt"], text, data_text=s["data_text"])
            except LLMError as e:
                st.error(str(e))
                return True
            sid = w.save_submission(conn, week, task, s["task_type"], s["prompt"], text, ev)
            db.record_attempt(conn, "writing", w.score_fraction(ev), f"{task}:{s['task_type']}")
            s.update(evaluation=ev.model_dump(), text=text, sid=sid)
            st.rerun()
        return True

    ev = WritingEvaluation.model_validate(s["evaluation"])
    show_evaluation(task, s, ev)
    st.info("Siguiente paso: bloque de **reescritura** (corrige las 3 peores oraciones).")
    return True


def _new_task(s: dict, task: str, focus, conn) -> None:
    """Task 1: se prefiere un gráfico de los libros; si no hay (o no encaja), uno sintético con matplotlib."""
    if task == "t1":
        books = w.book_t1_tasks(focus.t1, conn)
        if books and not s.get("force_synthetic"):
            b = random.choice(books)
            s.update(prompt=b["prompt"], png=b["png"], data_text=w.NO_CHART_DATA, task_type=b["task_type"],
                     source=b["source"])
            return
        synthetic = [k for k in focus.t1 if k in CHART_TYPES] or ["line"]
        chart = make_chart(random.choice(synthetic), seed=random.randint(1, 10**6))
        s.update(prompt=chart.prompt, png=chart.png, data_text=chart.data_text, task_type=chart.kind, source="gráfico generado")
    else:
        tt, p = w.pick_t2_prompt(focus.t2, conn)
        s.update(prompt=p, png=None, data_text="", task_type=tt, source="enunciado propio")


def show_evaluation(task: str, s: dict, ev: WritingEvaluation) -> None:
    st.subheader(f"Resultado · {w.BANNER}")
    cols = st.columns(5)
    for col, (label, c) in zip(cols, [("TA/TR", ev.ta_tr), ("CC", ev.cc), ("LR", ev.lr), ("GRA", ev.gra)]):
        col.metric(label, c.banda, help=c.justificacion_es)
    cols[4].metric("Global", w.overall_writing_band(ev))
    st.caption(f"Todas las bandas son una **{w.BANNER}** del modelo local; úsalas como tendencia, no como veredicto.")
    for label, c in [("TA/TR", ev.ta_tr), ("CC", ev.cc), ("LR", ev.lr), ("GRA", ev.gra)]:
        st.markdown(f"- **{label} {c.banda}:** {c.justificacion_es}")
    with st.expander(f"Errores detectados ({len(ev.errores)})", expanded=True):
        for e in ev.errores:
            st.markdown(f"- ❌ *{e.fragmento}* → ✅ **{e.correccion}** `{e.categoria.value}` — {e.explicacion_es}")
    with st.expander("3 oraciones a reescribir"):
        for o in ev.oraciones_a_reescribir:
            st.markdown(f"- *{o.original}* — {o.problema_es}")
    with st.expander("Párrafo mejorado"):
        st.markdown(f"**Original:** {ev.parrafo_mejorado.original}")
        st.markdown(f"**Mejorado:** {ev.parrafo_mejorado.mejorado}")
        st.caption(ev.parrafo_mejorado.notas_es)
    st.download_button("⬇ Exportar ensayo + feedback (markdown)",
                       w.feedback_markdown(task, s["prompt"], s.get("text", ""), ev),
                       file_name=f"writing_{task}.md", mime="text/markdown", key=f"dl_{s.get('sid')}")


def _render_rewrite(block, ctx) -> bool:
    """Reescritura obligatoria: no se puede avanzar hasta evaluar las 3 oraciones."""
    conn, week = get_conn(), ctx["week"]
    sub = w.latest_submission(conn, week)
    if sub is None:
        st.warning("Aún no tienes un ensayo evaluado esta semana. Haz primero el bloque de Writing.")
        return True  # no bloqueamos: no hay nada que reescribir
    ev = WritingEvaluation.model_validate_json(sub["evaluation"])
    key = f"rw_{sub['id']}"
    s = st.session_state.setdefault(key, {})
    st.markdown(f"Ensayo evaluado el {sub['date'][:10]} (`{sub['task']}`). Reescribe las **3 peores oraciones**:")
    with st.expander("Ver mi ensayo"):
        st.text(sub["text"])

    if "result" not in s:
        with st.form(f"{key}_form"):
            rewrites = []
            for i, o in enumerate(ev.oraciones_a_reescribir, start=1):
                st.markdown(f"**{i}.** *{o.original}*  \n_Problema:_ {o.problema_es}")
                rewrites.append(st.text_input(f"Reescritura {i}", key=f"{key}_r{i}"))
            go = st.form_submit_button("Evaluar reescritura", type="primary")
        if go:
            if not all(r.strip() for r in rewrites):
                st.warning("Reescribe las 3 oraciones antes de evaluar.")
            else:
                try:
                    with st.spinner("Evaluando reescrituras…"):
                        pairs = [(o.original, r) for o, r in zip(ev.oraciones_a_reescribir, rewrites)]
                        res = w.evaluate_rewrites(get_provider(), pairs)
                except LLMError as e:
                    st.error(str(e))
                    return False
                w.save_rewrite(conn, sub["id"], res)
                db.record_attempt(conn, "writing", sum(r.correcta for r in res.resultados) / max(1, len(res.resultados)), "rewrite")
                s["result"] = res.model_dump()
                st.rerun()
        return False

    from ..llm.schemas import RewriteEvaluation
    res = RewriteEvaluation.model_validate(s["result"])
    ok = sum(r.correcta for r in res.resultados)
    st.metric("Reescrituras correctas", f"{ok}/{len(res.resultados)}")
    for r in res.resultados:
        (st.success if r.correcta else st.error)(
            f"*{r.reescrita}*" + ("" if r.correcta else f"\n\n{r.problema_restante_es}") + f"\n\n**Modelo:** {r.mejor_version}")
    return True
