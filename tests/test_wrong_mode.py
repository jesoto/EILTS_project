from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from ielts import auth, config, doctor

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
SENSITIVE = ("Práctica de la semana", "Racha", "Punto de control", "Tema de la semana", "Empezar diagnóstico")
PAGES = ["pages/1_Sesion.py", "pages/2_Error_log.py", "pages/3_Vocabulario.py", "pages/4_Verificar_claves.py",
         "pages/5_Progreso.py", "pages/6_Configuracion.py"]


class FakeSecrets:
    """Imita st.secrets: puede estar vacío, ser ilegible o traer valores."""

    def __init__(self, data=None, error=None):
        self.data, self.error = data or {}, error

    def keys(self):
        if self.error:
            raise self.error
        return self.data.keys()

    def __getitem__(self, k):
        if self.error:
            raise self.error
        return self.data[k]


class StreamlitSecretNotFoundError(FileNotFoundError):
    """Mismo nombre que la excepción real de Streamlit cuando no hay secrets.toml."""


@pytest.fixture()
def on_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_ON_CLOUD", "1")                     # simula que el código vive en /mount/src
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")
    for k in ("IELTS_MODE", "OPENAI_API_KEY", "ALLOWED_EMAILS", "GCS_BUCKET", "IELTS_REQUIRE_LOGIN"):
        monkeypatch.delenv(k, raising=False)
    config.SECRETS_STATUS.update(state="unknown", error=None, keys=0)
    yield
    config.SECRETS_STATUS.update(state="unknown", error=None, keys=0)


def visible(at):
    return " ".join([*(m.value for m in at.markdown), *(e.value for e in at.error), *(c.value for c in at.caption),
                     *(s.value for s in at.subheader), *(t.value for t in at.title), *(m.label for m in at.metric)])


# ---------------------------------------------------------------- detección y estado de los secrets
def test_streamlit_cloud_is_detected_by_the_mount_path(monkeypatch):
    monkeypatch.delenv("IELTS_ON_CLOUD", raising=False)
    assert not config.on_streamlit_cloud()
    monkeypatch.setattr(config, "ROOT", Path("/mount/src/eilts_project"))
    assert config.on_streamlit_cloud()
    monkeypatch.setattr(config, "ROOT", Path("C:/Users/User/Documents/GitHub/EILTS_project"))
    assert not config.on_streamlit_cloud()
    monkeypatch.setenv("IELTS_ON_CLOUD", "1")
    assert config.on_streamlit_cloud()


@pytest.mark.parametrize("secrets,state", [
    (FakeSecrets({"IELTS_MODE": "cloud", "OPENAI_API_KEY": "sk-x", "auth": {"a": 1}}), "loaded"),
    (FakeSecrets(error=StreamlitSecretNotFoundError("no secrets")), "missing"),
    (FakeSecrets(error=ValueError("toml roto")), "invalid"),
])
def test_bridge_records_what_happened_without_leaking_content(monkeypatch, secrets, state):
    monkeypatch.setattr(st, "secrets", secrets, raising=False)
    monkeypatch.delenv("IELTS_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.bridge_streamlit_secrets()
    assert config.SECRETS_STATUS["state"] == state
    if state == "loaded":
        assert config.SECRETS_STATUS["keys"] == 3 and __import__("os").environ["IELTS_MODE"] == "cloud"
        assert "auth" not in __import__("os").environ                    # las tablas no se copian al entorno
    else:
        assert "toml roto" not in str(config.SECRETS_STATUS)            # solo el tipo de error, no su mensaje
    monkeypatch.delenv("IELTS_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ---------------------------------------------------------------- acceso
def test_cloud_host_without_cloud_mode_is_wrong_mode_even_if_a_user_is_logged_in(on_cloud, monkeypatch):
    class U:
        is_logged_in, email, email_verified = True, "yo@gmail.com", True
    monkeypatch.setattr(auth, "_user", lambda: U())
    assert auth.check_access()[0] == "wrong_mode"
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    assert auth.check_access()[0] == "ok"                                 # con la configuración correcta, normal


def test_local_machine_is_unaffected(monkeypatch):
    monkeypatch.delenv("IELTS_ON_CLOUD", raising=False)
    monkeypatch.setenv("IELTS_MODE", "local")
    assert auth.check_access() == ("open", None)


@pytest.mark.parametrize("page", ["app.py", *PAGES])
def test_every_page_shows_nothing_but_the_lock_message(on_cloud, monkeypatch, page, tmp_path):
    monkeypatch.setattr(st, "secrets", FakeSecrets(error=StreamlitSecretNotFoundError("x")), raising=False)
    at = AppTest.from_file(APP, default_timeout=60)
    if page != "app.py":
        at.switch_page(page)
    at.run()
    assert not at.exception, (page, at.exception)
    text = visible(at)
    assert "bloqueada por seguridad" in text and "IELTS_MODE" in text
    assert not any(s in text for s in SENSITIVE) and not at.dataframe
    assert not any(b.key and b.key.startswith("day_") for b in at.button)
    assert not (tmp_path / "t.db").exists()                                # ni siquiera se abrió la base de datos


@pytest.mark.parametrize("secrets,needle", [
    (FakeSecrets(error=StreamlitSecretNotFoundError("x")), "no tiene ningún secret"),
    (FakeSecrets(error=ValueError("boom")), "no se pueden leer"),
    (FakeSecrets({"OPENAI_API_KEY": "sk-x"}), "falta `IELTS_MODE"),
])
def test_lock_message_explains_the_probable_cause(on_cloud, monkeypatch, secrets, needle):
    monkeypatch.setattr(st, "secrets", secrets, raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert needle in visible(at), visible(at)
    assert "Save" in visible(at) and "Reboot" in visible(at)
    assert "sk-x" not in visible(at)                                       # nunca se muestran valores, solo ✅/❌


def test_lock_message_lists_which_variables_exist_without_values(on_cloud, monkeypatch):
    monkeypatch.setattr(st, "secrets", FakeSecrets({"OPENAI_API_KEY": "sk-secret-value-123"}), raising=False)
    text = visible(AppTest.from_file(APP, default_timeout=60).run())
    assert "OPENAI_API_KEY ✅" in text and "IELTS_MODE ❌" in text and "GCS_BUCKET ❌" in text
    assert "sk-secret-value-123" not in text


# ---------------------------------------------------------------- diagnóstico
def test_doctor_flags_missing_or_invalid_secrets(on_cloud, monkeypatch):
    monkeypatch.setattr(st, "secrets", FakeSecrets(error=StreamlitSecretNotFoundError("x")), raising=False)
    c = doctor.check_secrets()[0]
    assert c.status == doctor.FAIL and "Secrets" in c.fix and any(p.id == "secrets" for p in doctor.critical_problems())
    monkeypatch.setattr(st, "secrets", FakeSecrets(error=ValueError("boom")), raising=False)
    assert "no se pueden leer" in doctor.check_secrets()[0].title
    monkeypatch.setattr(st, "secrets", FakeSecrets({"IELTS_MODE": "cloud"}), raising=False)
    assert doctor.check_secrets()[0].status == doctor.OK


def test_doctor_is_quiet_about_secrets_on_a_normal_local_machine(monkeypatch):
    monkeypatch.delenv("IELTS_ON_CLOUD", raising=False)
    monkeypatch.setattr(st, "secrets", FakeSecrets(error=StreamlitSecretNotFoundError("x")), raising=False)
    assert doctor.check_secrets() == []                                   # sin secrets en local es lo normal
