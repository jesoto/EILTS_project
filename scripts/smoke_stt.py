"""Prueba real de faster-whisper con un fragmento de un audio de resources/ (solo lectura local).

Uso:  uv run python scripts/smoke_stt.py ["ruta/al.mp3"] [inicio_s] [fin_s]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ielts.modules import speaking as sp  # noqa: E402
from ielts.speaking_metrics import compute_metrics  # noqa: E402
from ielts.stt import FasterWhisperTranscriber  # noqa: E402

files = sp.list_shadowing_audios()
path = Path(sys.argv[1]) if len(sys.argv) > 1 else next(f for f in files if "T1 AUDIO 4" in f.name)
start = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
end = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
print("audio:", path.name, f"[{start}-{end}s]")

tr = FasterWhisperTranscriber()
t = time.time()
res = tr.transcribe(path, start=start, end=end)
print(f"transcrito en {time.time() - t:.0f}s (incluye carga/descarga del modelo)\n")
print(res.text, "\n")
print("primeras palabras:", [(w.text, round(w.start, 1), round(w.end, 1), round(w.prob, 2)) for w in res.words[:6]])
m = compute_metrics([res.words])
print("\n" + m.summary())
