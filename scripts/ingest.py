"""Ingesta de resources/ → data/derived/ (ambos ignorados por git).

Uso:
    uv run python scripts/ingest.py                 # inventario + todos los libros de data/books.yaml
    uv run python scripts/ingest.py --inventory     # solo inventario
    uv run python scripts/ingest.py --book c17      # solo ese libro
Después revisa y verifica las claves en la página «Verificar claves» de la app.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts.ingest import cambridge  # noqa: E402
from ielts.ingest.books import audio_map, find_pdf, load_books  # noqa: E402
from ielts.ingest.inventory import build_inventory  # noqa: E402
from ielts.ingest.schema import DERIVED_DIR, load_test, save_test  # noqa: E402
from ielts.storage import _local_roots  # noqa: E402

RESOURCES = _local_roots()["resources"]


def main() -> None:
    books = {b.id: b for b in load_books()}
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true", help="solo inventario")
    ap.add_argument("--book", choices=sorted(books), help="libro a procesar (por defecto, todos)")
    ap.add_argument("--force", action="store_true", help="sobrescribe también tests ya verificados")
    args = ap.parse_args()

    if not RESOURCES.exists():
        sys.exit(f"No existe {RESOURCES}. Crea la carpeta y copia tus libros y audios (ver resources/README.md).")
    inv = build_inventory(RESOURCES)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    (DERIVED_DIR / "inventory.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Inventario: {len(inv['pdfs'])} PDFs, {len(inv['audios'])} audios -> data/derived/inventory.json")
    for p in inv["pdfs"]:
        flag = "OCR" if p["needs_ocr"] else "texto"
        print(f"  [{flag:5}] {p['pages']:4d}p  {p['path']}")
    if args.inventory:
        return

    processed = 0
    for book in books.values():
        if args.book and book.id != args.book:
            continue
        pdf = find_pdf(RESOURCES, book)
        if pdf is None:
            print(f"{book.id}: no encuentro el PDF ({', '.join(book.pdf)}) en {RESOURCES}")
            continue
        audio = audio_map(RESOURCES, pdf, book.audio_pattern)
        print(f"{book.id}: {pdf.name} · {len(audio)} audios mapeados")
        try:
            tests = cambridge.parse_book(pdf, book.id, book.title, audio)
        except ValueError as e:
            print(f"{book.id}: no se pudo leer ({e}). ¿Es un PDF escaneado o de otro formato?")
            continue
        for t in tests:
            old = load_test(book.id, t.test)
            if old and old.verified and not args.force:
                print(f"{t.test_id}: ya VERIFICADO, no se sobrescribe (usa --force)")
                continue
            saved = save_test(t)
            processed += 1
            print(f"{t.test_id}: guardado ({saved}, {len(t.key_images)} imágenes de clave)")
            for n in t.notes:
                print("   AVISO:", n)
    if not processed:
        print("No se procesó ningún test. Revisa data/books.yaml y la carpeta resources/.")


if __name__ == "__main__":
    main()
