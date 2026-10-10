"""Inicio: semana actual, fase, cuenta atrás y los 7 botones de práctica."""
import streamlit as st

from ielts import db
from ielts.calendar import Mode, day_info, days_to_exam, effective_week
from ielts.curriculum import WEEKDAYS, load_curriculum
from ielts.ui import get_conn, plan_for, today

st.set_page_config(page_title="IELTS Trainer", page_icon="📘", layout="wide")

cur = load_curriculum()
conn = get_conn()
now = today()
info = day_info(now, cur)
week = effective_week(now, cur)
phase = cur.phase_of_week(week)
wk = cur.week(week)

st.title("📘 IELTS Trainer")
c1, c2, c3 = st.columns(3)
if info.mode is Mode.DIAGNOSTIC:
    c1.metric("Semana", "Diagnóstico", help=f"El plan empieza el {cur.start_date:%d/%m/%Y}")
else:
    c1.metric("Semana", f"{week} de {len(cur.weeks)}")
c2.metric("Fase", f"{phase.id}. {phase.name}")
c3.metric("Días al examen", max(days_to_exam(now, cur), 0))

if info.mode is Mode.DIAGNOSTIC:
    st.info(f"Modo **diagnóstico**: haz un test completo para tener tu línea base. "
            f"El plan de 11 semanas arranca el {cur.start_date:%d/%m/%Y}.")
    if st.button("▶ Empezar diagnóstico", type="primary"):
        st.session_state["session"] = {"weekday": "diagnostic", "week": 0, "phase": 0, "diagnostic": True}
        st.switch_page("pages/1_Sesion.py")
elif info.mode is Mode.FREE:
    st.success("Día libre. Descansa.")
elif info.mode is Mode.REST:
    st.warning("Día de descanso previo al examen. Checklist de logística:")
    for item in cur.rest_day_checklist:
        st.checkbox(item, key=f"rest_{item}")
elif info.mode is Mode.EXAM:
    st.success("¡Hoy es el examen! Confía en tu preparación.")

with st.expander(f"Tema de la semana {week}", expanded=info.mode is Mode.TRAINING):
    st.markdown(f"- **Gramática:** {wk.grammar}\n- **Writing:** {wk.writing}\n"
                f"- **Reading / Listening:** {wk.receptive}\n- **Vocabulario:** {wk.vocab}")

st.subheader("Práctica de la semana")
st.caption("Puedes practicar cualquier día, no solo hoy.")
cols = st.columns(7)
for col, weekday in zip(cols, WEEKDAYS):
    day = cur.days[weekday]
    blocks = plan_for(weekday, phase.id)
    done = db.day_is_done(conn, week, weekday, [b.id for b in blocks])
    is_today = info.mode is Mode.TRAINING and weekday == info.weekday
    minutes = sum(b.minutes for b in blocks)
    with col:
        label = f"{'✅ ' if done else ''}{day.label}"
        if st.button(label, key=f"day_{weekday}", type="primary" if is_today else "secondary",
                     use_container_width=True):
            st.session_state["session"] = {"weekday": weekday, "week": week, "phase": phase.id,
                                           "diagnostic": False}
            st.switch_page("pages/1_Sesion.py")
        st.caption(f"{'**Hoy** · ' if is_today else ''}{'hecho' if done else 'pendiente'}  \n"
                   f"{minutes // 60}h{minutes % 60:02d} · {day.where}")
