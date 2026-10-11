import io
import json
import math
import struct
import wave
from pathlib import Path

import httpx
import pytest

from ielts import audio
from ielts.config import STTConfig
from ielts.llm.base import LLMError
from ielts.llm.usage import FileUsage
from ielts.stt import FasterWhisperTranscriber, OpenAITranscriber, make_transcriber, resolve_stt_provider

ROOT = Path(__file__).resolve().parent.parent
C17_AUDIO = ROOT / "resources" / "Cambriedge IELTS 17 (2022)" / "AUDIOS PARA NAVEGADOR" / "T1 AUDIO 4.mp3"


def tone_wav(seconds=3.0, rate=44100, channels=2, freq=440) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) * channels
                          for i in range(int(seconds * rate)))
        w.writeframes(frames)
    return buf.getvalue()


def read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


# ---------------------------------------------------------------- recorte y conversión de audio
def test_to_wav16k_converts_to_mono_16khz_and_keeps_duration():
    wav, dur = audio.to_wav16k(tone_wav(3.0, 44100, 2))
    ch, width, rate, frames = read_wav(wav)
    assert (ch, width, rate) == (1, 2, 16000) and dur == pytest.approx(3.0, abs=0.05)
    assert frames == pytest.approx(48000, abs=800)


def test_to_wav16k_cuts_the_requested_window():
    src = tone_wav(4.0)
    wav, dur = audio.to_wav16k(src, 1.0, 2.5)
    assert dur == pytest.approx(1.5, abs=0.05) and read_wav(wav)[3] == pytest.approx(24000, abs=800)
    _, dur_tail = audio.to_wav16k(src, 3.0, None)                      # sin fin: hasta el final
    assert dur_tail == pytest.approx(1.0, abs=0.05)
    _, dur_past = audio.to_wav16k(src, 10.0, 12.0)                     # ventana fuera del audio: vacía, sin fallar
    assert dur_past == 0
    with pytest.raises(Exception):
        audio.to_wav16k(b"esto no es audio")


@pytest.mark.skipif(not C17_AUDIO.exists(), reason="resources/ no disponible")
def test_to_wav16k_handles_real_mp3_window():
    wav, dur = audio.to_wav16k(C17_AUDIO.read_bytes(), 10, 30)
    assert dur == pytest.approx(20, abs=0.3) and read_wav(wav)[2] == 16000


# ---------------------------------------------------------------- OpenAITranscriber
VERBOSE = {"text": " Hello there, I think so.", "duration": 3.0,
           "words": [{"word": " Hello", "start": 0.1, "end": 0.5}, {"word": " there,", "start": 0.6, "end": 1.0},
                     {"word": " I", "start": 1.2, "end": 1.3}, {"word": " think", "start": 1.3, "end": 1.7}],
           "segments": [{"start": 0.0, "end": 1.1, "avg_logprob": -0.1}, {"start": 1.1, "end": 3.0, "avg_logprob": -1.2}]}


def make(handler, tmp_path, **cfg):
    return OpenAITranscriber(STTConfig(provider="openai", initial_prompt="Umm, like", **cfg),
                             transport=httpx.MockTransport(handler), usage=FileUsage(tmp_path / "u.jsonl"),
                             sleep=lambda s: None)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SECRET")


def test_request_is_multipart_wav_with_word_timestamps_and_prompt(tmp_path):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["ct"] = request.headers["content-type"]
        seen["body"] = request.content
        seen["url"] = str(request.url)
        return httpx.Response(200, json=VERBOSE)

    t = make(handler, tmp_path).transcribe(tone_wav(3.0))
    body = seen["body"]
    assert seen["url"].endswith("/audio/transcriptions") and seen["auth"] == "Bearer sk-test-SECRET"
    assert seen["ct"].startswith("multipart/form-data")
    for needle in (b'name="model"', b"whisper-1", b"verbose_json", b'name="timestamp_granularities[]"', b"word",
                   b"segment", b'name="language"', b"\r\nen\r\n", b'name="prompt"', b"Umm, like", b'filename="audio.wav"', b"RIFF"):
        assert needle in body, needle
    assert t.text == "Hello there, I think so." and [w.text for w in t.words] == ["Hello", "there,", "I", "think"]
    assert t.duration == 3.0


