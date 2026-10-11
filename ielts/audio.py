"""Utilidades de audio con PyAV: recorte de ventanas y conversión a WAV 16 kHz mono (lo que pide la API de transcripción)."""
from __future__ import annotations

import io
import wave

SAMPLE_RATE = 16000


def to_wav16k(data: bytes, start: float | None = None, end: float | None = None) -> tuple[bytes, float]:
    """Decodifica cualquier formato (mp3, wav, webm…), recorta [start, end] en segundos y devuelve (wav, duración_s)."""
    import av

    pcm = bytearray()
    with av.open(io.BytesIO(data)) as container:
        if not container.streams.audio:
            raise ValueError("el archivo no contiene audio")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pcm += out.to_ndarray().tobytes()
        for out in resampler.resample(None):         # vacía el remuestreador
            pcm += out.to_ndarray().tobytes()

    total = len(pcm) // 2
    i0 = max(0, int((start or 0) * SAMPLE_RATE))
    i1 = total if end is None else min(total, int(end * SAMPLE_RATE))
    chunk = bytes(pcm[2 * i0:2 * max(i0, i1)])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(chunk)
    return buf.getvalue(), len(chunk) / 2 / SAMPLE_RATE
