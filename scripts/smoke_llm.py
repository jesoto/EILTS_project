"""Prueba real contra Ollama: genera un ejercicio y evalúa un ensayo con errores típicos.

Uso:  uv run python scripts/smoke_llm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts import db  # noqa: E402
from ielts.llm.client import get_provider  # noqa: E402
from ielts.modules import grammar as g  # noqa: E402
from ielts.modules import writing as w  # noqa: E402

ESSAY = """In nowadays, technology is very important for the education. Is clear that students can learn more fast with computers. Actually, many peoples thinks that online classes are better than traditional classes.

Firstly, the students can study in any place. Exist many platforms that offers free courses. Secondly, the teachers can use videos for explain difficult topics, so the students understand better. But some people say that technology make students lazy.

In conclusion, I am agree that technology have a positive impact in the education, but the government should invest more money."""

PROMPT = ("Some people believe that technology has improved education, while others think it has made students "
          "lazy. To what extent do you agree or disagree?")

provider = get_provider()
conn = db.connect(":memory:")

t = time.time()
ex = g.generate_exercise(provider, conn, "subject_agreement", "error_correction", level=3, phase=1, n_items=4)
print(f"--- Ejercicio ({time.time() - t:.0f}s) ---")
for i in ex.items:
    print(" *", i.prompt, "=>", i.answer)

t = time.time()
ev, checks = w.evaluate_writing(provider, "t2", PROMPT, ESSAY)
print(f"\n--- Evaluación ({time.time() - t:.0f}s) --- {w.BANNER}")
print("TR", ev.ta_tr.banda, "CC", ev.cc.banda, "LR", ev.lr.banda, "GRA", ev.gra.banda,
      "=> global", w.overall_writing_band(ev))
for e in ev.errores:
    print(f" - [{e.categoria.value}] {e.fragmento!r} -> {e.correccion!r} | {e.explicacion_es}")
print("Reescribir:", [o.original for o in ev.oraciones_a_reescribir])
bad = [e.fragmento for e in ev.errores if e.fragmento not in ESSAY]
print("Fragmentos que NO están literalmente en el ensayo:", bad or "ninguno")
