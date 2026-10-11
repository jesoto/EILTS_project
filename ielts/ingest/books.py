"""Configuración de libros (data/books.yaml): localizar el PDF y mapear audios dentro de resources/."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

BOOKS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "books.yaml"


@dataclass(frozen=True)
class Book:
    id: str
    title: str
    parser: str
    pdf: tuple[str, ...]
    audio_pattern: str


def load_books(path: Path | None = None) -> list[Book]:
    with open(path or BOOKS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return [Book(id=b["id"], title=b["title"], parser=b.get("parser", "cambridge"), pdf=tuple(b["pdf"]),
                 audio_pattern=b["audio_pattern"]) for b in raw.get("books", [])]


def find_pdf(resources: Path, book: Book) -> Path | None:
    """Primer PDF de resources/ que coincide con algún patrón del libro (sin distinguir mayúsculas)."""
    if not resources.exists():
        return None
    pdfs = sorted(p for p in resources.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    for pattern in book.pdf:
        for p in pdfs:
            if fnmatch.fnmatch(p.name.lower(), pattern.lower()):
                return p
    return None


def audio_map(resources: Path, pdf: Path, pattern: str) -> dict[tuple[int, int], str]:
    """{(test, parte): ruta relativa a resources/} de los mp3 de la carpeta del PDF cuyo nombre encaja con el patrón."""
    rx = re.compile(pattern, re.I)
    out: dict[tuple[int, int], str] = {}
    for p in sorted(pdf.parent.rglob("*.mp3")):
        m = rx.fullmatch(p.stem) or rx.match(p.stem)
        if m and len(m.groups()) >= 2:
            out[(int(m.group(1)), int(m.group(2)))] = str(p.relative_to(resources)).replace("\\", "/")
    return out


def book_status(resources: Path, book: Book) -> dict:
    """Para el diagnóstico: ¿está el PDF? ¿cuántos audios? ¿es escaneado?"""
    pdf = find_pdf(resources, book)
    if pdf is None:
        return {"pdf": None, "audios": 0, "scanned": None}
    audios = audio_map(resources, pdf, book.audio_pattern)
    import pymupdf
    with pymupdf.open(str(pdf)) as doc:
        n = doc.page_count
        sample = [len(doc[i].get_text()) for i in range(0, n, max(1, n // 12))]
    scanned = sum(1 for c in sample if c > 100) / max(1, len(sample)) < 0.5
    return {"pdf": str(pdf.relative_to(resources)).replace("\\", "/"), "audios": len(audios), "scanned": scanned}
