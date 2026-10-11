import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "make_cloud_secrets.py"


@pytest.fixture()
def sa_file(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"type": "service_account", "project_id": "proj-x", "private_key_id": "kid-123",
                                "private_key": pem, "client_email": "app@proj-x.iam.gserviceaccount.com",
                                "client_id": "99", "token_uri": "https://oauth2.googleapis.com/token",
                                "ignored_extra_field": "no debe copiarse"}), encoding="utf-8")
    return path, pem


def run(args, env_extra=None):
    import os
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", env=env)


def test_generates_valid_toml_and_never_prints_secrets(tmp_path, sa_file):
    path, pem = sa_file
    out = tmp_path / "secrets.toml"
    r = run(["--credentials", str(path), "--bucket", "my-bucket", "--resources-prefix", "/Resources_IELTS/",
             "--email", "yo@gmail.com", "--app-url", "https://mi-app.streamlit.app/", "--out", str(out)],
            {"OPENAI_API_KEY": "sk-test-fake-key-for-this-test-0123456789"})
    assert r.returncode == 0, r.stderr
    shown = r.stdout + r.stderr
    assert "BEGIN PRIVATE KEY" not in shown and "sk-test-fake-key" not in shown and pem[40:80] not in shown
    cfg = tomllib.loads(out.read_text(encoding="utf-8"))
    assert cfg["IELTS_MODE"] == "cloud" and cfg["IELTS_TZ"] == "America/Lima" and cfg["GCS_BUCKET"] == "my-bucket"
    assert cfg["GCS_RESOURCES_PREFIX"] == "Resources_IELTS/"                       # normalizado, una sola barra final
    assert cfg["ALLOWED_EMAILS"] == "yo@gmail.com" and cfg["OPENAI_API_KEY"].startswith("sk-test-fake-key")
    assert cfg["auth"]["redirect_uri"] == "https://mi-app.streamlit.app/oauth2callback" and len(cfg["auth"]["cookie_secret"]) >= 40
    sa = cfg["gcp_service_account"]
    assert sa["private_key"] == pem and sa["client_email"].startswith("app@") and "ignored_extra_field" not in sa
    assert "client_id" in " ".join(r.stdout.split())                              # avisa de lo que falta (OAuth)


