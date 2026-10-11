"""Bloques de Reading y Listening (corrección con clave, causa de cada error, dictado, velocidad)."""
from __future__ import annotations

import time

import streamlit as st
import streamlit.components.v1 as components

from ..curriculum import load_curriculum
from ..ingest.schema import Group, TestData
from ..storage import resources_store
from ..ui import audio_format, audio_src, get_conn, get_transcriber
from . import dictation
from . import receptive as rc

MODE = {"reading": "one", "reading_sections": "sections", "reading_full": "full", "sim_reading": "full",
        "dx_reading": "full", "listening": "one", "listening_sections": "sections", "listening_full": "full",
        "dx_listening": "full"}
SLOW_Q_SECONDS = 90
BLANK = "—"


def render(block, ctx) -> bool:
    if block.id in ("error_analysis", "review"):
        return _render_review(block, ctx)
    if block.id in ("sim_full", "checkpoint"):
        return _render_simulacro(ctx)
    skill = "reading" if block.module == "reading" else "listening"
    return _run(skill, MODE.get(block.id, "one"), block, ctx, f"{block.id}")


def _render_simulacro(ctx) -> bool:
    from . import ui_writing
    tl, tr, tw = st.tabs(["1 · Listening", "2 · Reading", "3 · Writing"])
    with tl:
        _run("listening", "full", None, ctx, "sim_l")
    with tr:
        _run("reading", "full", None, ctx, "sim_r")
    with tw:
        class _B:
            id, module = "sim_writing", "writing"
        ui_writing.render(_B(), ctx)
    return True


# ------------------------------------------------------------------ selección del plan
def _plan(skill: str, mode: str, ctx, tests: list[TestData], conn) -> list[tuple[rc.Unit, list[Group]]]:
    units = rc.all_units(skill, tests)
    cur = load_curriculum()
    foc = cur.receptive(ctx["week"]) if ctx["phase"] == 1 else None
    types = foc.reading_types if (foc and skill == "reading") else None
    part = foc.listening_part if (foc and skill == "listening") else None
    if mode == "one":
        u = rc.pick_unit(conn, skill, units, types=types, part=part)
        return [(u, u.groups)] if u else []
    if mode == "sections":
        chosen: list[rc.Unit] = []
        pool = list(units)
        for _ in range(3 if skill == "reading" else 2):
            u = rc.pick_unit(conn, skill, pool, types=types, part=part)
            if not u:
                break
            chosen.append(u)
            pool = [x for x in pool if (x.td.test_id, x.key) != (u.td.test_id, u.key)]
        wanted = set(types or [])
        return [(u, [g for g in u.groups if not wanted or g.type in wanted]) for u in chosen]
    # full: el test completo menos practicado (para Listening, preferir los que tienen los 4 audios)
    by_test: dict[str, list[rc.Unit]] = {}
    for u in units:
        by_test.setdefault(u.td.test_id, []).append(u)
    counts = {r["test_id"]: r["n"] for r in conn.execute(
        "SELECT test_id, COUNT(*) n FROM receptive_attempt WHERE skill=? AND unit='all' GROUP BY test_id", (skill,))}

    def complete(us):
        return len(us) == (4 if skill == "listening" else 3) and all(
            (skill == "reading") or u.td.listening[u.n - 1].audio for u in us)
    order = sorted(by_test.items(), key=lambda kv: (not complete(kv[1]), counts.get(kv[0], 0), kv[0]))
    if not order:
        return []
    best = sorted(order[0][1], key=lambda u: u.n)
    return [(u, u.groups) for u in best]


# ------------------------------------------------------------------ componentes
def audio_with_speed(rel: str, speed: float, key: str) -> None:
    """st.audio no tiene control de velocidad: se aplica playbackRate al <audio> desde un iframe del mismo origen."""
    st.audio(audio_src(rel), format=audio_format(rel))
    components.html(
        f"<script>const s=()=>{{window.parent.document.querySelectorAll('audio').forEach("
        f"a=>{{if(!a.closest('[data-testid=stExpander]')){{a.playbackRate={speed};a.preservesPitch=true;}}}});}};s();setInterval(s,800);</script>", height=0)


def _touch(key: str) -> None:
    st.session_state[f"{key}_last"] = time.time()


def _answer_widget(g: Group, q: int, key: str) -> str:
    wk = f"{key}_ans_{q}"
    if g.input == "text":
        return st.text_input(f"Respuesta {q}", key=wk, on_change=_touch, args=(key,))
    v = st.selectbox(f"Respuesta {q}", [BLANK] + g.options, key=wk, on_change=_touch, args=(key,))
    return "" if v == BLANK else v


def _group_block(g: Group, key: str, td_id: str) -> dict[int, str]:
    st.markdown(f"**Preguntas {g.start}–{g.end}** · _{g.type}_")
    st.markdown("  \n".join(g.text.split("\n")))
    answers: dict[int, str] = {}
    cols = st.columns(min(5, len(g.qnums)) or 1)
    for i, q in enumerate(g.qnums):
        with cols[i % len(cols)]:
            answers[q] = _answer_widget(g, q, f"{key}_{td_id}")
    return answers


