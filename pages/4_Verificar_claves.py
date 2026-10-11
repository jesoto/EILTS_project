"""Verificación humana de las claves extraídas (obligatoria antes de usar un test)."""
import streamlit as st

from ielts.ingest import review
from ielts.ingest.schema import list_tests, save_test
from ielts.ui import audio_format, audio_src

st.set_page_config(page_title="Verificar claves · IELTS Trainer", page_icon="🔑", layout="wide")
st.title("🔑 Verificar claves")
st.caption("Una clave mal leída arruina la evaluación. Compara cada tabla con la imagen del PDF y corrige lo necesario. "
           "Solo los tests marcados como verificados se usan en Reading y Listening.")

def _rows(x) -> list[dict]:
    """data_editor devuelve lista de dicts o DataFrame según la versión/entrada."""
    return x.to_dict("records") if hasattr(x, "to_dict") else list(x)


tests = list_tests()
if not tests:
    st.info("No hay tests ingeridos todavía. Ejecuta en la terminal:  `uv run python scripts/ingest.py`")
    st.stop()

labels = {t.test_id: f"{'✅' if t.verified else '⚠️'} {t.book_title} · Test {t.test}" for t in tests}
tid = st.selectbox("Test", list(labels), format_func=labels.get)
td = next(t for t in tests if t.test_id == tid)

notes = review.check(td)
if notes:
    with st.expander(f"⚠️ {len(notes)} avisos automáticos", expanded=True):
        for n in notes:
            st.markdown(f"- {n}")
else:
    st.success("Sin avisos automáticos. Aun así, compara con el PDF.")

key_images = review.key_page_images(td)
tab_l, tab_r, tab_q, tab_a, tab_w = st.tabs(["Listening", "Reading", "Tipos de pregunta", "Audios", "Writing"])
edited: dict[str, list[dict]] = {}
for tab, skill in ((tab_l, "listening"), (tab_r, "reading")):
    with tab:
        left, right = st.columns([1, 1])
        with left:
            rows = review.key_rows(td, skill)
            edited[skill] = st.data_editor(
                rows, key=f"ed_{tid}_{skill}", hide_index=True, use_container_width=True, num_rows="fixed",
                height=min(900, 36 * (len(rows) + 1)),
                column_config={"q": st.column_config.NumberColumn("Pregunta", disabled=True),
                               "answer": st.column_config.TextColumn("Respuesta(s) aceptada(s), separadas por |"),
                               "any_order": st.column_config.CheckboxColumn("Cualquier orden (pareja)")})
        with right:
            if key_images:
                for key, png in key_images:
                    st.image(png, caption=f"PDF · {key.rsplit('/', 1)[-1]}")
            else:
                st.caption("No hay imágenes de la clave: vuelve a ejecutar `scripts/ingest.py` con el PDF en resources/.")

with tab_q:
    st.caption("Cómo se contesta cada grupo de preguntas en la app (texto libre, lista de opciones…).")
    for skill, units in (("listening", td.listening), ("reading", td.reading)):
        for u in units:
            for g in u.groups:
                st.markdown(f"**{skill} · {'Parte' if skill == 'listening' else 'Pasaje'} "
                            f"{getattr(u, 'part', getattr(u, 'n', ''))} · P{g.start}–{g.end}** — tipo `{g.type}`, "
                            f"entrada `{g.input}`" + (f", opciones {', '.join(g.options)}" if g.options else ""))

with tab_a:
    opts = ["(sin audio)"] + review.candidate_audios(td)
    for p in td.listening:
        cur = p.audio or "(sin audio)"
        idx = opts.index(cur) if cur in opts else 0
        choice = st.selectbox(f"Parte {p.part}", opts, index=idx, key=f"au_{tid}_{p.part}")
        p.audio = None if choice == "(sin audio)" else choice
        if p.audio:
            st.audio(audio_src(p.audio), format=audio_format(p.audio))
        else:
            st.warning(f"La Parte {p.part} no tiene audio: no se podrá practicar esa parte.")

with tab_w:
    for w in td.writing:
        st.markdown(f"**Task {w.task}** · tipo `{w.task_type}`")
        st.write(w.prompt)

st.divider()
c1, c2, c3 = st.columns(3)
if c1.button("💾 Guardar cambios (sin verificar)"):
    for skill, key_attr in (("listening", "key_listening"), ("reading", "key_reading")):
        setattr(td, key_attr, review.rows_to_key(_rows(edited[skill])))
    td.verified, td.verified_at = False, None
    save_test(td)
    st.success("Guardado. El test sigue pendiente de verificación.")
confirm = c2.checkbox("He comparado las claves de Listening y Reading con el PDF")
if c3.button("✅ Marcar como verificado", type="primary", disabled=not confirm):
    for skill, key_attr in (("listening", "key_listening"), ("reading", "key_reading")):
        setattr(td, key_attr, review.rows_to_key(_rows(edited[skill])))
    td.mark_verified()
    save_test(td)
    st.success("Test verificado: ya está disponible para practicar.")
    st.rerun()
if td.verified:
    st.caption(f"Verificado el {td.verified_at}.")
