"""Exports para la profesora: martes (ensayo + feedback) y jueves (dudas + monólogo)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from .. import audit, export
from ..ui import get_conn, today


def render(block, ctx) -> bool:
    return _teacher_prep(ctx) if block.id == "teacher_prep" else _doubts(ctx)


def _teacher_prep(ctx) -> bool:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM writing_submission ORDER BY id DESC LIMIT 6").fetchall()
    if not rows:
        st.info("Todavía no tienes ensayos evaluados. Haz el bloque de Writing del lunes y vuelve aquí.")
        return True
    label = lambda r: f"{r['date'][:10]} · {r['task'].upper()} · {r['task_type']} · {r['prompt'][:60]}…"  # noqa: E731
    idx = st.selectbox("Ensayo a exportar", range(len(rows)), format_func=lambda i: label(rows[i]), key="exp_essay")
    sub = rows[idx]
    md = export.teacher_essay_markdown(sub)
    with st.expander("Vista previa", expanded=True):
        st.markdown(md)
    c1, c2, _ = st.columns([1, 1, 2])
    c1.download_button("⬇ Markdown", md, f"ensayo_{sub['date'][:10]}.md", "text/markdown", key="exp_md")
    c2.download_button("⬇ PDF", export.html_to_pdf(export.teacher_essay_html(sub)), f"ensayo_{sub['date'][:10]}.pdf",
                       "application/pdf", key="exp_pdf")
    return True


def _doubts(ctx) -> bool:
    conn, week = get_conn(), max(ctx["week"], 1)
    st.markdown("#### Dudas para la profesora")
    suggestions = audit.suggest_doubts(conn)
    if suggestions:
        st.caption("Sugeridas desde tu error log (los errores que más se repiten):")
        for i, sug in enumerate(suggestions):
            if st.checkbox(sug, key=f"dsug_{week}_{i}"):
                audit.add_doubt(conn, week, sug, "error_log", today())
    new = st.text_input("Añade una duda propia", key=f"dnew_{week}", placeholder="Ej.: ¿cuándo uso 'the' con 'government'?")
    if st.button("Añadir duda", key=f"dadd_{week}") and new.strip():
        audit.add_doubt(conn, week, new, "manual", today())
        st.rerun()
    doubts = audit.list_doubts(conn, week)
    for d in doubts:
        a, b = st.columns([12, 1])
        a.markdown(f"- {d['text']}")
        if b.button("✕", key=f"ddel_{d['id']}"):
            audit.delete_doubt(conn, d["id"])
            st.rerun()

    from . import speaking as sp
    session = sp.latest_session(conn, "p2")
    texts = [d["text"] for d in doubts]
    md = export.doubts_markdown(week, texts, session)
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Markdown", md, f"dudas_semana{week}.md", "text/markdown", key="dx_md")
    c2.download_button("⬇ PDF", export.html_to_pdf(export.doubts_html(week, texts, session)), f"dudas_semana{week}.pdf",
                       "application/pdf", key="dx_pdf")
    wav = _recording(session)
    if wav is not None:
        c3.download_button("⬇ Grabación (wav)", wav[1], wav[0], "audio/wav", key="dx_wav")
    elif session is None:
        st.caption("Aún no hay monólogo de Speaking: grábalo en el bloque anterior para incluir la transcripción.")
    return True


def _recording(session):
    """(nombre, bytes) de la grabación del monólogo, o None si no existe (sirve también con rutas antiguas absolutas)."""
    if session is None or not session["audio_path"]:
        return None
    from ..storage import recordings_store
    name = Path(str(session["audio_path"]).replace("\\", "/")).name
    try:
        return name, recordings_store().read_bytes(name)
    except FileNotFoundError:
        return None