def test_window_offset_is_added_and_confidence_comes_from_the_segment(tmp_path):
    t = make(lambda r: httpx.Response(200, json=VERBOSE), tmp_path).transcribe(tone_wav(8.0), start=5.0, end=8.0)
    assert t.words[0].start == pytest.approx(5.1) and t.words[3].end == pytest.approx(6.7)    # tiempos absolutos
    assert t.words[0].prob == pytest.approx(math.exp(-0.1)) and t.words[3].prob == pytest.approx(math.exp(-1.2))
    assert t.words[3].prob < 0.5 < t.words[0].prob                      # el segmento dudoso se marca como poco seguro


def test_usage_recorded_and_daily_cap_blocks_before_upload(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=VERBOSE)
    tr = make(handler, tmp_path)
    tr.transcribe(tone_wav(1.0))
    assert len(FileUsage(tmp_path / "u.jsonl").rows()) == 1
    monkeypatch.setenv("IELTS_LLM_PROVIDER", "openai")
    from ielts.config import LLMConfig
    tr.llm = LLMConfig(provider="openai", max_calls_per_day=1)
    with pytest.raises(LLMError, match="Límite diario"):
        tr.transcribe(tone_wav(1.0))
    assert len(calls) == 1


def test_errors_are_friendly_and_never_leak_the_key(tmp_path):
    with pytest.raises(LLMError, match="rechazó la clave") as e:
        make(lambda r: httpx.Response(401, text="bad sk-test-SECRET"), tmp_path).transcribe(tone_wav(1.0))
    assert "sk-test-SECRET" not in str(e.value)
    with pytest.raises(LLMError, match="Sin crédito"):
        make(lambda r: httpx.Response(429, json={"error": {"code": "insufficient_quota", "message": "insufficient_quota"}}),
             tmp_path).transcribe(tone_wav(1.0))
    with pytest.raises(LLMError) as e2:
        make(lambda r: httpx.Response(400, text="oops sk-test-SECRET"), tmp_path).transcribe(tone_wav(1.0))
    assert "***" in str(e2.value) and "sk-test-SECRET" not in str(e2.value)


def test_transient_errors_are_retried(tmp_path):
    n = []

    def flaky(request):
        n.append(1)
        return httpx.Response(503) if len(n) < 3 else httpx.Response(200, json=VERBOSE)
    assert make(flaky, tmp_path).transcribe(tone_wav(1.0)).text.startswith("Hello") and len(n) == 3


def test_missing_key_message(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")      # que .env no devuelva la clave real
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        make(lambda r: httpx.Response(200, json=VERBOSE), tmp_path).transcribe(tone_wav(1.0))


# ---------------------------------------------------------------- elección de proveedor
def test_provider_auto_resolves_by_mode(monkeypatch):
    assert resolve_stt_provider(STTConfig(provider="auto")) == "local"
    monkeypatch.setenv("IELTS_MODE", "cloud")
    assert resolve_stt_provider(STTConfig(provider="auto")) == "openai"
    assert resolve_stt_provider(STTConfig(provider="local")) == "local"      # explícito manda
    assert isinstance(make_transcriber(), OpenAITranscriber)
    monkeypatch.setenv("IELTS_MODE", "local")
    monkeypatch.setenv("IELTS_STT_PROVIDER", "openai")
    assert isinstance(make_transcriber(), OpenAITranscriber)
    monkeypatch.setenv("IELTS_STT_PROVIDER", "local")
    assert isinstance(make_transcriber(), FasterWhisperTranscriber)


def test_local_whisper_missing_gives_actionable_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "faster_whisper":
            raise ImportError("no module")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="local-stt"):
        FasterWhisperTranscriber(STTConfig())._load()


def test_fake_transcript_roundtrips_through_speaking_metrics(tmp_path):
    """El Transcript de la nube alimenta las mismas métricas que el local."""
    from ielts.speaking_metrics import compute_metrics
    t = make(lambda r: httpx.Response(200, json=VERBOSE), tmp_path).transcribe(tone_wav(3.0))
    m = compute_metrics([t.words])
    assert m.words == 4 and m.wpm > 0 and json.dumps(m.summary())