def _slow_warning(key: str, done: bool) -> None:
    @st.fragment(run_every=5)
    def _w():
        last = st.session_state.get(f"{key}_last", st.session_state.get(f"{key}_start", time.time()))
        if not done and time.time() - last > SLOW_Q_SECONDS:
            st.warning(f"⏱ Llevas más de {SLOW_Q_SECONDS} s sin responder. Si estás atascado, marca una respuesta y pasa a la siguiente.")
    _w()


# ------------------------------------------------------------------ ejecución de un bloque
def _run(skill: str, mode: str, block, ctx, key0: str) -> bool:
    conn = get_conn()
    key = f"rc_{ctx['week']}_{ctx['weekday']}_{key0}"
    tests = rc.verified_tests()
    if not tests:
        st.warning("Todavía no hay tests **verificados**. Ejecuta `uv run python scripts/ingest.py` y revisa las claves "
                   "en la página «Verificar claves» antes de practicar (una clave mal leída arruina la evaluación).")
        st.page_link("pages/4_Verificar_claves.py", label="Ir a Verificar claves →")
        return True
    s = st.session_state.setdefault(key, {})
    if "plan" not in s:
        plan = _plan(skill, mode, ctx, tests, conn)
        s["plan"] = [(u.td.test_id, u.key, [(g.start, g.end) for g in groups]) for u, groups in plan]
        s["start"] = time.time()
        st.session_state[f"{key}_start"] = s["start"]
    by_id = {(u.td.test_id, u.key): u for u in rc.all_units(skill, tests)}
    plan = []
    for tid, ukey, ranges in s["plan"]:
        u = by_id.get((tid, ukey))
        if u:
            plan.append((u, [g for g in u.groups if (g.start, g.end) in {tuple(r) for r in ranges}]))
    if not plan:
        st.info("No hay material verificado que encaje con este bloque (p. ej. falta el audio o el tipo de pregunta).")
        return True

    done = bool(s.get("results"))
    speed_default = load_curriculum().week(max(ctx["week"], 1)).listening_speed
    speed = 1.0
    if skill == "listening":
        speed = float(st.radio("Velocidad", ["1.0x", "1.25x"], index=1 if speed_default >= 1.25 else 0,
                               horizontal=True, key=f"{key}_speed").rstrip("x"))
        st.caption("En el examen el audio suena **una sola vez**: intenta no retroceder.")
    else:
        _slow_warning(key, done)
        st.caption("Máx. 20 min por pasaje. Si una pregunta te atasca más de 90 s, marca y sigue.")

    answers: dict[tuple[str, int], str] = {}
    for u, groups in plan:
        st.markdown(f"## {u.label}")
        if skill == "reading":
            rp = u.td.reading[u.n - 1]
            left, right = st.columns([1, 1])
            with left:
                with st.container(height=640):
                    st.markdown(f"### {rp.title}")
                    st.markdown(rp.text.replace("\n\n", "\n\n"))
            with right:
                with st.container(height=640):
                    for g in groups:
                        for q, v in _group_block(g, key, u.td.test_id).items():
                            answers[(u.td.test_id, q)] = v
        else:
            lp = u.td.listening[u.n - 1]
            audio_with_speed(lp.audio, speed, key)
            for g in groups:
                for q, v in _group_block(g, key, u.td.test_id).items():
                    answers[(u.td.test_id, q)] = v
            if block is not None and block.id == "listening":
                _dictation(u, key, ctx)

    if not done:
        if st.button("Corregir ✔", key=f"{key}_submit", type="primary"):
            _grade_and_store(skill, plan, answers, s, conn, ctx, mode)
            st.rerun()
    else:
        _show_results(skill, s, plan, conn)
    return True


def _grade_and_store(skill, plan, answers, s, conn, ctx, mode) -> None:
    secs = int(time.time() - s["start"])
    s["results"] = []
    all_results: list[rc.QResult] = []
    for u, groups in plan:
        qn = [q for g in groups for q in g.qnums]
        qtype_of = {q: g.type for g in groups for q in g.qnums}
        res = rc.grade(u.td, skill, {q: answers.get((u.td.test_id, q), "") for q in qn}, qn, qtype_of)
        aid = rc.record_attempt(conn, week=ctx["week"], skill=skill, td=u.td, unit=u.key, results=res,
                                qtype=",".join(sorted({g.type for g in groups})), seconds=secs)
        all_results += res
        s["results"].append({"unit": u.key, "label": u.label, "aid": aid, "test_id": u.td.test_id,
                             "res": [r.__dict__ for r in res]})
    if mode == "full" and len(all_results) == 40:
        s["band"] = rc.band_for(skill, sum(r.correct for r in all_results), 40)
        rc.record_attempt(conn, week=ctx["week"], skill=skill, td=plan[0][0].td, unit="all",
                          results=all_results, seconds=secs, aggregate=True)
    s["raw_total"] = (sum(r.correct for r in all_results), len(all_results))


