"""Lógica de la página «Verificar claves»: filas editables ↔ KeyEntry, comprobaciones y vista previa del PDF."""
from __future__ import annotations

from pathlib import Path

from .schema import KeyEntry, TestData

SEP = " | "


def key_rows(td: TestData, skill: str) -> list[dict]:
    rows = []
    for e in td.key(skill):
        for i, q in enumerate(e.qnums):
            rows.append({"q": q, "answer": SEP.join(e.answers[i]), "any_order": e.any_order})
    return sorted(rows, key=lambda r: r["q"])


def rows_to_key(rows: list[dict]) -> list[KeyEntry]:
    """Reconstruye las entradas; las filas con any_order=True contiguas se agrupan por parejas."""
    rows = sorted((r for r in rows if r.get("q") is not None), key=lambda r: int(r["q"]))
    out: list[KeyEntry] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        alts = [a.strip() for a in str(r["answer"]).split("|") if a.strip()]
        if r.get("any_order") and i + 1 < len(rows) and rows[i + 1].get("any_order"):
            nxt = rows[i + 1]
            alts2 = [a.strip() for a in str(nxt["answer"]).split("|") if a.strip()]
            out.append(KeyEntry(qnums=[int(r["q"]), int(nxt["q"])], answers=[alts, alts2], any_order=True))
            i += 2
        else:
            out.append(KeyEntry(qnums=[int(r["q"])], answers=[alts], any_order=False))
            i += 1
    return out


def check(td: TestData) -> list[str]:
    """Avisos de coherencia para la revisión humana (más estricto que la validación de la ingesta)."""
    notes = []
    for skill in ("listening", "reading"):
        units = td.listening if skill == "listening" else td.reading
        km = td.key_map(skill)
        for u in units:
            for g in u.groups:
                for q in g.qnums:
                    e = km.get(q)
                    if not e:
                        notes.append(f"{skill} P{q}: sin clave")
                        continue
                    answers = e.answers[e.qnums.index(q)]
                    if g.input in ("choice", "tfng", "ynng", "headings"):
                        bad = [a for a in answers if a.upper() not in {o.upper() for o in g.options}]
                        if bad and not e.any_order:
                            notes.append(f"{skill} P{q}: la clave {bad} no está entre las opciones {g.options}")
                    elif any(not a for a in answers) or any(len(a.split()) > 6 for a in answers):
                        notes.append(f"{skill} P{q}: clave sospechosa {answers}")
    notes += [n for n in td.notes if n not in notes]
    return notes


def render_page(pdf: Path, page_number: int, dpi: int = 85) -> bytes:
    """Renderiza una página de un PDF local (solo ingesta)."""
    import pymupdf
    with pymupdf.open(str(pdf)) as doc:
        return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")


def key_page_images(td: TestData) -> list[tuple[str, bytes]]:
    """Imágenes de las páginas de clave guardadas en la ingesta: [(clave, png)]. Vacío si faltan."""
    from .schema import derived_store
    store = derived_store()
    out = []
    for key in td.key_images:
        try:
            out.append((key, store.read_bytes(key)))
        except FileNotFoundError:
            continue
    return out


def candidate_audios(td: TestData) -> list[str]:
    """mp3 del mismo libro (para reasignar manualmente un audio): carpeta de los audios ya asignados, o todos."""
    from ..storage import resources_store
    keys = [k for k in resources_store().list("") if k.lower().endswith(".mp3")]
    folders = {p.audio.rsplit("/", 1)[0] for p in td.listening if p.audio and "/" in p.audio}
    near = [k for k in keys if any(k.startswith(f + "/") for f in folders)]
    return sorted(near or keys)
