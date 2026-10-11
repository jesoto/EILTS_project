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
    return db.connect()


@st.cache_resource
def get_provider():
    from .llm.client import get_provider as _get
    return _get()


@st.cache_resource
def get_transcriber():
    from .stt import FasterWhisperTranscriber
    return FasterWhisperTranscriber()


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
