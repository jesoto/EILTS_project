"""Ingesta de resources/ → data/derived/ (ambos ignorados por git).

Uso:
    uv run python scripts/ingest.py                 # inventario + Cambridge 17
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
from ielts.ingest.inventory import build_inventory  # noqa: E402
from ielts.ingest.schema import DERIVED_DIR, load_test, save_test  # noqa: E402

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
BOOKS = {
    "c17": dict(pdf="Cambriedge IELTS 17 (2022)/cambridge_ielts_17_academic.pdf", title="Cambridge IELTS 17 Academic",
                audio_dir="Cambriedge IELTS 17 (2022)", audio=cambridge.map_audio_c17),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true", help="solo inventario")
    ap.add_argument("--book", choices=sorted(BOOKS), help="libro a procesar (por defecto, todos)")
    ap.add_argument("--force", action="store_true", help="sobrescribe también tests ya verificados")
    args = ap.parse_args()

    inv = build_inventory(RESOURCES)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    (DERIVED_DIR / "inventory.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Inventario: {len(inv['pdfs'])} PDFs, {len(inv['audios'])} audios -> data/derived/inventory.json")
    for p in inv["pdfs"]:
        flag = "OCR" if p["needs_ocr"] else "texto"
        print(f"  [{flag:5}] {p['pages']:4d}p  {p['path']}")
    if args.inventory:
        return

    for key, cfg in BOOKS.items():
        if args.book and key != args.book:
            continue
        pdf = RESOURCES / cfg["pdf"]
        if not pdf.exists():
            print(f"{key}: no existe {pdf}")
            continue
        audio = cfg["audio"](RESOURCES, cfg["audio_dir"])
        for t in cambridge.parse_book(pdf, key, cfg["title"], audio):
            old = load_test(key, t.test)
            if old and old.verified and not args.force:
                print(f"{t.test_id}: ya VERIFICADO, no se sobrescribe (usa --force)")
                continue
            path = save_test(t)
            print(f"{t.test_id}: guardado en {path.relative_to(DERIVED_DIR.parent.parent)}")
            for n in t.notes:
                print("   AVISO:", n)


if __name__ == "__main__":
    main()
