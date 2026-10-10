"""Bloques de Speaking: Part 2 (tarjeta + 1 min + 2 min), Parts 1 y 3, y shadowing."""
from __future__ import annotations

import time

import streamlit as st

from ..curriculum import load_curriculum
from ..llm.base import LLMError
from ..llm.schemas import SpeakingEvaluation
from ..speaking_metrics import SpeakingMetrics
from ..ui import fmt_mmss, get_conn, get_provider, get_transcriber
from . import speaking as sp

PREP_SECONDS = 60


def render(block, ctx) -> bool:
    if block.id == "shadowing":
        return _render_shadowing(ctx)
    if block.id in ("speaking_p2", "dx_speaking"):
        return _render_part2(ctx)
    return _render_part13(ctx)


def _theme(ctx) -> str:
    return load_curriculum().week(max(ctx["week"], 1)).vocab


def _show_metrics(m: dict) -> None:
    c = st.columns(4)
    c[0].metric("Palabras/min", f"{m['wpm']:.0f}", help="Objetivo orientativo: 110-160 wpm")
    c[1].metric("Pausas > 1.5 s", len(m["pauses"]))
    c[2].metric("Muletillas", sum(m["fillers"].values()))
    c[3].metric("Diversidad léxica", f"{m['mattr']:.2f}", help="MATTR (0-1): más alto = más variado")
    if m["fillers"]:
        st.caption("Muletillas: " + ", ".join(f"{k} ×{v}" for k, v in m["fillers"].items()))
    if m["repeated"]:
        st.caption("Palabras muy repetidas: " + ", ".join(f"{w} ×{n}" for w, n in m["repeated"]) +
                   " → busca sinónimos.")
    if m["pauses"]:
        st.caption("Pausas largas tras: " + ", ".join(f"«{p['after']}» ({p['seconds']} s)" for p in m["pauses"][:6]))


def _show_evaluation(ev: SpeakingEvaluation) -> None:
    st.subheader(f"Feedback · {sp.BANNER}")
    c = st.columns(4)
    for col, (label, crit) in zip(c, [("FC", ev.fc), ("LR", ev.lr), ("GRA", ev.gra)]):
        col.metric(label, crit.banda, help=crit.justificacion_es)
    c[3].metric("Promedio FC/LR/GRA", sp.overall_speaking(ev))
    for label, crit in [("Fluency & Coherence", ev.fc), ("Lexical Resource", ev.lr), ("Grammar", ev.gra)]:
        st.markdown(f"- **{label} {crit.banda}:** {crit.justificacion_es}")
    st.info(f"**Pronunciación (observación aproximada, sin banda):** {ev.pronunciacion_es}")
    with st.expander(f"Errores ({len(ev.errores)})", expanded=True):
        for e in ev.errores:
            st.markdown(f"- ❌ *{e.fragmento}* → ✅ **{e.correccion}** `{e.categoria.value}` — {e.explicacion_es}")
    for t in ev.consejos_es:
        st.markdown(f"💡 {t}")
    with st.expander("Versión mejorada de tu respuesta"):
        st.write(ev.respuesta_mejorada_en)


def _analyze_and_evaluate(s: dict, ctx, part: str, prompt: str, audios: list[bytes], key: str) -> None:
    conn = get_conn()
    try:
        with st.spinner("Transcribiendo (la primera vez descarga y carga el modelo Whisper)…"):
            transcripts, metrics = sp.analyze(get_transcriber(), audios)
    except Exception as e:  # noqa: BLE001 — cualquier fallo del STT se muestra sin tumbar la página
        st.error(f"No se pudo transcribir el audio: {e}")
        return
    text = "\n\n".join(t.text for t in transcripts)
    if not text.strip():
        st.warning("No se detectó voz en la grabación. Revisa el micrófono e inténtalo de nuevo.")
        return
    audio_path = sp.save_recording(audios[0], ctx["week"], part) if len(audios) == 1 else None
    ev = None
    try:
        with st.spinner("El modelo local está evaluando…"):
            ev = sp.evaluate_speaking(get_provider(), part, prompt, text, metrics)
    except LLMError as e:
        st.warning(f"Tienes la transcripción y las métricas, pero falló el feedback del LLM: {e}")
    import dataclasses
    sid = sp.save_session(conn, ctx["week"], part, prompt, text, metrics, ev, audio_path)
    s.update(done=True, transcript=text, metrics=dataclasses.asdict(metrics), sid=sid,
             evaluation=ev.model_dump() if ev else None)
    st.rerun()


def _show_done(s: dict) -> None:
    st.markdown("#### Transcripción")
    st.write(s["transcript"])
    _show_metrics(s["metrics"])
    if s.get("evaluation"):
        _show_evaluation(SpeakingEvaluation.model_validate(s["evaluation"]))