def _cause_selector(skill: str, err, conn, key: str) -> None:
    opts = [BLANK] + rc.causes_for(skill)
    cur = err["cause"] if err["cause"] in opts else BLANK
    k = f"{key}_cause_{err['id']}"

    def _save():
        v = st.session_state[k]
        if v != BLANK:
            rc.save_cause(conn, skill, err["id"], v)
    st.selectbox(f"Causa del error en la pregunta {err['q']}", opts, index=opts.index(cur), key=k, on_change=_save)


def _show_results(skill: str, s: dict, plan, conn) -> None:
    raw, total = s["raw_total"]
    st.divider()
    st.subheader("Resultado")
    c = st.columns(3)
    c[0].metric("Aciertos", f"{raw}/{total}")
    if s.get("band") is not None:
        c[1].metric("Banda estimada (aproximada)", s["band"])
    for item in s["results"]:
        with st.expander(f"{item['label']} — {sum(r['correct'] for r in item['res'])}/{len(item['res'])}", expanded=True):
            st.table([{"Pregunta": r["q"], "Tu respuesta": r["user"] or "(vacía)",
                       "Correcta": r["expected"], "": "✅" if r["correct"] else "❌"} for r in item["res"]])
            errs = rc.attempt_errors(conn, item["aid"])
            if errs:
                st.markdown("**¿Por qué fallaste?** (se guarda en tu error log)")
                for e in errs:
                    _cause_selector(skill, e, conn, f"rs{item['aid']}")
        if skill == "listening":
            u = next(u for u, _ in plan if u.key == item["unit"] and u.td.test_id == item["test_id"])
            with st.expander("Transcripción del audio (para revisar lo que fallaste)"):
                st.text(u.td.listening[u.n - 1].transcript)


# ------------------------------------------------------------------ revisión (análisis de errores / corrección)
def _render_review(block, ctx) -> bool:
    conn = get_conn()
    skills = ["reading"] if block.id == "error_analysis" else ["reading", "listening"]
    shown = False
    for sk in skills:
        for a in rc.latest_attempts(conn, sk, limit=2):
            errs = rc.attempt_errors(conn, a["id"])
            band = f" · banda estimada (aproximada) {a['band']}" if a["band"] else ""
            st.markdown(f"### {sk.capitalize()} · {a['test_id']} · {a['unit']} — {a['raw']}/{a['total']}{band}")
            shown = True
            if not errs:
                st.success("Sin errores en este intento 🎉")
            for e in errs:
                st.markdown(f"- **P{e['q']}** ({e['qtype']}): tú pusiste «{e['user_answer'] or '(vacía)'}» → correcta: **{e['correct_answer']}**")
                _cause_selector(sk, e, conn, f"rv{a['id']}")
    if not shown:
        st.info("Aún no hay intentos de Reading/Listening para revisar. Haz primero el bloque de práctica.")
    return True


# ------------------------------------------------------------------ dictado
def _dictation(u: rc.Unit, key: str, ctx) -> None:
    lp = u.td.listening[u.n - 1]
    dkey = f"{key}_dict_{u.td.test_id}_{u.n}"
    ds = st.session_state.setdefault(dkey, {})
    with st.expander("✍️ Dictado (extra semanal, bottom-up)"):
        st.caption("Escucha ~1 minuto y escribe **palabra por palabra** lo que oyes. Luego compara con la transcripción del libro.")
        c1, c2 = st.columns(2)
        start = c1.number_input("Inicio (s)", min_value=0, value=60, step=10, key=f"{dkey}_s")
        length = c2.slider("Duración (s)", 30, 70, 60, key=f"{dkey}_l")
        st.audio(audio_src(lp.audio), format=audio_format(lp.audio), start_time=int(start), end_time=int(start + length))
        typed = st.text_area("Lo que oigo", key=f"{dkey}_t", height=140)
        if st.button("Comparar con el libro", key=f"{dkey}_c"):
            try:
                with st.spinner("Localizando el fragmento en la transcripción…"):
                    asr = get_transcriber().transcribe(resources_store().read_bytes(lp.audio), start=float(start), end=float(start + length))
                ref = dictation.locate(asr.text, lp.transcript)
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo transcribir el fragmento: {e}")
                return
            ds["ref"] = ref
            ds["cmp"] = dictation.compare_dictation(ref, typed)
        if ds.get("cmp"):
            r = ds["cmp"]
            st.metric("Similitud", f"{r['similarity'] * 100:.0f}%")
            st.markdown(f"**Referencia (libro):** {ds['ref']}")
            if r["missing"]:
                st.markdown("**No captaste:** " + ", ".join(r["missing"]))
            if r["weak_forms_missing"]:
                st.info("Formas débiles / coarticulación que omitiste: " + ", ".join(sorted(set(r["weak_forms_missing"]))))
            if r["extra"]:
                st.markdown("**Escribiste de más o distinto:** " + ", ".join(r["extra"]))
