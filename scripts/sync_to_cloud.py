"""Sube tus datos locales a tu bucket PRIVADO de Google Cloud Storage (para usar la app en Streamlit Cloud).

Qué sube (solo lo que cambió):
  derived     data/derived/**                      tests extraídos, imágenes de claves y gráficos
  resources   audios mp3 que usan tus tests        (no sube tus PDF ni el resto de la carpeta; --all-audio añade todos los Cambridge)
  db          data/ielts.db                        solo si no existe ya en la nube (--force-db para sobrescribir)
  recordings  data/recordings/*.wav                con --recordings

Credenciales: clave JSON de la cuenta de servicio, con --credentials ruta.json (o la variable GOOGLE_APPLICATION_CREDENTIALS).

Uso:
    uv run python scripts/sync_to_cloud.py --bucket mi-bucket --credentials clave.json --dry-run
    uv run python scripts/sync_to_cloud.py --bucket mi-bucket --credentials clave.json
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts import sync  # noqa: E402
from ielts.config import ROOT, secret  # noqa: E402
from ielts.ingest.schema import DERIVED_DIR  # noqa: E402
from ielts.storage import _local_roots  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bucket", help="nombre del bucket (por defecto GCS_BUCKET)")
    ap.add_argument("--credentials", help="ruta a la clave JSON de la cuenta de servicio")
    ap.add_argument("--resources-prefix", help="carpeta del bucket donde están tus libros/audios (por defecto GCS_RESOURCES_PREFIX o resources/)")
    ap.add_argument("--dry-run", action="store_true", help="solo muestra qué se subiría")
    ap.add_argument("--yes", action="store_true", help="no pedir confirmación")
    ap.add_argument("--force-db", action="store_true", help="sobrescribe la base de datos de la nube con la local")
    ap.add_argument("--all-audio", action="store_true", help="sube todos los mp3 de libros Cambridge, no solo los usados")
    ap.add_argument("--recordings", action="store_true", help="incluye tus grabaciones de Speaking")
    ap.add_argument("--skip-db", action="store_true", help="no toca la base de datos")
    args = ap.parse_args()

    if args.credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.credentials
    bucket = args.bucket or secret("GCS_BUCKET")
    if not bucket:
        sys.exit("Indica el bucket con --bucket o define GCS_BUCKET en .env")

    roots = _local_roots()
    items = sync.collect_derived(DERIVED_DIR)
    items += sync.collect_audio(roots["resources"], DERIVED_DIR, all_cambridge=args.all_audio)
    if not args.skip_db:
        items += sync.collect_db(Path(os.environ.get("IELTS_DB") or ROOT / "data" / "ielts.db"))
    if args.recordings:
        items += sync.collect_recordings(roots["recordings"])
    if not items:
        sys.exit("No hay nada que subir: ejecuta primero scripts/ingest.py")

    stores = sync.cloud_stores(bucket, resources_prefix=args.resources_prefix)
    try:
        sync.plan(items, stores, force_db=args.force_db)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"No se pudo acceder al bucket «{bucket}»: {type(e).__name__}: {e}\n"
                 "Revisa el nombre, la clave de la cuenta de servicio y sus permisos (Storage Object Admin sobre el bucket).")

    summary = sync.summarize(items)
    print(f"Bucket: gs://{bucket}  (debe ser PRIVADO: acceso uniforme + prevención de acceso público)\n")
    for ns in ("derived", "resources", "db", "recordings"):
        group = [i for i in items if i.namespace == ns]
        if group:
            up = [i for i in group if i.action in ("new", "changed")]
            print(f"  {ns:<11} {len(group):4d} archivos · subir {len(up):4d} ({sync.human(sum(i.size for i in up))})"
                  f" · sin cambios {sum(i.action == 'same' for i in group)}")
    for b in summary["blocked"]:
        print(f"  ⚠ {b.label}: {b.note}")
    print(f"\nTotal a subir: {summary['upload']} archivos, {sync.human(summary['bytes'])}")
    if args.dry_run or not summary["upload"]:
        print("(simulación: no se ha subido nada)" if args.dry_run else "Todo está al día.")
        return 0
    if not args.yes and input("¿Subir ahora? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
        print("Cancelado.")
        return 1
    report = sync.execute(items, stores, force_db=args.force_db,
                          progress=lambda it, ok, bad: print(f"  subido {it.label} ({sync.human(it.size)})"))
    print(f"\nSubidos: {report['uploaded']} · fallidos: {report['failed']}")
    for e in report["errors"]:
        print("  ✗", e)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
