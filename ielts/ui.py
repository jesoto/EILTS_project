"""Utilidades compartidas por las páginas de Streamlit."""
from __future__ import annotations

import os
from datetime import date

import streamlit as st

from . import db
from .curriculum import Block, load_curriculum


def today() -> date:
    """Hoy; IELTS_TODAY=YYYY-MM-DD permite simular otra fecha al probar."""
    override = os.environ.get("IELTS_TODAY")
    return date.fromisoformat(override) if override else date.today()


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


def plan_for(weekday: str, phase: int, diagnostic: bool = False) -> list[Block]:
    cur = load_curriculum()
    return cur.diagnostic_blocks() if diagnostic else cur.blocks_for(weekday, phase)


def fmt_mmss(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    return f"{sign}{seconds // 60:02d}:{seconds % 60:02d}"
