"""Diagnóstico de configuración desde la terminal.

Uso:
    uv run python scripts/doctor.py          # comprobaciones sin red
    uv run python scripts/doctor.py --live   # además prueba OpenAI / Ollama / bucket (llamadas gratuitas)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts import doctor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="comprobaciones con red")
    args = ap.parse_args()
    checks = doctor.run_checks() + (doctor.run_live_checks() if args.live else [])
    print(doctor.render_text(checks))
    bad = [c for c in checks if c.status == doctor.FAIL]
    print(f"\n{len(bad)} problema(s) crítico(s)." if bad else "\nTodo lo esencial está en orden.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
