"""Auditoría guiada del domingo: ¿qué medí? ¿dónde perdí puntos? ¿por qué? ¿qué cambio? ¿cómo me sentí?"""
from __future__ import annotations

import streamlit as st

from .. import audit, progress
from ..curriculum import load_curriculum
from ..ui import get_conn, today

WHY_HINTS = ["Interferencia del español", "Falta de práctica con esta estructura", "Me precipité / no revisé",
             "No conocía el vocabulario", "Ansiedad o cansancio", "Otra razón (escríbela abajo)"]


def render(block, ctx) -> bool:
    conn, cur = get_conn(), load_curriculum()
    week = max(ctx["week"], 1)
    s = progress.week_summary(conn, week, cur)
    key = f"audit_{week}"
    saved = audit.get_audit(conn, week)

    if week == 6:
        _checkpoint_box(conn)

    st.markdown("### 1 · ¿Qué medí?")
    c = st.columns(4)
    c[0].metric("Writing (media)", s["writing_avg"] if s["writing_avg"] else "—", help="banda estimada (aproximada)")
    c[1].metric("Speaking (media)", s["speaking_avg"] if s["speaking_avg"] else "—", help="banda estimada (aproximada)")
    c[2].metric("Reading", ", ".join(f"{r}/{t}" for r, t in s["reading"]) or "—")
    c[3].metric("Listening", ", ".join(f"{r}/{t}" for r, t in s["listening"]) or "—")
    c = st.columns(2)
    c[0].metric("Gramática (acierto medio)", f"{s['grammar_pct']}%" if s["grammar_pct"] is not None else "—")
    c[1].metric("Tarjetas repasadas", s["vocab_reviews"])
    st.caption("Las bandas son estimaciones aproximadas del modelo local: úsalas para ver la tendencia.")

    st.markdown("### 2 · ¿Dónde perdí puntos?")
    if s["top_errors"]:
        st.table([{"Categoría": cat, "Errores": n} for cat, n in s["top_errors"]])
        where = ", ".join(cat for cat, _ in s["top_errors"])
    else:
        st.info("Esta semana aún no hay errores registrados.")
        where = ""

    st.markdown("### 3 · ¿Por qué?")
    hint = st.multiselect("Causas probables", WHY_HINTS, key=f"{key}_hint")
    why_txt = st.text_area("En tus palabras", value=saved["why"] if saved else "", key=f"{key}_why", height=90)

    st.markdown("### 4 · ¿Qué cambio?")
    goal = st.text_input("Un solo objetivo concreto para la próxima semana",
                         value=saved["change_goal"] if saved else "", key=f"{key}_goal",
                         placeholder="Ej.: releer cada oración buscando el sujeto antes de entregar el ensayo")

    st.markdown("### 5 · ¿Cómo me sentí?")
    c1, c2 = st.columns(2)
    energy = c1.slider("Energía (1 = agotado, 5 = con mucha energía)", 1, 5, saved["energy"] if saved else 3, key=f"{key}_e")
    anxiety = c2.slider("Ansiedad (1 = tranquilo, 5 = muy ansioso)", 1, 5, saved["anxiety"] if saved else 2, key=f"{key}_a")

    if st.button("Guardar auditoría", key=f"{key}_save", type="primary"):
        if not goal.strip():
            st.warning("Escribe un objetivo concreto (un solo cambio).")
        else:
            why = "; ".join(hint + ([why_txt.strip()] if why_txt.strip() else []))
            audit.save_audit(conn, week, measured=s, where_lost=where, why=why, change_goal=goal.strip(),
                             energy=energy, anxiety=anxiety, today=today())
            st.rerun()

    saved = audit.get_audit(conn, week)
    if saved:
        st.success(f"Auditoría de la semana {week} guardada. Objetivo: **{saved['change_goal']}**")
        warn = audit.load_warning(conn)
        if warn:
            st.warning(warn)
    return saved is not None


def _checkpoint_box(conn) -> None:
    st.markdown("### 🏁 Punto de control (22 nov)")
    cp = progress.checkpoint(conn)
    if cp is None:
        miss = progress.missing_for_checkpoint(conn)
        st.info("Para calcular el punto de control faltan resultados de: **" + ", ".join(miss) +
                "**. Reading y Listening cuentan solo si hiciste el test completo (40 preguntas); "
                "Writing y Speaking usan tus dos últimas evaluaciones.")
        return
    b = cp["bands"]
    c = st.columns(5)
    for col, (label, key) in zip(c, [("Listening", "listening"), ("Reading", "reading"),
                                     ("Writing", "writing"), ("Speaking", "speaking")]):
        col.metric(label, b[key])
    c[4].metric("Overall (aprox.)", cp["overall"])
    box = {"keep": st.success, "consult": st.warning, "reschedule": st.error}[cp["advice"]]
    box(f"**Banda estimada (aproximada): {cp['overall']}.** {cp['text']}")
