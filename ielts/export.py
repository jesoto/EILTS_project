"""Exports para la profesora: ensayo con errores marcados (martes) y dudas + transcripción (jueves)."""
from __future__ import annotations

import html
import io
import json
import sqlite3

from .llm.schemas import SpeakingEvaluation, WritingEvaluation
from .modules.speaking import BANNER as SPEAKING_BANNER
from .modules.writing import BANNER, TASK_LABEL, overall_writing_band


# ------------------------------------------------------------------ marcado de errores
def _spans(text: str, errors) -> list[tuple[int, int, str]]:
    """Posiciones (ini, fin, corrección) de cada fragmento erróneo, sin solaparse."""
    spans: list[tuple[int, int, str]] = []
    for e in sorted(errors, key=lambda e: -len(e.fragmento)):
        frag = e.fragmento.strip()
        if not frag:
            continue
        start = 0
        while True:
            i = text.find(frag, start)
            if i < 0:
                break
            if not any(i < b and a < i + len(frag) for a, b, _ in spans):
                spans.append((i, i + len(frag), e.correccion))
                break
            start = i + 1
    return sorted(spans)


def annotate_markdown(text: str, errors) -> str:
    """«fragmento» → ~~fragmento~~ **corrección**."""
    out, pos = [], 0
    for a, b, corr in _spans(text, errors):
        out += [text[pos:a], f"~~{text[a:b]}~~ **{corr}**"]
        pos = b
    return "".join(out + [text[pos:]])


def annotate_html(text: str, errors) -> str:
    out, pos = [], 0
    for a, b, corr in _spans(text, errors):
        out += [html.escape(text[pos:a]),
                f"<del style='color:#b00020'>{html.escape(text[a:b])}</del> "
                f"<ins style='color:#0a7d2c;font-weight:bold;text-decoration:none'>{html.escape(corr)}</ins>"]
        pos = b
    return "".join(out + [html.escape(text[pos:])]).replace("\n\n", "</p><p>").replace("\n", "<br>")


