"""Bloque de Gramática: micro-teoría → ejercicios (rotando formato) → producción."""
from __future__ import annotations

import streamlit as st

from .. import db
from ..curriculum import load_curriculum
from ..llm.base import LLMError
from ..ui import get_conn, get_provider
from . import grammar as g

TOPIC_CATEGORY = {  # categoría de error por defecto cuando falla un ejercicio cerrado de ese tema
    "subject_agreement": "subject_omission", "articles": "articles", "t1_tenses_prepositions": "verb_tense",
    "relatives_concessives": "other", "conditionals": "verb_tense", "passive": "verb_tense",
    "inversion_nominalization": "other",
}
THEMES = ["education", "technology", "the environment", "health", "cities and society", "work and the economy"]


def render(block, ctx) -> bool:
    conn, week = get_conn(), ctx["week"]
    cur = load_curriculum()
    key = f"gram_{week}_{ctx['weekday']}_{block.id}"
    s = st.session_state.setdefault(key, {"stage": "theory", "n": 0})

    topics = g.resolve_topics(cur.focus(week).grammar_topics, conn)
    names = g.load_topics()["topics"]
    topic_id = st.selectbox("Tema", topics, format_func=lambda t: names[t]["name"], key=f"{key}_topic",
                            disabled=s["stage"] != "theory")
    s["topic"] = topic_id

    if s["stage"] == "theory":
        st.markdown(names[topic_id]["theory_es"])
        if st.button("Empezar ejercicios ▶", key=f"{key}_go", type="primary"):
            s["stage"] = "generate"
            st.rerun()
        return True

    if s["stage"] == "generate":
        level = db.get_level(conn, "grammar")
        kind = g.next_kind(g.last_generated_kind(conn))
        freq = [c for c, _ in db.top_categories(conn, limit=3)]
        try:
            with st.spinner(f"Generando ejercicio ({kind}) con el modelo local…"):
                s["exercise"] = g.generate_exercise(get_provider(), conn, topic_id, kind, level=level,
                                                    phase=ctx["phase"], frequent_errors=freq).model_dump()
        except LLMError as e:
            st.error(f"No se pudo generar el ejercicio: {e}")
            if st.button("Reintentar", key=f"{key}_retry"):
                st.rerun()
            return True
        s["stage"] = "free" if kind == "free_writing" else "exercise"
        s["answers"], s["results"] = None, None
        st.rerun()

    ex = g.GrammarExercise.model_validate(s["exercise"]) if "exercise" in s else None

    if s["stage"] == "exercise" and ex:
        st.caption(f"Formato: **{ex.kind}** · nivel {db.get_level(conn, 'grammar')}/10")
        st.markdown(f"**{ex.instruction}**")
        with st.form(f"{key}_form_{s['n']}"):
            answers = []
            for i, item in enumerate(ex.items):
                st.markdown(f"**{i + 1}.** {item.prompt}")
                if item.options:
                    answers.append(st.radio("Respuesta", item.options, index=None, key=f"{key}_a{s['n']}_{i}",
                                            horizontal=True, label_visibility="collapsed") or "")
                else:
                    answers.append(st.text_input("Respuesta", key=f"{key}_a{s['n']}_{i}", label_visibility="collapsed"))
            submitted = st.form_submit_button("Corregir", type="primary")
        if submitted:
            results = g.grade_closed(ex, answers)
            for item, ok, ans in zip(ex.items, results, answers):
                if not ok:
                    db.log_error(conn, "grammar", ans or "(vacío)", item.answer,
                                 TOPIC_CATEGORY.get(topic_id, "other"), item.explicacion_es)
            db.record_attempt(conn, "grammar", sum(results) / len(results), topic_id)
            s["answers"], s["results"], s["stage"] = answers, results, "reviewed"
            st.rerun()

    if s["stage"] == "reviewed" and ex:
        score = sum(s["results"])
        st.metric("Aciertos", f"{score}/{len(ex.items)}")
        for i, (item, ok, ans) in enumerate(zip(ex.items, s["results"], s["answers"]), start=1):
            if ok:
                st.success(f"{i}. ✅ {item.prompt} → **{item.answer}**")
            else:
                st.error(f"{i}. ❌ {item.prompt}\n\nTu respuesta: *{ans or '(vacío)'}* → correcta: **{item.answer}**\n\n{item.explicacion_es}")
        if st.button("Ahora produce: escribe un párrafo ▶", key=f"{key}_prod", type="primary"):
            s["stage"] = "free"
            s["task"] = None
            st.rerun()

    if s["stage"] in ("free", "free_done"):
        if not s.get("task"):
            theme = THEMES[s["n"] % len(THEMES)]
            if ex and ex.kind == "free_writing":
                s["task"] = ex.items[0].prompt
            else:
                s["task"] = (f"Write a short paragraph (4-6 sentences) about {theme} that uses this grammar point "
                             f"at least twice: {names[topic_id]['name']}.")
        st.markdown(f"**Producción:** {s['task']}")
        text = st.text_area("Tu párrafo (en inglés)", key=f"{key}_text{s['n']}", height=160,
                            disabled=s["stage"] == "free_done")
        if s["stage"] == "free" and st.button("Evaluar párrafo", key=f"{key}_eval", type="primary"):
            if len(text.split()) < 15:
                st.warning("Escribe al menos 15 palabras.")
            else:
                try:
                    with st.spinner("Evaluando…"):
                        fb = g.evaluate_production(get_provider(), topic_id, s["task"], text)
                    g.log_feedback_errors(conn, "grammar", fb.errores)
                    db.record_attempt(conn, "grammar", 1.0 if fb.topic_used_correctly and len(fb.errores) <= 2
                                      else 0.6 if fb.topic_used_correctly else 0.3, "production")
                    s["feedback"], s["stage"] = fb.model_dump(), "free_done"
                    st.rerun()
                except LLMError as e:
                    st.error(str(e))
        if s["stage"] == "free_done":
            fb = g.ProductionFeedback.model_validate(s["feedback"])
            (st.success if fb.topic_used_correctly else st.warning)(fb.comentario_es)
            for e in fb.errores:
                st.markdown(f"- ❌ *{e.fragmento}* → ✅ **{e.correccion}** `{e.categoria.value}` — {e.explicacion_es}")
            st.markdown(f"**Versión corregida:** {fb.version_corregida}")
            if st.button("Otra ronda de ejercicios", key=f"{key}_again"):
                s["stage"], s["n"], s["task"] = "generate", s["n"] + 1, None
                st.rerun()
    return True
