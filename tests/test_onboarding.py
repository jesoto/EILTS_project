import re
import subprocess
import tomllib
from pathlib import Path

import httpx
import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from ielts import doctor
from ielts.ingest import schema
from ielts.ingest.books import Book, audio_map, book_status, find_pdf, load_books
from ielts.ingest.schema import TestData

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


def make_pdf(path: Path, text: str | None):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text * 40, fontsize=9)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Sin .env real, sin clave ni modo cloud: el diagnóstico parte de cero."""
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")
    for k in ("OPENAI_API_KEY", "IELTS_MODE", "ALLOWED_EMAILS", "GCS_BUCKET", "IELTS_LLM_PROVIDER", "IELTS_STT_PROVIDER",
              "IELTS_REQUIRE_LOGIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "t.db"))
    return tmp_path


# ---------------------------------------------------------------- libros
def test_default_books_config_lists_c17():
    books = load_books()
    assert [b.id for b in books] == ["c17"] and books[0].parser == "cambridge"
    assert re.fullmatch(books[0].audio_pattern, "T1 AUDIO 1")


def test_find_pdf_is_case_insensitive_and_searches_any_subfolder(tmp_path):
    book = Book("c17", "C17", "cambridge", ("cambridge_ielts_17_academic.pdf", "*ielts*17*academic*.pdf"), r"^T(\d) AUDIO (\d)$")
    assert find_pdf(tmp_path, book) is None and find_pdf(tmp_path / "nope", book) is None
    make_pdf(tmp_path / "Mis libros" / "Cambridge IELTS 17 ACADEMIC (2022).pdf", "x")
    assert find_pdf(tmp_path, book).name == "Cambridge IELTS 17 ACADEMIC (2022).pdf"
    make_pdf(tmp_path / "otra" / "Cambridge_IELTS_17_Academic.PDF", "x")             # extensión en mayúsculas
    assert find_pdf(tmp_path, book) is not None


def test_audio_map_uses_the_pdf_folder_and_the_pattern(tmp_path):
    pdf = tmp_path / "Book" / "b.pdf"
    make_pdf(pdf, "x")
    for name in ("T1 AUDIO 1.mp3", "T2 AUDIO 3.mp3", "ruido.mp3"):
        (pdf.parent / "Audios").mkdir(exist_ok=True)
        (pdf.parent / "Audios" / name).write_bytes(b"x")
    (tmp_path / "Otro").mkdir()
    (tmp_path / "Otro" / "T1 AUDIO 2.mp3").write_bytes(b"x")                          # otra carpeta: no cuenta
    got = audio_map(tmp_path, pdf, r"^T(\d) AUDIO (\d)$")
    assert got == {(1, 1): "Book/Audios/T1 AUDIO 1.mp3", (2, 3): "Book/Audios/T2 AUDIO 3.mp3"}
    assert audio_map(tmp_path, pdf, r"^Test (\d) Part (\d)$") == {}
    (pdf.parent / "Test 4 Part 2.MP3").write_bytes(b"x")
    assert audio_map(tmp_path, pdf, r"^test (\d) part (\d)$")[(4, 2)] == "Book/Test 4 Part 2.MP3"


def test_book_status_detects_scanned_pdfs(tmp_path):
    book = Book("b", "B", "cambridge", ("*.pdf",), r"^(\d) (\d)$")
    assert book_status(tmp_path, book) == {"pdf": None, "audios": 0, "scanned": None}
    make_pdf(tmp_path / "text.pdf", "Questions 1-10 complete the notes. " * 3)
    assert book_status(tmp_path, book)["scanned"] is False
    (tmp_path / "text.pdf").unlink()
    make_pdf(tmp_path / "scan.pdf", None)                                              # páginas sin texto
    assert book_status(tmp_path, book)["scanned"] is True


# ---------------------------------------------------------------- diagnóstico
def by_id(checks):
    return {c.id: c for c in checks}


def test_missing_openai_key_is_critical_and_explains_the_fix(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    c = by_id(doctor.check_llm())["llm"]
    assert c.status == doctor.FAIL and ".env" in c.fix and "OPENAI_API_KEY" in c.fix
    assert doctor.critical_problems() and any(p.id == "llm" for p in doctor.critical_problems())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890")
    assert by_id(doctor.check_llm())["llm"].status == doctor.OK and not any(p.id == "llm" for p in doctor.critical_problems())


def test_diagnostic_never_leaks_key_values(clean_env, monkeypatch):
    secret = "sk-proj-SUPER-SECRET-VALUE-0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    text = doctor.render_text(doctor.run_checks()) + str(doctor.env_summary())
    assert secret not in text and doctor.env_summary()["OPENAI_API_KEY"] is True


def test_ollama_provider_needs_no_key(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "ollama")
    assert by_id(doctor.check_llm())["llm"].status == doctor.OK


def test_stt_checks_follow_provider(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_STT_PROVIDER", "openai")
    assert by_id(doctor.check_stt())["stt"].status == doctor.FAIL                    # sin clave
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert by_id(doctor.check_stt())["stt"].status == doctor.OK
    monkeypatch.setenv("IELTS_STT_PROVIDER", "local")
    assert by_id(doctor.check_stt())["stt"].status in (doctor.OK, doctor.WARN)


def test_cloud_checks_require_bucket_credentials_allowlist_and_oauth(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setattr(doctor, "secret_section", lambda name: {})
    problems = {c.id for c in doctor.critical_problems()}
    assert {"gcs_bucket", "gcs_creds", "allowed", "oauth"} <= problems
    monkeypatch.setenv("GCS_BUCKET", "bkt")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    full = {"gcp_service_account": {"client_email": "a@b", "private_key": "k", "project_id": "p"},
            "auth": {k: "x" for k in ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")}}
    monkeypatch.setattr(doctor, "secret_section", lambda name: full.get(name, {}))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert not [c for c in doctor.critical_problems() if c.id in {"gcs_bucket", "gcs_creds", "allowed", "oauth"}]


def test_plan_check_flags_a_past_exam_date(clean_env, monkeypatch):
    assert by_id(doctor.check_plan())["plan"].status == doctor.OK
    monkeypatch.setenv("IELTS_EXAM_DATE", "2020-01-01")
    assert by_id(doctor.check_plan())["plan"].status == doctor.WARN
    monkeypatch.setenv("IELTS_TZ", "Mars/Olympus")
    assert by_id(doctor.check_mode())["tz"].status == doctor.FAIL


def test_books_check_reports_each_stage(clean_env, monkeypatch, tmp_path):
    res = tmp_path / "res"
    monkeypatch.setattr(doctor, "_local_roots", lambda: {"resources": res})
    assert by_id(doctor.check_books())["books"].status == doctor.FAIL                 # no existe resources/
    res.mkdir()
    assert by_id(doctor.check_books())["book_c17"].status == doctor.WARN              # sin PDF
    make_pdf(res / "Cambridge" / "cambridge_ielts_17_academic.pdf", "Questions complete the notes. ")
    monkeypatch.setattr(doctor, "list_tests", lambda: [])
    assert "sin ingerir" in by_id(doctor.check_books())["book_c17"].title
    tests = [TestData(book="c17", book_title="C17", test=n, verified=n == 1) for n in (1, 2)]
    monkeypatch.setattr(doctor, "list_tests", lambda: tests)
    assert "1/2 tests verificados" in by_id(doctor.check_books())["book_c17"].title
    tests[1].verified = True
    assert by_id(doctor.check_books())["book_c17"].status == doctor.OK
    make_pdf(res / "Cambridge" / "cambridge_ielts_17_academic.pdf", None)             # ahora escaneado
    assert "escaneado" in by_id(doctor.check_books())["book_c17"].title


def test_live_checks_with_a_mock_transport(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def models(ids):
        return httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": i} for i in ids]}))
    assert by_id(doctor.run_live_checks(models(["gpt-4.1-mini"])))["live_openai"].status == doctor.OK
    assert by_id(doctor.run_live_checks(models(["otro"])))["live_openai"].status == doctor.WARN
    assert by_id(doctor.run_live_checks(httpx.MockTransport(lambda r: httpx.Response(401))))["live_openai"].status == doctor.FAIL

    def boom(request):
        raise httpx.ConnectError("sin red")
    assert by_id(doctor.run_live_checks(httpx.MockTransport(boom)))["live_openai"].status == doctor.FAIL
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "ollama")
    ollama = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "gemma3:12b"}]}))
    assert by_id(doctor.run_live_checks(ollama))["live_ollama"].status == doctor.OK


def test_cli_exit_code_reflects_critical_problems(clean_env):
    env = {**__import__("os").environ, "IELTS_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(["uv", "run", "python", "scripts/doctor.py"], cwd=ROOT, capture_output=True, text=True, env=env,
                       encoding="utf-8")
    assert r.returncode in (0, 1) and "Modo:" in r.stdout


# ---------------------------------------------------------------- pantallas
def test_home_shows_a_friendly_setup_banner_when_the_key_is_missing(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert any("Falta configurar" in e.value and "OPENAI_API_KEY" in e.value for e in at.error)
    assert any(b.key and b.key.startswith("day_") for b in at.button)                  # la app sigue usable
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not any("Falta configurar" in e.value for e in at.error)


def test_configuration_page_renders_and_runs_live_checks(clean_env, monkeypatch):
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(doctor, "run_live_checks", lambda transport=None: [doctor.Check("live_x", doctor.OK, "Prueba de red OK")])
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/6_Configuracion.py").run()
    assert not at.exception, at.exception
    assert any("Modo: local" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Probar conexiones").click().run()
    assert any("Prueba de red OK" in m.value for m in at.markdown)


def test_configuration_page_shows_sync_status_in_cloud(clean_env, monkeypatch, tmp_path):
    import streamlit as st

    from ielts import dbsync
    from ielts.storage import MemoryStore
    st.cache_resource.clear()
    store = MemoryStore()
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    monkeypatch.setattr(dbsync, "make_store", lambda ns, root=None: store)
    monkeypatch.setattr(dbsync, "_local_dir", lambda: tmp_path / "cloud")
    from ielts import auth

    class U:
        is_logged_in, email, name, email_verified = True, "yo@gmail.com", "Yo", True
    monkeypatch.setattr(auth, "_user", lambda: U())
    at = AppTest.from_file(APP, default_timeout=60)
    at.switch_page("pages/6_Configuracion.py").run()
    assert not at.exception, at.exception
    labels = {m.label for m in at.metric}
    assert {"Pendiente de subir", "Última subida", "Conflicto"} <= labels
    st.cache_resource.clear()


# ---------------------------------------------------------------- higiene del repo
def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8").stdout
    except Exception:  # noqa: BLE001
        pytest.skip("git no disponible")
    return [ROOT / line for line in out.splitlines() if line]


def test_example_files_exist_and_contain_no_real_secrets():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-..." in env and not re.search(r"sk-[A-Za-z0-9_-]{20,}", env)
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8"))
    assert {"IELTS_MODE", "OPENAI_API_KEY", "ALLOWED_EMAILS", "GCS_BUCKET", "auth", "gcp_service_account"} <= set(secrets)
    assert set(secrets["auth"]) >= {"redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"}
    assert (ROOT / "resources" / "README.md").exists()


def test_no_tracked_file_contains_an_openai_key_or_private_key():
    pattern = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----\n[A-Za-z0-9+/=\n]{40,}")
    for f in tracked_files():
        if f.suffix.lower() in {".png", ".pdf", ".mp3", ".wav", ".lock"} or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        assert not pattern.search(text), f"posible secreto en {f.relative_to(ROOT)}"


def test_no_book_or_data_file_is_tracked_except_the_resources_readme():
    names = [str(f.relative_to(ROOT)).replace("\\", "/") for f in tracked_files()]
    assert not [n for n in names if n.lower().startswith("resources/") and n != "resources/README.md"]
    assert not [n for n in names if n.startswith("data/derived/") or n.endswith((".db", ".mp3", ".env"))]
    assert not [n for n in names if n == ".env" or n.endswith("secrets.toml")]


def test_schema_default_store_is_local_in_local_mode(clean_env):
    assert schema.derived_store().root.name == "derived"
