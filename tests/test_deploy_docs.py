import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def norm(name: str) -> str:
    return re.split(r"[<>=!~;\[ ]", name.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_requirements_cover_every_direct_dependency_and_skip_local_whisper():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    wanted = {norm(d) for d in project["dependencies"]}
    pinned = {norm(line) for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
              if line and not line.startswith(("#", " "))}
    assert wanted <= pinned, f"faltan en requirements.txt: {sorted(wanted - pinned)}"
    assert not ({"faster-whisper", "ctranslate2", "onnxruntime"} & pinned)           # extra local-stt: no va a la nube
    assert {"streamlit", "google-cloud-storage", "authlib"} <= pinned
    assert "local-stt" in project["optional-dependencies"]


def test_deploy_guide_mentions_every_secret_of_the_example():
    secrets = tomllib.loads((ROOT / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8"))
    guide = (ROOT / "DEPLOY.md").read_text(encoding="utf-8")
    for key in secrets:
        assert key in guide or key in ("IELTS_TZ", "IELTS_MODE"), f"DEPLOY.md no menciona {key}"
    for step in ("Prevención de acceso público", "Storage Object Admin", "redirect_uri", "sync_to_cloud.py", "Python version: 3.12"):
        assert step.lower().replace("á", "a") in guide.lower().replace("á", "a") or step in guide


def test_relative_links_in_docs_point_to_existing_files():
    for doc in ("README.md", "DEPLOY.md", "resources/README.md"):
        base = (ROOT / doc).parent
        text = (ROOT / doc).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+?)(?:#[^)]*)?\)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (base / target).exists(), f"{doc}: enlace roto → {target}"


def test_sync_script_help_runs_and_documents_the_safety_flags():
    r = subprocess.run([sys.executable, "scripts/sync_to_cloud.py", "--help"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0
    for flag in ("--dry-run", "--force-db", "--credentials", "--bucket", "--skip-db", "--yes"):
        assert flag in r.stdout
    assert "PRIVADO" in r.stdout


def test_sync_script_refuses_without_bucket(monkeypatch):
    env = {k: v for k, v in __import__("os").environ.items() if k != "GCS_BUCKET"}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "scripts/sync_to_cloud.py", "--dry-run"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", env=env)
    assert r.returncode != 0 and "bucket" in (r.stderr + r.stdout).lower()


def test_claude_md_reflects_cloud_mode_and_openai_default():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "DEPLOY.md" in text and "OpenAIProvider" in text and "No asumir despliegue en la nube" not in text
