"""Sesión: bloques en secuencia con temporizador, "siguiente bloque" y resumen final."""
import time

import streamlit as st

from ielts import db
from ielts.curriculum import load_curriculum
from ielts.modules.registry import render_block
from ielts.ui import fmt_mmss, get_conn, page_setup, plan_for

page_setup("Sesión · IELTS Trainer", "⏱️")

sel = st.session_state.get("session")
if not sel:
    st.info("Elige un día en la página de inicio.")
    st.page_link("app.py", label="← Ir al inicio")
    st.stop()

cur = load_curriculum()
conn = get_conn()
blocks = plan_for(sel["weekday"], sel["phase"], sel["diagnostic"], sel["week"])
title = "Diagnóstico" if sel["diagnostic"] else cur.days[sel["weekday"]].label
state_key = f"flow_{sel['week']}_{sel['weekday']}"
flow = st.session_state.setdefault(state_key, {"idx": 0, "start": time.time(), "secs": {}})

st.title(f"{title} · {'línea base' if sel['diagnostic'] else f'semana {sel['week']}'}")
st.progress(min(flow["idx"], len(blocks)) / len(blocks))
st.page_link("app.py", label="← Inicio")

if flow["idx"] >= len(blocks):
    total = sum(flow["secs"].values())
    st.success("Sesión completada 🎉")
    st.table([{"Bloque": b.title, "Plan (min)": b.minutes,
               "Real (min)": round(flow["secs"].get(b.id, 0) / 60, 1)} for b in blocks])
    st.metric("Tiempo total", f"{total // 60} min")
    if st.button("Repetir sesión"):
        del st.session_state[state_key]
        st.rerun()
    st.stop()

block = blocks[flow["idx"]]
timed = block.timed_from_phase is not None and sel["phase"] >= block.timed_from_phase
st.subheader(f"Bloque {flow['idx'] + 1}/{len(blocks)} · {block.title}")
st.info(f"**Estrategia:** {block.strategy}")


@st.fragment(run_every=1)
def timer():
    elapsed = int(time.time() - flow["start"])
    remaining = block.minutes * 60 - elapsed
    left, right = st.columns(2)
    left.metric("Transcurrido", fmt_mmss(elapsed))
    right.metric("Restante" if remaining >= 0 else "Excedido", fmt_mmss(remaining))
    if remaining < 0:
        st.warning("Tiempo del bloque agotado." if timed else
                   "Pasaste el tiempo sugerido (en esta fase el cronómetro es orientativo).")


timer()
ctx = {"week": sel["week"], "weekday": sel["weekday"], "phase": sel["phase"], "diagnostic": sel["diagnostic"]}
can_advance = render_block(block, ctx)
st.divider()

if st.button("Siguiente bloque ▶" if flow["idx"] < len(blocks) - 1 else "Terminar sesión ✔", type="primary",
             disabled=not can_advance, help=None if can_advance else "Completa este paso para continuar."):
    secs = int(time.time() - flow["start"])
    flow["secs"][block.id] = secs
    if not sel["diagnostic"]:
        db.mark_block_done(conn, sel["week"], sel["weekday"], block.id, secs)
    flow["idx"] += 1
    flow["start"] = time.time()
    st.rerun()