# ---- Part 2 ----
def _render_part2(ctx) -> bool:
    key = f"sp2_{ctx['week']}_{ctx['weekday']}"
    s = st.session_state.setdefault(key, {})
    if "card" not in s:
        s["theme"], s["card"] = sp.part2_card(_theme(ctx))
    card = s["card"]
    st.markdown(f"### Part 2 · {s['theme']}")
    st.info(sp.card_text(card))
    st.caption("Tienes 1 minuto para preparar y luego hablas ~2 minutos. Estructura: introducción → puntos de la tarjeta → cierre.")

    if s.get("done"):
        _show_done(s)
        return True

    if "prep_start" not in s:
        if st.button("▶ Empezar preparación (1 min)", key=f"{key}_prep", type="primary"):
            s["prep_start"] = time.time()
            st.rerun()
        return True

    @st.fragment(run_every=1)
    def prep_timer():
        left = PREP_SECONDS - int(time.time() - s["prep_start"])
        if left > 0:
            st.metric("Preparación", fmt_mmss(left))
        else:
            st.success("Se acabó la preparación. ¡Graba tu respuesta!")

    prep_timer()
    audio = st.audio_input("Graba tu respuesta (~2 min)", key=f"{key}_audio")
    if audio is not None:
        st.audio(audio)
        if st.button("Analizar mi respuesta", key=f"{key}_go", type="primary"):
            _analyze_and_evaluate(s, ctx, "p2", sp.card_text(card), [audio.getvalue()], key)
    return True


# ---- Parts 1 y 3 ----
def _render_part13(ctx) -> bool:
    key = f"sp13_{ctx['week']}_{ctx['weekday']}"
    s = st.session_state.setdefault(key, {})
    if "questions" not in s:
        s["questions"] = sp.part13_questions(_theme(ctx))
    st.caption("Estructura de cada respuesta: **respuesta → razón → ejemplo** (Part 1: 2-3 frases; Part 3: más desarrollo).")
    if s.get("done"):
        for part, q in s["questions"]:
            st.markdown(f"- **{part}:** {q}")
        _show_done(s)
        return True

    audios, labelled = [], []
    for i, (part, q) in enumerate(s["questions"]):
        st.markdown(f"**{part} · {q}**")
        a = st.audio_input("Tu respuesta", key=f"{key}_a{i}", label_visibility="collapsed")
        if a is not None:
            audios.append(a.getvalue())
            labelled.append(f"[{part}] {q}")
    st.caption(f"{len(audios)}/{len(s['questions'])} respuestas grabadas")
    if audios and st.button("Analizar mis respuestas", key=f"{key}_go", type="primary"):
        _analyze_and_evaluate(s, ctx, "p13", "\n".join(labelled), audios, key)
    return True


# ---- Shadowing ----
def _render_shadowing(ctx) -> bool:
    key = f"shadow_{ctx['week']}_{ctx['weekday']}"
    s = st.session_state.setdefault(key, {})
    files = sp.list_shadowing_audios()
    if not files:
        st.warning("No encontré audios de Cambridge en resources/. Añádelos para practicar shadowing.")
        return True
    names = [str(f.relative_to(sp.RESOURCES_DIR)) for f in files]
    default = next((i for i, n in enumerate(names) if "T1 AUDIO 4" in n), 0)
    choice = st.selectbox("Audio", names, index=default, key=f"{key}_file")
    path = sp.RESOURCES_DIR / choice
    c1, c2 = st.columns(2)
    start = c1.number_input("Inicio (s)", min_value=0, value=0, step=5, key=f"{key}_start")
    length = c2.slider("Duración del fragmento (s)", 10, 40, 20, key=f"{key}_len")
    st.audio(str(path), start_time=int(start), end_time=int(start + length))
    st.caption("1) Escucha. 2) Pulsa «Preparar referencia». 3) Escucha otra vez repitiendo en voz alta justo después de cada frase "
               "(shadowing). 4) Graba tu versión.")

    if st.button("Preparar referencia (transcribe el fragmento)", key=f"{key}_ref"):
        try:
            with st.spinner("Transcribiendo el fragmento…"):
                s["ref"] = get_transcriber().transcribe(path, start=float(start), end=float(start + length)).text
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo transcribir: {e}")
    if s.get("ref"):
        with st.expander("Texto de referencia"):
            st.write(s["ref"])
        audio = st.audio_input("Graba tu shadowing", key=f"{key}_audio")
        if audio is not None and st.button("Comparar", key=f"{key}_cmp", type="primary"):
            mine = get_transcriber().transcribe(audio.getvalue())
            s["cmp"] = {**sp.shadowing_compare(s["ref"], mine.text), "mine": mine.text}
        if s.get("cmp"):
            r = s["cmp"]
            st.metric("Similitud con la referencia", f"{r['similarity'] * 100:.0f}%")
            st.markdown(f"**Tu transcripción:** {r['mine']}")
            if r["missing"]:
                st.markdown("**Palabras que faltaron:** " + ", ".join(r["missing"]))
            if r["weak_forms_missing"]:
                st.info("Formas débiles omitidas (en inglés se reducen pero no desaparecen): "
                        + ", ".join(sorted(set(r["weak_forms_missing"]))))
            if r["extra"]:
                st.markdown("**Palabras añadidas/distintas:** " + ", ".join(r["extra"]))
    return True
