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
