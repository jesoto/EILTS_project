"""Bloque de SRS (Anki): repaso SM-2, tarjetas desde errores y semillas del tema semanal."""
from __future__ import annotations

import json
import streamlit as st

from .. import srs
from ..curriculum import load_curriculum
from ..llm.base import LLMError
from ..ui import get_conn, get_provider, today

SOURCE_LABEL = {"weekly": "Tema de la semana", "collocation": "Colocaciones C1", "false_friend": "Falsos amigos",
                "awl": "AWL (fase actual)"}


def _fill_pending(conn) -> None:
    """Completa con el LLM solo las tarjetas necesarias (hasta tener NEW_PER_DAY nuevas listas).

    Si falla, el repaso sigue con las que ya están listas.
    """
    if not srs.pending_cards(conn, 1) or srs.unseen_ready(conn) >= srs.NEW_PER_DAY:
        return
    try:
        with st.spinner("Preparando tarjetas nuevas con el modelo local…"):
            while srs.pending_cards(conn, 1) and srs.unseen_ready(conn) < srs.NEW_PER_DAY:
                if srs.fill_pending(get_provider(), conn) == 0:
                    break
    except LLMError as e:
        st.warning(f"No se pudieron completar algunas tarjetas ahora ({e}). Se reintentará más tarde.")


def render(block, ctx) -> bool:
    conn, now = get_conn(), today()
    key = f"srs_{now.isoformat()}"
    s = st.session_state.setdefault(key, {"filled": False, "reveal": False, "reviewed": 0})
    if not s["filled"]:
        _fill_pending(conn)
        s["filled"] = True

    cur = load_curriculum()
    week_theme = cur.week(max(ctx["week"], 1)).vocab
    stt = srs.stats(conn, now)
    a, b, c = st.columns(3)
    a.metric("Por repasar hoy", stt["due"])
    b.metric("Tarjetas listas", stt["total"])
    c.metric("Repasadas en esta sesión", s["reviewed"])

    with st.expander("➕ Añadir tarjetas"):
        st.caption(f"Tema de la semana: **{week_theme}**. Los errores de colocación, falsos amigos, forma de palabra "
                   "y ortografía de tu error log se convierten en tarjetas automáticamente.")
        sources = srs.seed_words_for(week_theme, ctx["phase"])
        for src, words in sources.items():
            if st.button(f"{SOURCE_LABEL.get(src, src)} ({len(words)})", key=f"{key}_add_{src}"):
                n = srs.add_pending(conn, words, src, week_theme, now)
                st.toast(f"{n} tarjetas nuevas en cola")
                s["filled"] = False
                st.rerun()

    due = srs.due_cards(conn, now)
    if not due:
        st.success("🎉 No quedan tarjetas por repasar hoy." if stt["total"] else
                   "Aún no tienes tarjetas. Añade el tema de la semana en el panel de arriba.")
        return True

    card = due[0]
    family = json.loads(card["family"] or "{}")
    colls = json.loads(card["collocations"] or "[]")
    st.markdown(f"### {card['word']}")
    if card["source"] == "error_log" and card["context"]:
        st.caption(f"De tu error log: {card['context']}")
    sentence = st.text_input("Escribe tu propia oración con esta palabra/chunk",
                             value=card["user_sentence"], key=f"{key}_sent_{card['id']}")
    if not s["reveal"]:
        if st.button("Mostrar respuesta", key=f"{key}_show", type="primary"):
            s["reveal"] = True
            st.rerun()
        return True

    fam = " · ".join(f"**{k}:** {v}" for k, v in family.items() if v)
    st.markdown(f"{card['definition_es']}\n\n{fam}\n\n**Colocaciones:** " + "; ".join(colls))
    st.markdown(f"*{card['example_en']}*")
    if card["note_es"]:
        st.warning(card["note_es"])
    cols = st.columns(len(srs.RATINGS))
    for col, (label, q) in zip(cols, srs.RATINGS.items()):
        if col.button(label, key=f"{key}_rate_{card['id']}_{q}", use_container_width=True):
            srs.review_card(conn, card["id"], q, now, sentence)
            s["reveal"], s["reviewed"] = False, s["reviewed"] + 1
            st.rerun()
    return True
