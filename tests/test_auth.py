from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ielts import auth

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = {
    "pages/1_Sesion.py": "Elige un día",
    "pages/2_Error_log.py": "📝 Error log",
    "pages/3_Vocabulario.py": "Vocabulario (SRS)",
    "pages/4_Verificar_claves.py": "Verificar claves",
    "pages/5_Progreso.py": "Progreso",
}
SECRET_MARKERS = ("Práctica de la semana", "Punto de control", "Racha", "Modelo de lenguaje")


class FakeUser:
    def __init__(self, email=None, verified=True, name="Jesús"):
        self.is_logged_in = email is not None
        self.email, self.name, self.email_verified = email, name, verified


@pytest.fixture()
def cloud(monkeypatch, tmp_path):
    """Modo cloud sin tocar la red: DB local temporal y SIN lista de correos por defecto."""
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")
    from ielts import dbsync, ui
    from ielts.storage import MemoryStore
    import streamlit as st
    st.cache_resource.clear()
    store = MemoryStore()
    monkeypatch.setattr(dbsync, "make_store", lambda ns, root=None: store)
    monkeypatch.setattr(dbsync, "_local_dir", lambda: tmp_path / "cloud")
    monkeypatch.setattr(ui, "get_conn", ui.get_conn)           # se usa la versión real (SyncedConnection en memoria)
    yield
    st.cache_resource.clear()


def set_user(monkeypatch, user):
    calls = {"login": 0, "logout": 0}
    monkeypatch.setattr(auth, "_user", lambda: user)
    monkeypatch.setattr(auth, "_login", lambda: calls.__setitem__("login", calls["login"] + 1))
    monkeypatch.setattr(auth, "_logout", lambda: calls.__setitem__("logout", calls["logout"] + 1))
    return calls


def visible(at):
    text = " ".join([*(m.value for m in at.markdown), *(s.value for s in at.subheader), *(t.value for t in at.title),
                     *(m.label for m in at.metric)])
    return text


# ---------------------------------------------------------------- lógica de acceso
def test_allowed_emails_parsing(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", " Yo@Gmail.com; otra@x.org ,, ")
    assert auth.allowed_emails() == {"yo@gmail.com", "otra@x.org"}
    monkeypatch.setenv("ALLOWED_EMAILS", "")
    assert auth.allowed_emails() == set()


def test_local_mode_is_open_unless_login_is_forced(monkeypatch):
    monkeypatch.setenv("IELTS_MODE", "local")
    monkeypatch.delenv("IELTS_REQUIRE_LOGIN", raising=False)
    set_user(monkeypatch, FakeUser(None))
    assert auth.check_access() == ("open", None)
    monkeypatch.setenv("IELTS_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    assert auth.check_access()[0] == "login"


@pytest.mark.parametrize("user,expected", [
    (FakeUser(None), "login"),
    (FakeUser("intruso@gmail.com"), "denied"),
    (FakeUser("YO@gmail.com"), "ok"),                         # sin distinguir mayúsculas
    (FakeUser("yo@gmail.com", verified=False), "denied"),      # correo sin verificar
])
def test_check_access_states_in_cloud(monkeypatch, user, expected):
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    set_user(monkeypatch, user)
    assert auth.check_access()[0] == expected


def test_cloud_without_allowlist_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")
    set_user(monkeypatch, FakeUser("yo@gmail.com"))
    assert auth.check_access()[0] == "misconfigured"


# ---------------------------------------------------------------- las páginas
def test_home_hides_everything_when_not_logged_in(cloud, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    calls = set_user(monkeypatch, FakeUser(None))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert any(b.key == "auth_login" for b in at.button)
    assert not any(m in visible(at) for m in SECRET_MARKERS) and not any(b.key and b.key.startswith("day_") for b in at.button)
    next(b for b in at.button if b.key == "auth_login").click().run()
    assert calls["login"] == 1


def test_denied_account_sees_nothing_and_can_log_out(cloud, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    calls = set_user(monkeypatch, FakeUser("intruso@gmail.com"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert any("intruso@gmail.com" in e.value and "no tiene acceso" in e.value for e in at.error)
    assert not any(m in visible(at) for m in SECRET_MARKERS) and not any(b.key and b.key.startswith("day_") for b in at.button)
    next(b for b in at.button if b.key == "auth_logout_denied").click().run()
    assert calls["logout"] == 1


def test_missing_allowlist_blocks_even_a_logged_in_user(cloud, monkeypatch):
    set_user(monkeypatch, FakeUser("yo@gmail.com"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert any("ALLOWED_EMAILS" in e.value for e in at.error)
    assert not any(m in visible(at) for m in SECRET_MARKERS)


def test_allowed_user_gets_the_app_and_a_logout_button(cloud, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    set_user(monkeypatch, FakeUser("Yo@Gmail.com"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert any(b.key and b.key.startswith("day_") for b in at.button)
    assert any("yo@gmail.com" in c.value for c in at.sidebar.caption)
    assert any(b.key == "auth_logout" for b in at.sidebar.button)


@pytest.mark.parametrize("page", list(PAGES))
def test_every_page_is_guarded_when_opened_directly(cloud, monkeypatch, page):
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    set_user(monkeypatch, FakeUser("intruso@gmail.com"))
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page(page).run()
    assert not at.exception, (page, at.exception)
    assert any("no tiene acceso" in e.value for e in at.error), page
    assert PAGES[page] not in visible(at) and not at.dataframe and not at.metric


def test_local_mode_pages_render_without_login(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_MODE", "local")
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("IELTS_REQUIRE_LOGIN", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and any(b.key and b.key.startswith("day_") for b in at.button)
    assert not any(c.value.startswith("👤") for c in at.sidebar.caption)
