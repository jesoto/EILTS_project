"""Inventario de resources/: PDFs (¿texto o escaneado?) y audios (nombre → posible test/parte)."""
from __future__ import annotations

import re
from pathlib import Path


def guess_audio(rel: str) -> dict:
    """Intenta deducir libro/test/parte por el nombre del archivo; si no, marca ambiguous."""
    name = Path(rel).stem
    m = re.fullmatch(r"T(\d) AUDIO (\d)", name)
    if m:
        return {"book": "c17", "test": int(m.group(1)), "part": int(m.group(2)), "ambiguous": False}
    m = re.fullmatch(r"TEST (\d) PARTE (\d)", name, re.I)
    if m:
        return {"book": "c16", "test": int(m.group(1)), "part": int(m.group(2)), "ambiguous": False}
    return {"book": None, "test": None, "part": None, "ambiguous": True}


def build_inventory(resources: Path) -> dict:
    import pymupdf
    pdfs, audios = [], []
    for p in sorted(resources.rglob("*.pdf")):
        doc = pymupdf.open(str(p))
        n = doc.page_count
        step = max(1, n // 12)
        sampled = [len(doc[i].get_text()) for i in range(0, n, step)]
        with_text = sum(1 for c in sampled if c > 100)
        pdfs.append({"path": str(p.relative_to(resources)).replace("\\", "/"), "pages": n,
                     "needs_ocr": with_text / max(1, len(sampled)) < 0.5})
    for p in sorted(resources.rglob("*.mp3")):
        rel = str(p.relative_to(resources)).replace("\\", "/")
        audios.append({"path": rel, **guess_audio(rel)})
    return {"pdfs": pdfs, "audios": audios}
