"""Acceso protegido: login de Google (OIDC de Streamlit) + lista de correos permitidos.

- Modo cloud: obligatorio. Falla cerrado: sin `ALLOWED_EMAILS` nadie entra.
- Modo local: desactivado, salvo que pongas IELTS_REQUIRE_LOGIN=1.
"""
from __future__ import annotations

import os

import streamlit as st

from .config import SECRETS_STATUS, load_app_config, on_streamlit_cloud, secret


def allowed_emails() -> set[str]:
    raw = secret("ALLOWED_EMAILS") or ""
    return {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}


def auth_required() -> bool:
    return load_app_config().is_cloud or os.environ.get("IELTS_REQUIRE_LOGIN", "").lower() in ("1", "true", "yes")


# Indirecciones finas para poder simular el login en los tests.
def _user():
    return st.user


def _login() -> None:
    st.login()


def _logout() -> None:
    st.logout()


def current_user() -> dict | None:
    """{'email', 'name', 'verified'} del usuario con sesión iniciada, o None."""
    u = _user()
    try:
        logged = bool(getattr(u, "is_logged_in", False))
    except Exception:  # noqa: BLE001
        logged = False
    if not logged:
        return None
    return {"email": str(getattr(u, "email", "") or "").strip().lower(), "name": str(getattr(u, "name", "") or ""),
            "verified": getattr(u, "email_verified", True) is not False}


def check_access() -> tuple[str, dict | None]:
    """Estado de acceso: 'open' (sin login), 'login' (hay que entrar), 'denied', 'misconfigured', 'wrong_mode' u 'ok'."""
    if on_streamlit_cloud() and not load_app_config().is_cloud:
        return "wrong_mode", None          # desplegada en Streamlit Cloud sin sus secrets: no mostrar NADA
    if not auth_required():
        return "open", None
    allowed = allowed_emails()
    if not allowed:
        return "misconfigured", None
    user = current_user()
    if user is None:
        return "login", None
    if not user["verified"] or user["email"] not in allowed:
        return "denied", user
    return "ok", user


def guard() -> dict | None:
    """Llamar al principio de CADA página (después de set_page_config). Detiene la ejecución si no hay acceso."""
    state, user = check_access()
    if state in ("open", "ok"):
        if user:
            with st.sidebar:
                st.caption(f"👤 {user['email']}")
                st.button("Cerrar sesión", on_click=_logout, key="auth_logout")
        return user
    if state == "wrong_mode":
        _wrong_mode_message()
    elif state == "misconfigured":
        st.error("Falta configurar `ALLOWED_EMAILS` en los secrets: por seguridad, nadie puede entrar hasta que lo hagas.")
    elif state == "login":
        st.title("📘 IELTS Trainer")
        st.info("Esta aplicación es privada. Inicia sesión con tu cuenta de Google.")
        st.button("Entrar con Google", on_click=_login, type="primary", key="auth_login")
    else:  # denied
        st.error(f"La cuenta **{user['email']}** no tiene acceso a esta aplicación.")
        st.button("Cerrar sesión", on_click=_logout, key="auth_logout_denied")
    st.stop()


def _wrong_mode_message() -> None:
    """La app está en Streamlit Cloud pero sin IELTS_MODE=cloud: casi seguro los Secrets no se aplicaron."""
    st.error("🔒 **La aplicación está bloqueada por seguridad.** Está desplegada en Streamlit Cloud pero no ha recibido "
             "su configuración privada (`IELTS_MODE = \"cloud\"`), así que no mostrará nada hasta que la tenga.")
    state = SECRETS_STATUS.get("state")
    detail = {"missing": "Streamlit **no tiene ningún secret** guardado para esta app.",
              "invalid": f"Los secrets existen pero **no se pueden leer** ({SECRETS_STATUS.get('error')}): suele ser TOML mal formado.",
              "loaded": f"Se leyeron {SECRETS_STATUS.get('keys')} secrets, pero falta `IELTS_MODE = \"cloud\"`."}.get(state, "")
    st.markdown(detail + "\n\n**Qué hacer:** en share.streamlit.io → tu app → ⋮ → *Settings* → *Secrets*, pega el contenido "
                "completo de `.streamlit/secrets.cloud.toml`, pulsa *Save* y luego *Reboot app*.")
    names = ["IELTS_MODE", "OPENAI_API_KEY", "ALLOWED_EMAILS", "GCS_BUCKET"]
    defined = {n: bool(secret(n)) for n in names}
    st.caption("Variables detectadas (solo si existen): " + ", ".join(f"{n} {'✅' if v else '❌'}" for n, v in defined.items()))
