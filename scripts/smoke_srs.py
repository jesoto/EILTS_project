"""Prueba real: el LLM completa tarjetas a partir de errores léxicos.

Uso:  uv run python scripts/smoke_srs.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts import db, srs  # noqa: E402
from ielts.llm.client import get_provider  # noqa: E402

conn = db.connect(":memory:")
db.log_error(conn, "writing", "make a research", "conduct research", "collocation", "Se dice conduct/carry out research")
db.log_error(conn, "writing", "Actually, many people", "Currently, many people", "false_friend", "actually no es actualmente")
srs.add_pending(conn, ["mitigate the effects", "sympathetic"], "weekly")
t = time.time()
n = srs.fill_pending(get_provider(), conn)
print(f"{n} tarjetas en {time.time() - t:.0f}s")
for r in conn.execute("SELECT * FROM card"):
    print(f"\n[{r['status']}] {r['word']}  <- {r['source']}\n  familia={r['family']}\n  colocs={r['collocations']}\n"
          f"  es={r['definition_es']}\n  ej={r['example_en']}\n  nota={r['note_es']}")
