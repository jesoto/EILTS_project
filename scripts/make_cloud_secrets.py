"""Genera un archivo de secrets listo para pegar en Streamlit Cloud, a partir de la clave JSON de tu cuenta de servicio.

Escribe `.streamlit/secrets.cloud.toml` (ignorado por git). NUNCA imprime claves: solo dice qué campos faltan por rellenar.

Uso:
    uv run python scripts/make_cloud_secrets.py --credentials sa.json --bucket resources_ielts \\
        --resources-prefix Resources_IELTS --email tu-correo@gmail.com --app-url https://mi-app.streamlit.app

Lo que NO se puede generar y debes rellenar tú: client_id y client_secret de Google OAuth (ver DEPLOY.md, paso 5).
"""
import argparse
import json
import secrets as pysecrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts.config import ROOT, secret  # noqa: E402

OUT = ROOT / ".streamlit" / "secrets.cloud.toml"
SA_FIELDS = ("type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "token_uri")
PLACEHOLDER_OAUTH = ("PEGA_AQUI_EL_CLIENT_ID", "PEGA_AQUI_EL_CLIENT_SECRET")


def q(value: str) -> str:
    """Cadena TOML básica (las secuencias de escape de JSON son válidas en TOML)."""
    return json.dumps(value, ensure_ascii=False)


def build(sa: dict, *, bucket: str, resources_prefix: str, email: str, app_url: str, tz: str, exam_date: str,
          openai_key: str, cookie_secret: str) -> str:
    lines = [
        "# Generado por scripts/make_cloud_secrets.py: pega TODO este contenido en Streamlit Cloud → Settings → Secrets.",
        "# Contiene claves privadas: no lo subas a GitHub (está en .gitignore).",
        "",
        'IELTS_MODE = "cloud"',
        f"IELTS_TZ = {q(tz)}",
    ]
    if exam_date:
        lines.append(f"IELTS_EXAM_DATE = {q(exam_date)}")
    lines += [
        "",
        f"OPENAI_API_KEY = {q(openai_key or 'PEGA_AQUI_TU_CLAVE_DE_OPENAI')}",
        f"ALLOWED_EMAILS = {q(email)}",
        "",
        f"GCS_BUCKET = {q(bucket)}",
    ]
    if resources_prefix:
        lines.append(f"GCS_RESOURCES_PREFIX = {q(resources_prefix.strip('/') + '/')}")
    lines += [
        "",
        "[auth]",
        f"redirect_uri = {q(app_url.rstrip('/') + '/oauth2callback')}",
        f"cookie_secret = {q(cookie_secret)}",
        f"client_id = {q(PLACEHOLDER_OAUTH[0])}",
        f"client_secret = {q(PLACEHOLDER_OAUTH[1])}",
        'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"',
        "",
        "[gcp_service_account]",
    ]
    lines += [f"{k} = {q(str(sa[k]))}" for k in SA_FIELDS if k in sa]
    return "\n".join(lines) + "\n"


def pending(text: str) -> list[str]:
    todo = []
    if "PEGA_AQUI_TU_CLAVE_DE_OPENAI" in text:
        todo.append("OPENAI_API_KEY (no se encontró en .env)")
    if PLACEHOLDER_OAUTH[0] in text:
        todo.append("[auth] client_id y client_secret (los da Google Cloud al crear el cliente OAuth)")
    if "tu-correo@gmail.com" in text:
        todo.append("ALLOWED_EMAILS (usa --email)")
    if "TU-APP" in text:
        todo.append("[auth] redirect_uri (usa --app-url con la URL real de tu app)")
    return todo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--credentials", required=True, help="clave JSON de la cuenta de servicio")
    ap.add_argument("--bucket", help="nombre del bucket (por defecto GCS_BUCKET)")
    ap.add_argument("--resources-prefix", default="", help="carpeta del bucket con tus libros/audios (p. ej. Resources_IELTS)")
    ap.add_argument("--email", default="tu-correo@gmail.com", help="correo(s) con acceso, separados por comas")
    ap.add_argument("--app-url", default="https://TU-APP.streamlit.app", help="URL de tu app en Streamlit Cloud")
    ap.add_argument("--tz", default="America/Lima")
    ap.add_argument("--exam-date", default="", help="YYYY-MM-DD si no es el 2026-12-29")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-openai-key", action="store_true", help="no copiar tu OPENAI_API_KEY de .env al archivo")
    args = ap.parse_args()

    sa = json.loads(Path(args.credentials).read_text(encoding="utf-8"))
    if sa.get("type") != "service_account" or not sa.get("private_key"):
        sys.exit("Ese archivo no parece una clave JSON de cuenta de servicio.")
    bucket = args.bucket or secret("GCS_BUCKET")
    if not bucket:
        sys.exit("Indica el bucket con --bucket.")
    text = build(sa, bucket=bucket, resources_prefix=args.resources_prefix, email=args.email, app_url=args.app_url,
                 tz=args.tz, exam_date=args.exam_date, openai_key="" if args.no_openai_key else (secret("OPENAI_API_KEY") or ""),
                 cookie_secret=pysecrets.token_urlsafe(48))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Escrito {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} ({len(text.splitlines())} líneas).")
    print(f"Cuenta de servicio: {sa.get('client_email')} · proyecto: {sa.get('project_id')}")
    todo = pending(text)
    if todo:
        print("\nTe falta rellenar a mano:")
        for t in todo:
            print("  -", t)
    print("\nPégalo entero en Streamlit Cloud → tu app → Settings → Secrets. No lo subas a GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
