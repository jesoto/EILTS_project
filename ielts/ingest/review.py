"""Lógica de la página «Verificar claves»: filas editables ↔ KeyEntry, comprobaciones y vista previa del PDF."""
from __future__ import annotations

from pathlib import Path

from .schema import KeyEntry, TestData

RESOURCES = Path(__file__).resolve().parent.parent.parent / "resources"
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


def find_pdf(name: str) -> Path | None:
    if not name:
        return None
    return next(iter(RESOURCES.rglob(name)), None) if RESOURCES.exists() else None


def render_page(pdf: Path, page_number: int, dpi: int = 85) -> bytes:
    import pymupdf
    with pymupdf.open(str(pdf)) as doc:
        return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")


def candidate_audios(td: TestData) -> list[str]:
    """mp3 del mismo libro (para reasignar manualmente un audio)."""
    folder = next((p.parent for p in RESOURCES.rglob("*.pdf") if p.name == td.source_pdf), None)
    root = folder if folder else RESOURCES
    return sorted(str(p.relative_to(RESOURCES)).replace("\\", "/") for p in root.rglob("*.mp3"))