def test_private_key_roundtrips_into_working_credentials(tmp_path, sa_file):
    path, _ = sa_file
    out = tmp_path / "s.toml"
    assert run(["--credentials", str(path), "--bucket", "b", "--out", str(out)]).returncode == 0
    from google.oauth2 import service_account
    info = tomllib.loads(out.read_text(encoding="utf-8"))["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(info)           # la clave pegada en Streamlit sigue siendo válida
    assert creds.service_account_email == "app@proj-x.iam.gserviceaccount.com"


def test_reports_pending_fields_and_each_run_gets_a_new_cookie_secret(tmp_path, sa_file):
    path, _ = sa_file
    a, b = tmp_path / "a.toml", tmp_path / "b.toml"
    r = run(["--credentials", str(path), "--bucket", "b", "--no-openai-key", "--out", str(a)])
    assert "ALLOWED_EMAILS" in r.stdout and "redirect_uri" in r.stdout and "client_secret" in r.stdout
    assert "PEGA_AQUI_TU_CLAVE_DE_OPENAI" in a.read_text(encoding="utf-8")
    run(["--credentials", str(path), "--bucket", "b", "--out", str(b)])
    assert tomllib.loads(a.read_text(encoding="utf-8"))["auth"]["cookie_secret"] != \
        tomllib.loads(b.read_text(encoding="utf-8"))["auth"]["cookie_secret"]


def test_rejects_files_that_are_not_service_account_keys(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    r = run(["--credentials", str(bad), "--bucket", "b", "--out", str(tmp_path / "o.toml")])
    assert r.returncode != 0 and not (tmp_path / "o.toml").exists()


def test_generated_secrets_file_is_git_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", ".streamlit/secrets.cloud.toml"], cwd=ROOT)
    assert r.returncode == 0
    r2 = subprocess.run(["git", "check-ignore", "-q", ".streamlit/secrets.toml.example"], cwd=ROOT)
    assert r2.returncode == 1                                                      # el ejemplo SÍ se versiona


# ---------------------------------------------------------------- --apply-oauth
OAUTH = {"web": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-test-secret-value",
                 "project_id": "p", "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}


def test_apply_oauth_only_touches_the_auth_section_and_keeps_manual_edits(tmp_path, sa_file):
    path, pem = sa_file
    out = tmp_path / "s.toml"
    assert run(["--credentials", str(path), "--bucket", "b", "--email", "yo@gmail.com", "--out", str(out)]).returncode == 0
    before = tomllib.loads(out.read_text(encoding="utf-8"))
    out.write_text(out.read_text(encoding="utf-8").replace("TU-APP", "mi-app"), encoding="utf-8")   # edición manual previa
    oauth = tmp_path / "oauth.json"
    oauth.write_text(json.dumps(OAUTH), encoding="utf-8")
    r = run(["--apply-oauth", str(oauth), "--out", str(out)])
    assert r.returncode == 0 and "client_id, client_secret" in r.stdout
    assert "GOCSPX-test-secret-value" not in r.stdout + r.stderr                                   # nunca se imprime
    after = tomllib.loads(out.read_text(encoding="utf-8"))
    assert after["auth"]["client_id"] == "123-abc.apps.googleusercontent.com" and after["auth"]["client_secret"] == "GOCSPX-test-secret-value"
    assert after["gcp_service_account"]["client_id"] == before["gcp_service_account"]["client_id"] == "99"   # la otra sección intacta
    assert after["gcp_service_account"]["private_key"] == pem and after["ALLOWED_EMAILS"] == "yo@gmail.com"
    assert after["auth"]["cookie_secret"] == before["auth"]["cookie_secret"]                         # no se regenera
    assert after["auth"]["redirect_uri"] == "https://mi-app.streamlit.app/oauth2callback"
    assert "client_secret" not in " ".join(l for l in r.stdout.splitlines() if "falta" in l.lower() or l.startswith("  -"))


def test_apply_oauth_takes_redirect_uri_from_the_json_and_handles_installed_clients(tmp_path, sa_file):
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cloud_secrets as m
    base = m.build({"type": "service_account", "private_key": "k"}, bucket="b", resources_prefix="", email="e@x.com",
                   app_url="https://TU-APP.streamlit.app", tz="UTC", exam_date="", openai_key="sk-x", cookie_secret="c" * 48)
    web = {"web": {**OAUTH["web"], "redirect_uris": ["http://localhost:8501/oauth2callback", "https://real.streamlit.app/oauth2callback"]}}
    text, changed = m.apply_oauth(base, web)
    assert set(changed) == {"client_id", "client_secret", "redirect_uri"}
    assert tomllib.loads(text)["auth"]["redirect_uri"] == "https://real.streamlit.app/oauth2callback"
    text2, changed2 = m.apply_oauth(base, {"installed": OAUTH["web"]})
    assert "redirect_uri" not in changed2 and tomllib.loads(text2)["auth"]["client_id"].startswith("123-abc")
    with pytest.raises(ValueError):
        m.apply_oauth(base, {"web": {"client_id": "x"}})


def test_apply_oauth_requires_an_existing_file_and_valid_json(tmp_path):
    oauth = tmp_path / "oauth.json"
    oauth.write_text(json.dumps(OAUTH), encoding="utf-8")
    r = run(["--apply-oauth", str(oauth), "--out", str(tmp_path / "nope.toml")])
    assert r.returncode != 0 and "genera primero" in (r.stdout + r.stderr)
    out = tmp_path / "s.toml"
    out.write_text('[auth]\nclient_id = "x"\n', encoding="utf-8")
    oauth.write_text("{no es json", encoding="utf-8")
    assert run(["--apply-oauth", str(oauth), "--out", str(out)]).returncode != 0


def test_oauth_client_files_are_git_ignored():
    for name in ("oauth.json", "client_secret_1234.apps.googleusercontent.com.json", "my-oauth-client.json"):
        assert subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0, name
