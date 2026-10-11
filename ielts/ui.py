"""Utilidades compartidas por las páginas de Streamlit."""
from __future__ import annotations

import os
from datetime import date

import streamlit as st

from . import db
from .curriculum import Block, load_curriculum
from . import clock


def today() -> date:
    """Hoy en la zona horaria configurada (IELTS_TODAY=YYYY-MM-DD simula otra fecha)."""
    return clock.today()


@st.cache_resource
def get_conn():
    """Base de datos: SQLite local, o en modo cloud SQLite sincronizado con Google Cloud Storage."""
    from .config import load_app_config
    if load_app_config().is_cloud:
        from . import dbsync
        return dbsync.open_cloud_db()
    return db.connect()


@st.cache_resource
def get_provider():
    from .llm.client import get_provider as _get
    from .llm.usage import DbUsage
    provider = _get()
    if hasattr(provider, "usage"):               # OpenAI: el gasto se guarda en la base de datos
        provider.usage = DbUsage(get_conn())
    return provider


@st.cache_resource
def get_transcriber():
    from .llm.usage import DbUsage
    from .stt import make_transcriber
    return make_transcriber(usage=DbUsage(get_conn()))


def plan_for(weekday: str, phase: int, diagnostic: bool = False, week: int = 0) -> list[Block]:
    cur = load_curriculum()
    return cur.diagnostic_blocks() if diagnostic else cur.blocks_for(weekday, phase, week)


def fmt_mmss(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 60:02d}:{seconds % 60:02d}"


def audio_format(path) -> str:
    """Streamlit asume audio/wav por defecto; un MP3 servido así no se decodifica en el navegador."""
    return {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}.get(
        str(path)[str(path).rfind("."):].lower(), "audio/mpeg")


def audio_src(rel: str):
    """Qué le pasamos a st.audio: URL firmada (nube) o ruta local de resources/."""
    from .storage import resources_store
    store = resources_store()
    url = store.url(rel)
    if url:
        return url
    path = store.local_path(rel)
    return str(path) if path else rel


def page_setup(page_title: str, page_icon: str, layout: str = "wide") -> None:
    """set_page_config + control de acceso. Debe ser lo PRIMERO que ejecuta cada página."""
    st.set_page_config(page_title=page_title, page_icon=page_icon, layout=layout)
    from .auth import guard
    guard()
