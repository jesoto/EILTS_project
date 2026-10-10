"""Enlaza `block.module` con su renderer. Devuelve True si se puede avanzar al siguiente bloque."""
from __future__ import annotations

import streamlit as st


def render_block(block, ctx) -> bool:
    if block.module == "grammar":
        from . import ui_grammar
        return ui_grammar.render(block, ctx)
    if block.module == "writing":
        from . import ui_writing
        return ui_writing.render(block, ctx)
    if block.module in ("reading", "listening", "errorlog", "simulacro"):
        from . import ui_receptive
        return ui_receptive.render(block, ctx)
    if block.module == "audit":
        from . import ui_audit
        return ui_audit.render(block, ctx)
    if block.module == "export":
        from . import ui_export
        return ui_export.render(block, ctx)
    if block.module == "speaking":
        from . import ui_speaking
        return ui_speaking.render(block, ctx)
    if block.module == "vocab":
        from . import ui_vocab
        return ui_vocab.render(block, ctx)
    st.caption(f"Módulo `{block.module}` — el contenido interactivo llega en hitos posteriores.")
    return True
