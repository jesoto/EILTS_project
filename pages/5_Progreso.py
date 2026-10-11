"""Progreso: bandas estimadas en el tiempo, raw scores, top errores, racha, nivel por habilidad y punto de control."""
from datetime import timedelta

import pandas as pd
import streamlit as st

from ielts import audit, db, progress
from ielts.config import load_llm_config
from ielts.curriculum import load_curriculum
from ielts.llm.usage import DbUsage, usage_summary
from ielts.ui import get_conn, page_setup, today

page_setup("Progreso · IELTS Trainer", "📈")
st.title("📈 Progreso")
conn, cur, now = get_conn(), load_curriculum(), today()
st.caption("Todas las bandas son **bandas estimadas (aproximadas)** del modelo local: úsalas para ver la tendencia, no como veredicto.")

latest = progress.latest_bands(conn)
c = st.columns(6)
c[0].metric("Racha", f"{progress.streak(conn, now)} días")
for col, (label, key) in zip(c[1:5], [("Listening", "listening"), ("Reading", "reading"),
                                      ("Writing", "writing"), ("Speaking", "speaking")]):
    col.metric(label, latest[key] if latest[key] is not None else "—")
cp = progress.checkpoint(conn)
c[5].metric("Overall (aprox.)", cp["overall"] if cp else "—")
if cp:
    {"keep": st.success, "consult": st.warning, "reschedule": st.error}[cp["advice"]](f"**Punto de control:** {cp['text']}")
else:
    st.caption("Overall disponible cuando tengas una banda de las 4 habilidades "
               "(Reading/Listening solo cuentan con test completo).")
warn = audit.load_warning(conn)
if warn:
    st.warning(warn)

st.subheader("Bandas estimadas en el tiempo")
rows = ([{"fecha": h["date"], "habilidad": "Writing", "banda": h["band"]} for h in progress.writing_history(conn)]
        + [{"fecha": h["date"], "habilidad": "Speaking", "banda": h["band"]} for h in progress.speaking_history(conn)]
        + [{"fecha": h["date"], "habilidad": sk.capitalize(), "banda": h["band"]}
           for sk in ("reading", "listening") for h in progress.receptive_history(conn, sk) if h["band"] is not None])
if rows:
    df = pd.DataFrame(rows).pivot_table(index="fecha", columns="habilidad", values="banda", aggfunc="mean")
    st.line_chart(df)
else:
    st.info("Aún no hay bandas: aparecerán cuando evalúes Writing/Speaking o completes un test de Reading/Listening.")

left, right = st.columns(2)
with left:
    st.subheader("Reading y Listening: % de aciertos")
    raw = [{"fecha": h["date"], "habilidad": sk.capitalize(), "% aciertos": h["pct"]}
           for sk in ("reading", "listening") for h in progress.receptive_history(conn, sk) if h["unit"] != "all"]
    if raw:
        st.line_chart(pd.DataFrame(raw).pivot_table(index="fecha", columns="habilidad", values="% aciertos", aggfunc="mean"))
        full = [{"Fecha": h["date"], "Habilidad": sk.capitalize(), "Test": h["test"], "Raw": f"{h['raw']}/{h['total']}",
                 "Banda (aprox.)": h["band"]}
                for sk in ("reading", "listening") for h in progress.receptive_history(conn, sk) if h["unit"] == "all"]
        if full:
            st.markdown("**Tests completos**")
            st.dataframe(full, hide_index=True, use_container_width=True)
    else:
        st.caption("Sin intentos todavía.")
with right:
    st.subheader("Top errores")
    week_ago = (now - timedelta(days=7)).isoformat()
    scope = st.radio("Periodo", ["Últimos 7 días", "Todo"], horizontal=True, key="err_scope")
    top = db.top_categories(conn, since=week_ago if scope.startswith("Últ") else None, limit=8)
    if top:
        st.bar_chart(pd.DataFrame(top, columns=["categoría", "errores"]).set_index("categoría"))
    else:
        st.caption("Sin errores registrados en este periodo.")

st.subheader("Nivel por habilidad (dificultad progresiva)")
st.dataframe([{"Habilidad": s, "Nivel (1-10)": db.get_level(conn, s)} for s in db.SKILLS], hide_index=True)

st.subheader("Auditorías semanales")
rows = audit.audits(conn)
if rows:
    st.line_chart(pd.DataFrame([{"semana": r["week"], "Energía": r["energy"], "Ansiedad": r["anxiety"]} for r in rows])
                  .set_index("semana"))
    st.dataframe([{"Semana": r["week"], "Dónde perdí puntos": r["where_lost"], "Por qué": r["why"],
                   "Objetivo": r["change_goal"]} for r in rows], hide_index=True, use_container_width=True)
else:
    st.caption("Aún no hay auditorías. Se hacen los domingos.")

st.subheader("Modelo de lenguaje")
llm = load_llm_config()
st.markdown(f"Proveedor activo: **{llm.provider}** · modelo **{llm.active_model}**")
if llm.provider == "openai":
    u = usage_summary(cfg=llm, tracker=DbUsage(conn))
    c1, c2, c3 = st.columns(3)
    c1.metric("Llamadas a la API", u["calls"])
    c2.metric("Tokens (entrada / salida)", f"{u['prompt_tokens']:,} / {u['completion_tokens']:,}")
    st.caption(f"Llamadas de hoy: {u['calls_today']}" + (f" de {llm.max_calls_per_day}" if llm.max_calls_per_day else ""))
    c3.metric("Gasto estimado", f"${u['cost_usd']:.3f}" if u["priced"] else "—",
              help="Estimación con los precios de config.toml; el saldo real está en tu cuenta de OpenAI.")
