"""Error log: tabla filtrable + export."""
from datetime import timedelta

import streamlit as st

from ielts import db
from ielts.modules import errorlog as el
from ielts.ui import get_conn, today

st.set_page_config(page_title="Error log · IELTS Trainer", page_icon="📝", layout="wide")
st.title("📝 Error log")
conn = get_conn()

if not el.distinct_values(conn, "category"):
    st.info("Aún no hay errores registrados. Aparecerán aquí cuando evalúes Writing o hagas ejercicios de gramática.")
    st.stop()

week_ago = (today() - timedelta(days=7)).isoformat()
st.subheader("Top 3 categorías de la última semana")
top = db.top_categories(conn, since=week_ago)
if top:
    cols = st.columns(len(top))
    for col, (cat, n) in zip(cols, top):
        col.metric(cat, n)
else:
    st.caption("Sin errores en los últimos 7 días.")

st.subheader("Filtros")
c1, c2, c3, c4 = st.columns(4)
modules = c1.multiselect("Módulo", el.distinct_values(conn, "module"))
cats = c2.multiselect("Categoría", el.distinct_values(conn, "category"))
min_count = c3.number_input("Veces (mín.)", min_value=1, value=1)
text = c4.text_input("Buscar texto")
rows = el.query_errors(conn, modules=modules, categories=cats, min_count=int(min_count), text=text)

st.caption(f"{len(rows)} errores")
st.dataframe(rows, use_container_width=True, hide_index=True, column_config={
    "date": "Fecha", "module": "Módulo", "fragment": "Fragmento", "correction": "Corrección",
    "category": "Categoría", "explanation": "Explicación", "count": "Veces"})

d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("⬇ CSV", el.to_csv(rows), "error_log.csv", "text/csv")
d2.download_button("⬇ Markdown", el.to_markdown(rows), "error_log.md", "text/markdown")