# ------------------------------------------------------------------ martes: ensayo + feedback
def teacher_essay_markdown(sub: sqlite3.Row) -> str:
    ev = WritingEvaluation.model_validate_json(sub["evaluation"])
    lines = [f"# {TASK_LABEL[sub['task']]} — para la profesora", "", f"_Fecha: {sub['date'][:10]} · semana {sub['week']}_", "",
             f"**Enunciado:** {sub['prompt']}", "", "## Ensayo con errores marcados",
             "~~tachado~~ = error · **negrita** = corrección propuesta", "", annotate_markdown(sub["text"], ev.errores), "",
             f"## Bandas ({BANNER})", "",
             f"- TA/TR **{ev.ta_tr.banda}** — {ev.ta_tr.justificacion_es}", f"- CC **{ev.cc.banda}** — {ev.cc.justificacion_es}",
             f"- LR **{ev.lr.banda}** — {ev.lr.justificacion_es}", f"- GRA **{ev.gra.banda}** — {ev.gra.justificacion_es}",
             f"- **Global ({BANNER}): {overall_writing_band(ev)}**", "", "## Lista de errores", "",
             "| Fragmento | Corrección | Categoría | Explicación |", "|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines += [f"| {esc(e.fragmento)} | {esc(e.correccion)} | {e.categoria.value} | {esc(e.explicacion_es)} |" for e in ev.errores]
    lines += ["", "## Oraciones a reescribir", ""] + [f"- {s.original} — _{s.problema_es}_" for s in ev.oraciones_a_reescribir]
    if sub["rewrite"]:
        rw = json.loads(sub["rewrite"])["resultados"]
        lines += ["", "## Mi reescritura", ""]
        for r in rw:
            lines.append(f"- {'✅' if r['correcta'] else '❌'} {r['reescrita']}"
                         + ("" if r["correcta"] else f" — {r.get('problema_restante_es', '')}"))
    lines += ["", "## Párrafo mejorado (propuesta del modelo)", "", ev.parrafo_mejorado.mejorado,
              "", f"_{ev.parrafo_mejorado.notas_es}_"]
    return "\n".join(lines)


def teacher_essay_html(sub: sqlite3.Row) -> str:
    ev = WritingEvaluation.model_validate_json(sub["evaluation"])
    rows = "".join(f"<tr><td>{html.escape(e.fragmento)}</td><td>{html.escape(e.correccion)}</td>"
                   f"<td>{e.categoria.value}</td><td>{html.escape(e.explicacion_es)}</td></tr>" for e in ev.errores)
    sentences = "".join(f"<li>{html.escape(s.original)} — <i>{html.escape(s.problema_es)}</i></li>"
                        for s in ev.oraciones_a_reescribir)
    return f"""<h1>{TASK_LABEL[sub['task']]} — para la profesora</h1>
<p><i>Fecha: {sub['date'][:10]} · semana {sub['week']}</i></p>
<p><b>Enunciado:</b> {html.escape(sub['prompt'])}</p>
<h2>Ensayo con errores marcados</h2>
<p style='font-size:9pt'><del style='color:#b00020'>tachado</del> = error · <b style='color:#0a7d2c'>verde</b> = corrección</p>
<p>{annotate_html(sub['text'], ev.errores)}</p>
<h2>Bandas ({BANNER})</h2>
<ul><li>TA/TR <b>{ev.ta_tr.banda}</b> — {html.escape(ev.ta_tr.justificacion_es)}</li>
<li>CC <b>{ev.cc.banda}</b> — {html.escape(ev.cc.justificacion_es)}</li>
<li>LR <b>{ev.lr.banda}</b> — {html.escape(ev.lr.justificacion_es)}</li>
<li>GRA <b>{ev.gra.banda}</b> — {html.escape(ev.gra.justificacion_es)}</li>
<li><b>Global ({BANNER}): {overall_writing_band(ev)}</b></li></ul>
<h2>Lista de errores</h2>
<table border='1' cellpadding='3' style='font-size:9pt'><tr><th>Fragmento</th><th>Corrección</th><th>Categoría</th><th>Explicación</th></tr>{rows}</table>
<h2>Oraciones a reescribir</h2><ul>{sentences}</ul>
<h2>Párrafo mejorado (propuesta del modelo)</h2><p>{html.escape(ev.parrafo_mejorado.mejorado)}</p>
<p><i>{html.escape(ev.parrafo_mejorado.notas_es)}</i></p>"""


# ------------------------------------------------------------------ jueves: dudas + Speaking
def doubts_markdown(week: int, doubts: list[str], session: sqlite3.Row | None) -> str:
    lines = [f"# Dudas para la profesora — semana {week}", ""]
    lines += [f"{i}. {d}" for i, d in enumerate(doubts, 1)] or ["_(sin dudas anotadas)_"]
    if session is not None:
        lines += ["", "## Mi monólogo de Speaking", "", f"**Tarea:** {session['prompt']}", "", "### Transcripción", "",
                  session["transcript"]]
        if session["evaluation"]:
            ev = SpeakingEvaluation.model_validate_json(session["evaluation"])
            lines += ["", f"### Feedback ({SPEAKING_BANNER})", "",
                      f"- FC {ev.fc.banda} · LR {ev.lr.banda} · GRA {ev.gra.banda}",
                      f"- Pronunciación (observación aproximada): {ev.pronunciacion_es}", ""]
            lines += [f"- ❌ {e.fragmento} → ✅ {e.correccion} ({e.categoria.value})" for e in ev.errores]
    return "\n".join(lines)


def doubts_html(week: int, doubts: list[str], session: sqlite3.Row | None) -> str:
    items = "".join(f"<li>{html.escape(d)}</li>" for d in doubts) or "<li><i>(sin dudas anotadas)</i></li>"
    out = f"<h1>Dudas para la profesora — semana {week}</h1><ol>{items}</ol>"
    if session is not None:
        out += (f"<h2>Mi monólogo de Speaking</h2><p><b>Tarea:</b> {html.escape(session['prompt']).replace(chr(10), '<br>')}</p>"
                f"<h3>Transcripción</h3><p>{html.escape(session['transcript']).replace(chr(10), '<br>')}</p>")
        if session["evaluation"]:
            ev = SpeakingEvaluation.model_validate_json(session["evaluation"])
            errs = "".join(f"<li>{html.escape(e.fragmento)} → <b>{html.escape(e.correccion)}</b> ({e.categoria.value})</li>"
                           for e in ev.errores)
            out += (f"<h3>Feedback ({SPEAKING_BANNER})</h3><p>FC {ev.fc.banda} · LR {ev.lr.banda} · GRA {ev.gra.banda}</p>"
                    f"<p><i>Pronunciación (aprox.): {html.escape(ev.pronunciacion_es)}</i></p><ul>{errs}</ul>")
    return out


# ------------------------------------------------------------------ PDF
def html_to_pdf(body_html: str) -> bytes:
    """Renderiza HTML sencillo a PDF A4 con PyMuPDF (sin dependencias extra)."""
    import pymupdf
    css = "body{font-family:sans-serif;font-size:10.5pt;line-height:1.35} h1{font-size:17pt} h2{font-size:13pt;margin-top:12pt}"
    story = pymupdf.Story(html=f"<body>{body_html}</body>", user_css=css)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    media = pymupdf.paper_rect("a4")
    where = media + (40, 40, -40, -40)
    more = 1
    while more:
        dev = writer.begin_page(media)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()
