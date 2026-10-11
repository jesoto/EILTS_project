"""Vocabulario (SRS) fuera del flujo de sesión."""
import streamlit as st

from ielts.calendar import effective_week
from ielts.curriculum import load_curriculum
from ielts.modules import ui_vocab
from ielts.ui import page_setup, today

page_setup("Vocabulario · IELTS Trainer", "🃏")
st.title("🃏 Vocabulario (SRS)")
cur, now = load_curriculum(), today()
week = effective_week(now, cur)
ui_vocab.render(None, {"week": week, "phase": cur.phase_of_week(week).id})
