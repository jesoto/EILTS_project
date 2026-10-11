"""Diagnóstico de configuración: qué falta para que la app funcione (clave, modelo, libros, almacenamiento, acceso…).

`run_checks()` es estático (no usa la red). `run_live_checks()` hace llamadas gratuitas (lista de modelos, lista del bucket).
Nunca devuelve ni imprime valores de claves.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from .config import SECRETS_STATUS, load_app_config, load_llm_config, load_stt_config, on_streamlit_cloud, secret, secret_section
from .ingest.books import book_status, load_books
from .ingest.schema import list_tests
from .storage import _local_roots

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    id: str
    status: str
    title: str
    detail: str = ""
    fix: str = ""


def _has_key() -> bool:
    return bool(secret(load_llm_config().openai_key_env))


def check_secrets() -> list[Check]:
    from .config import load_env
    load_env()
    st = SECRETS_STATUS
    if st["state"] == "invalid":
        return [Check("secrets", FAIL, "Los secrets de Streamlit no se pueden leer", f"Error: {st['error']}",
                      "Revisa que el contenido de Settings → Secrets sea TOML válido y vuelve a guardar")]
    if on_streamlit_cloud() and st["state"] != "loaded":
        return [Check("secrets", FAIL, "Esta app está en Streamlit Cloud sin secrets",
                      fix="Pega .streamlit/secrets.cloud.toml en Settings → Secrets, Save y Reboot")]
    if st["state"] == "loaded":
        return [Check("secrets", OK, f"Secrets de Streamlit cargados ({st['keys']} claves)")]
    return []


def check_mode() -> list[Check]:
    app = load_app_config()
    out = [Check("mode", OK, f"Modo: {app.mode}", "local = tu equipo · cloud = Streamlit Cloud")]
    from . import clock
    zone = clock.tz()
    if app.timezone and zone is None:
        out.append(Check("tz", FAIL, f"Zona horaria desconocida: {app.timezone}", fix="Usa un nombre válido, p. ej. America/Lima"))
    else:
        out.append(Check("tz", OK if app.timezone else WARN, f"Zona horaria: {app.timezone or 'la del sistema'}",
                         f"Hoy en la app: {clock.today().isoformat()}",
                         "" if app.timezone else "En la nube define `timezone` (config.toml) o IELTS_TZ: el servidor está en UTC"))
    return out


def check_llm() -> list[Check]:
    cfg = load_llm_config()
    if cfg.provider == "openai":
        if not _has_key():
            return [Check("llm", FAIL, "Falta la clave de OpenAI",
                          "Sin ella no se pueden evaluar Writing, Speaking ni generar ejercicios",
                          f"Pon {cfg.openai_key_env}=sk-... en el archivo .env (o en los secrets de Streamlit). Ver .env.example")]
        return [Check("llm", OK, f"LLM: OpenAI · {cfg.openai_model}", f"Tope diario: {cfg.max_calls_per_day or 'sin tope'} llamadas")]
    return [Check("llm", OK, f"LLM: Ollama · {cfg.model}", f"Servidor: {cfg.host}",
                  "Comprueba que Ollama está abierto y que descargaste el modelo (`ollama pull`)")]


def check_stt() -> list[Check]:
    from .stt import resolve_stt_provider
    cfg = load_stt_config()
    provider = resolve_stt_provider(cfg)
    if provider == "openai":
        if not _has_key():
            return [Check("stt", FAIL, "Transcripción (OpenAI) sin clave", fix="Define OPENAI_API_KEY")]
        return [Check("stt", OK, f"Transcripción: OpenAI · {cfg.openai_model}", "~0,006 USD por minuto de audio")]
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return [Check("stt", WARN, "Whisper local no instalado", "Speaking no podrá transcribir",
                      "Ejecuta `uv sync --extra local-stt` o usa [stt] provider = \"openai\"")]
    return [Check("stt", OK, f"Transcripción: Whisper local · {cfg.model} ({cfg.device})")]


def check_books(resources=None) -> list[Check]:
    resources = resources or _local_roots()["resources"]
    app = load_app_config()
    if app.is_cloud:
        return [Check("books", OK, "Libros: se leen del almacenamiento en la nube",
                      "Se suben con scripts/sync_to_cloud.py desde tu equipo")]
    if not resources.exists():
        return [Check("books", FAIL, "No existe la carpeta resources/", "Aquí van tus libros (PDF) y audios (mp3)",
                      "Crea la carpeta y sigue resources/README.md")]
    out = []
    ingested = {}
    for t in list_tests():
        ingested.setdefault(t.book, []).append(t)
    for book in load_books():
        st = book_status(resources, book)
        tests = ingested.get(book.id, [])
        verified = sum(t.verified for t in tests)
        if st["pdf"] is None:
            out.append(Check(f"book_{book.id}", WARN, f"{book.title}: sin PDF",
                             f"Se busca en resources/ (patrones: {', '.join(book.pdf)})",
                             "Copia tu PDF a resources/ o ajusta data/books.yaml"))
        elif st["scanned"]:
            out.append(Check(f"book_{book.id}", WARN, f"{book.title}: PDF escaneado", st["pdf"],
                             "Sin texto seleccionable no se puede ingerir (haría falta OCR)"))
        elif not tests:
            out.append(Check(f"book_{book.id}", WARN, f"{book.title}: PDF y {st['audios']} audios, sin ingerir",
                             st["pdf"], "Ejecuta `uv run python scripts/ingest.py`"))
        elif verified < len(tests):
            out.append(Check(f"book_{book.id}", WARN, f"{book.title}: {verified}/{len(tests)} tests verificados",
                             f"{st['audios']} audios", "Abre «Verificar claves» y compara las claves con el PDF"))
        else:
            out.append(Check(f"book_{book.id}", OK, f"{book.title}: {len(tests)} tests verificados", f"{st['audios']} audios"))
    return out or [Check("books", WARN, "No hay libros configurados en data/books.yaml")]


def check_storage_and_db() -> list[Check]:
    app = load_app_config()
    if not app.is_cloud:
        return [Check("db", OK, "Base de datos: SQLite local", "data/ielts.db (ignorada por git)")]
    out = []
    bucket = secret("GCS_BUCKET")
    out.append(Check("gcs_bucket", OK if bucket else FAIL, "Bucket de Google Cloud Storage" + (": configurado" if bucket else ": falta"),
                     fix="" if bucket else "Define GCS_BUCKET en los secrets"))
    info = secret_section("gcp_service_account")
    need = {"client_email", "private_key", "project_id"}
    missing = sorted(need - set(info))
    out.append(Check("gcs_creds", OK if not missing else FAIL, "Cuenta de servicio de Google" + (": configurada" if not missing else ": incompleta"),
                     "" if not missing else f"Faltan campos: {', '.join(missing)}",
                     "" if not missing else "Pega la clave JSON de la cuenta de servicio en [gcp_service_account]"))
    return out


def check_access() -> list[Check]:
    from .auth import allowed_emails, auth_required
    if not auth_required():
        return [Check("auth", OK, "Acceso: abierto (modo local)")]
    out = []
    emails = allowed_emails()
    out.append(Check("allowed", OK if emails else FAIL,
                     f"Correos permitidos: {len(emails)}" if emails else "Falta ALLOWED_EMAILS",
                     "" if emails else "Por seguridad nadie puede entrar sin lista de correos",
                     "" if emails else "Define ALLOWED_EMAILS en los secrets"))
    a = secret_section("auth")
    miss = sorted({"redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"} - set(a))
    out.append(Check("oauth", OK if not miss else FAIL, "Login de Google (OIDC)" + (": configurado" if not miss else ": incompleto"),
                     "" if not miss else f"Faltan: {', '.join(miss)}", "" if not miss else "Rellena la sección [auth] de los secrets"))
    return out


def check_plan() -> list[Check]:
    from . import clock
    from .curriculum import load_curriculum
    cur = load_curriculum()
    left = (cur.exam_date - clock.today()).days
    detail = (f"Inicio {cur.start_date:%d/%m/%Y} · punto de control {cur.checkpoint_date:%d/%m/%Y} "
              f"· examen {cur.exam_date:%d/%m/%Y}")
    if left < 0:
        return [Check("plan", WARN, "La fecha de examen ya pasó", detail,
                      "Define [plan] exam_date en config.toml (o IELTS_EXAM_DATE)")]
    fix = "Te quedan menos de 11 semanas: empezarás en la semana que corresponde a hoy" if left < 77 else ""
    return [Check("plan", OK, f"Plan de 11 semanas · faltan {left} días", detail, fix)]


def run_checks() -> list[Check]:
    checks: list[Check] = []
    for fn in (check_secrets, check_mode, check_plan, check_llm, check_stt, check_storage_and_db, check_access, check_books):
        try:
            checks += fn()
        except Exception as e:  # noqa: BLE001 — un diagnóstico nunca debe tumbar la página
            checks.append(Check(fn.__name__, WARN, f"No se pudo comprobar ({fn.__name__})", f"{type(e).__name__}: {e}"))
    return checks


def critical_problems() -> list[Check]:
    """Problemas que impiden usar la app. Solo comprobaciones rápidas (no abre PDFs): se usa en la pantalla de inicio."""
    out: list[Check] = []
    for fn in (check_secrets, check_llm, check_stt, check_storage_and_db, check_access):
        try:
            out += [c for c in fn() if c.status == FAIL]
        except Exception:  # noqa: BLE001
            continue
    return out


# ------------------------------------------------------------------ comprobaciones con red (gratuitas)
def run_live_checks(transport: httpx.BaseTransport | None = None) -> list[Check]:
    out = []
    cfg = load_llm_config()
    if cfg.provider == "openai" and _has_key():
        try:
            with httpx.Client(transport=transport, timeout=20) as c:
                r = c.get(f"{cfg.openai_base_url}/models", headers={"Authorization": f"Bearer {secret(cfg.openai_key_env)}"})
            if r.status_code == 200:
                ids = {m["id"] for m in r.json().get("data", [])}
                if cfg.openai_model in ids:
                    out.append(Check("live_openai", OK, f"OpenAI responde y el modelo {cfg.openai_model} está disponible"))
                else:
                    out.append(Check("live_openai", WARN, f"OpenAI responde, pero tu cuenta no lista {cfg.openai_model}",
                                     fix="Cambia `openai_model` en config.toml"))
            elif r.status_code == 401:
                out.append(Check("live_openai", FAIL, "OpenAI rechazó la clave (401)", fix="Revisa OPENAI_API_KEY"))
            else:
                out.append(Check("live_openai", WARN, f"OpenAI devolvió {r.status_code}"))
        except httpx.HTTPError as e:
            out.append(Check("live_openai", FAIL, "No se pudo conectar con OpenAI", str(e)[:150]))
    if cfg.provider == "ollama":
        try:
            with httpx.Client(transport=transport, timeout=3) as c:
                r = c.get(f"{cfg.host}/api/tags")
            names = [m["name"] for m in r.json().get("models", [])]
            ok = cfg.model in names
            out.append(Check("live_ollama", OK if ok else WARN, "Ollama responde" + ("" if ok else f", pero falta el modelo {cfg.model}"),
                             "" if ok else f"Modelos: {', '.join(names) or 'ninguno'}", "" if ok else f"Ejecuta `ollama pull {cfg.model}`"))
        except Exception as e:  # noqa: BLE001
            out.append(Check("live_ollama", FAIL, "No se pudo conectar con Ollama", str(e)[:150], "Abre Ollama"))
    if load_app_config().is_cloud:
        try:
            from .storage import make_store
            store = make_store("derived")
            n = len(store.list(""))
            out.append(Check("live_gcs", OK, f"Google Cloud Storage accesible ({n} archivos en derived/)"))
            res = make_store("resources")
            mp3 = [k for k in res.list("") if k.lower().endswith(".mp3")]
            out.append(Check("live_gcs_resources", OK if mp3 else WARN,
                             f"Recursos en el bucket ({getattr(res, 'prefix', '')}): {len(mp3)} audios",
                             "" if mp3 else "No hay audios en esa carpeta",
                             "" if mp3 else "Sube tus audios o define GCS_RESOURCES_PREFIX con la carpeta donde están"))
            info = store.public_access_info() if hasattr(store, "public_access_info") else {}
            if info.get("public_access_prevention") != "enforced":
                out.append(Check("live_gcs_private", WARN, "El bucket no tiene activada la prevención de acceso público",
                                 "Tus libros y datos deben ser privados",
                                 "En Google Cloud → Storage → tu bucket → Permisos → «Prevención de acceso público»: Aplicar"))
            else:
                out.append(Check("live_gcs_private", OK, "Bucket privado: prevención de acceso público activada"))
        except Exception as e:  # noqa: BLE001
            out.append(Check("live_gcs", FAIL, "No se pudo acceder al bucket", f"{type(e).__name__}: {str(e)[:150]}",
                             "Revisa GCS_BUCKET, la clave de la cuenta de servicio y sus permisos"))
    return out or [Check("live", WARN, "No hay nada que probar con red en esta configuración")]


def render_text(checks: list[Check]) -> str:
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    lines = []
    for c in checks:
        lines.append(f"{icon[c.status]} {c.title}" + (f" — {c.detail}" if c.detail else ""))
        if c.fix and c.status != OK:
            lines.append(f"     → {c.fix}")
    return "\n".join(lines)


def env_summary() -> dict:
    """Variables relevantes definidas (solo nombres, nunca valores)."""
    names = ["OPENAI_API_KEY", "IELTS_MODE", "IELTS_TZ", "IELTS_EXAM_DATE", "ALLOWED_EMAILS", "GCS_BUCKET"]
    return {n: bool(secret(n)) for n in names}
