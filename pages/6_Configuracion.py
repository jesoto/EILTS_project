"""Configuración: diagnóstico de qué falta (clave, modelo, libros, almacenamiento, acceso) y estado de la sincronización."""
from datetime import datetime

import streamlit as st

from ielts import doctor
from ielts.config import load_app_config
from ielts.ui import get_conn, page_setup

page_setup("Configuración · IELTS Trainer", "⚙️")
st.title("⚙️ Configuración")
st.caption("Comprueba que todo está listo. Nunca se muestran tus claves, solo si existen.")

ICON = {doctor.OK: "✅", doctor.WARN: "⚠️", doctor.FAIL: "❌"}


def show(checks):
    for c in checks:
        st.markdown(f"{ICON[c.status]} **{c.title}**" + (f"  \n<small>{c.detail}</small>" if c.detail else ""),
                    unsafe_allow_html=False)
        if c.fix and c.status != doctor.OK:
            st.caption(f"→ {c.fix}")


checks = doctor.run_checks()
bad = [c for c in checks if c.status == doctor.FAIL]
(st.error if bad else st.success)(f"{len(bad)} problema(s) crítico(s)." if bad else "Todo lo esencial está en orden.")
show(checks)

st.subheader("Comprobaciones con red")
st.caption("Llamadas gratuitas: lista de modelos de OpenAI, servidor de Ollama y/o bucket de Google Cloud.")
if st.button("Probar conexiones"):
    with st.spinner("Probando…"):
        show(doctor.run_live_checks())

if load_app_config().is_cloud:
    st.subheader("Sincronización de la base de datos")
    conn = get_conn()
    status = conn.status() if hasattr(conn, "status") else None
    if status:
        last = datetime.fromtimestamp(status["last_upload"]).strftime("%H:%M:%S") if status["last_upload"] else "—"
        c1, c2, c3 = st.columns(3)
        c1.metric("Pendiente de subir", "sí" if status["dirty"] else "no")
        c2.metric("Última subida", last)
        c3.metric("Conflicto", "SÍ" if status["conflict"] else "no")
        if status["error"]:
            st.warning(f"Último error: {status['error']}")
        if status["conflict"]:
            st.error("Otra instancia escribió la base de datos antes que esta. Elige qué versión conservar:")
            a, b = st.columns(2)
            if a.button("Conservar lo de esta sesión (sobrescribe la nube)"):
                conn.force_upload()
                st.rerun()
            if b.button("Descartar lo local y recargar la nube"):
                from ielts.dbsync import reload_from_store
                reload_from_store(conn)
                st.rerun()
        elif st.button("Subir ahora"):
            conn.flush()
            st.rerun()

with st.expander("Variables definidas (solo nombres)"):
    st.table([{"Variable": k, "Definida": "sí" if v else "no"} for k, v in doctor.env_summary().items()])
