from pathlib import Path

import pytest

from ielts import storage
from ielts.ingest import review
from ielts.ingest import schema
from ielts.ingest.schema import TestData, derived_store, list_tests, load_test, save_test
from ielts.modules import speaking as sp
from ielts.storage import ANY, ConflictError, DirStore, GCSStore, MemoryStore


# ---------------------------------------------------------------- GCS falso (misma API que google-cloud-storage)
class PreconditionFailed(Exception):
    code = 412


class NotFound(Exception):
    code = 404


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name, self.generation = bucket, name, None

    def exists(self):
        return self.name in self.bucket.objects

    def download_as_bytes(self):
        if not self.exists():
            raise NotFound(self.name)
        return self.bucket.objects[self.name][0]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self.bucket.objects.get(self.name)
        current_gen = cur[1] if cur else 0
        if if_generation_match is not None and if_generation_match != current_gen:
            raise PreconditionFailed("412")
        self.bucket.counter += 1
        self.bucket.objects[self.name] = (bytes(data), self.bucket.counter, content_type)
        self.generation = self.bucket.counter

    def delete(self):
        self.bucket.objects.pop(self.name, None)

    def generate_signed_url(self, version, expiration, method):
        return f"https://signed.example/{self.name}?exp={int(expiration.total_seconds())}&v={version}&m={method}"


class FakeBucket:
    def __init__(self, name):
        self.name, self.objects, self.counter = name, {}, 0

    def blob(self, name):
        b = FakeBlob(self, name)
        if name in self.objects:
            b.generation = self.objects[name][1]
        return b

    def get_blob(self, name):
        return self.blob(name) if name in self.objects else None


class FakeClient:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))

    def list_blobs(self, bucket, prefix=""):
        b = self.bucket(bucket if isinstance(bucket, str) else bucket.name)
        return [FakeBlob(b, n) for n in sorted(b.objects) if n.startswith(prefix)]


def stores(tmp_path):
    return [DirStore(tmp_path / "dir"), MemoryStore(), GCSStore("bkt", "ns/", client=FakeClient())]


# ---------------------------------------------------------------- contrato común a los tres backends
def test_roundtrip_list_delete_and_missing(tmp_path):
    for s in stores(tmp_path):
        assert not s.exists("a/b.txt") and s.version("a/b.txt") is None and s.list() == []
        with pytest.raises(FileNotFoundError):
            s.read_bytes("a/b.txt")
        s.write_bytes("a/b.txt", b"hola")
        s.write_text("a/c.json", '{"x": 1}')
        s.write_bytes("z.bin", b"\x00\x01")
        assert s.read_bytes("a/b.txt") == b"hola" and s.read_text("a/c.json") == '{"x": 1}'
        assert s.list() == ["a/b.txt", "a/c.json", "z.bin"] and s.list("a/") == ["a/b.txt", "a/c.json"]
        s.delete("a/b.txt")
        s.delete("a/b.txt")                                   # borrar dos veces no falla
        assert s.list() == ["a/c.json", "z.bin"]


def test_versions_and_optimistic_concurrency(tmp_path):
    for s in stores(tmp_path):
        v1 = s.write_bytes("db", b"1", if_version=None)       # crear solo si no existe
        with pytest.raises(ConflictError):
            s.write_bytes("db", b"x", if_version=None)
        v2 = s.write_bytes("db", b"2", if_version=v1)
        assert v2 != v1 and s.version("db") == v2
        with pytest.raises(ConflictError):
            s.write_bytes("db", b"3", if_version=v1)          # versión vieja: otra sesión escribió antes
        assert s.read_bytes("db") == b"2"
        s.write_bytes("db", b"4", if_version=ANY)             # sin condición
        assert s.read_bytes("db") == b"4"


def test_dirstore_is_atomic_and_blocks_path_traversal(tmp_path):
    s = DirStore(tmp_path / "root")
    s.write_bytes("deep/er/file.txt", b"ok")
    assert (tmp_path / "root" / "deep" / "er" / "file.txt").read_bytes() == b"ok"
    assert not [p for p in (tmp_path / "root").rglob(".tmp-*")]        # sin temporales residuales
    with pytest.raises(ValueError):
        s.read_bytes("../outside.txt")
    assert s.local_path("deep/er/file.txt").name == "file.txt"
    assert DirStore(tmp_path / "nothing").list() == []


def test_gcs_prefix_signed_url_and_private_by_default():
    client = FakeClient()
    s = GCSStore("bkt", "resources", client=client)                   # el prefijo se normaliza con «/»
    s.write_bytes("Book/T1 AUDIO 1.mp3", b"mp3", content_type="audio/mpeg")
    assert list(client.bucket("bkt").objects) == ["resources/Book/T1 AUDIO 1.mp3"]
    assert client.bucket("bkt").objects["resources/Book/T1 AUDIO 1.mp3"][2] == "audio/mpeg"
    url = s.url("Book/T1 AUDIO 1.mp3", expires=1800)
    assert "exp=1800" in url and "v=v4" in url and "m=GET" in url
    assert DirStore(Path(".")).url("x") is None and DirStore(Path(".")).local_path("x") is not None
    assert GCSStore("bkt", "resources/", client=client).list() == ["Book/T1 AUDIO 1.mp3"]   # claves relativas


# ---------------------------------------------------------------- fábricas y modo cloud
def test_make_store_local_vs_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("IELTS_RESOURCES", str(tmp_path / "res"))
    assert isinstance(storage.resources_store(), DirStore)
    monkeypatch.setenv("IELTS_MODE", "cloud")
    with pytest.raises(RuntimeError, match="GCS_BUCKET"):
        storage.resources_store()
    monkeypatch.setenv("GCS_BUCKET", "my-private-bucket")
    s = storage.resources_store()
    assert isinstance(s, GCSStore) and s.prefix == "resources/" and s._bucket_name == "my-private-bucket"
    assert storage.recordings_store().prefix == "recordings/"


# ---------------------------------------------------------------- integración con los módulos
def test_schema_works_on_any_store_including_images(tmp_path, monkeypatch):
    mem = MemoryStore()
    monkeypatch.setattr(schema, "derived_store", lambda root=None: mem)
    td = TestData(book="bk", book_title="Book", test=2, key_images=["bk/images/k.png"])
    assert save_test(td) == "bk/test2.json" and mem.exists("bk/test2.json")
    mem.write_bytes("bk/images/k.png", b"\x89PNG")
    assert [t.test_id for t in list_tests()] == ["bk/test2"] and load_test("bk", 2).book_title == "Book"
    assert load_test("bk", 9) is None
    assert review.key_page_images(load_test("bk", 2)) == [("bk/images/k.png", b"\x89PNG")]
    mem.delete("bk/images/k.png")
    assert review.key_page_images(load_test("bk", 2)) == []            # imagen perdida: lista vacía, no excepción


def test_recordings_roundtrip_and_old_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("IELTS_RECORDINGS", str(tmp_path / "rec"))
    name = sp.save_recording(b"RIFFdata", 3, "p2")
    assert name.startswith("w3_p2_") and name.endswith(".wav")
    assert storage.recordings_store().read_bytes(name) == b"RIFFdata"
    from ielts.modules.ui_export import _recording
    assert _recording({"audio_path": name}) == (name, b"RIFFdata")
    old = {"audio_path": "C:\\Users\\x\\data\\recordings\\" + name}        # filas guardadas antes del refactor
    assert _recording(old) == (name, b"RIFFdata")
    assert _recording({"audio_path": "nope.wav"}) is None and _recording(None) is None


def test_shadowing_and_candidate_audios_list_keys_not_paths(tmp_path, monkeypatch):
    res = tmp_path / "res"
    for rel in ["Cambridge IELTS 17/AUDIO/T1 AUDIO 1.mp3", "Cambridge IELTS 17/AUDIO/T1 AUDIO 2.mp3",
                "Cambridge grammar for IELTS/PISTA 1.mp3", "Other book/x.mp3", "Cambridge IELTS 17/book.pdf"]:
        (res / rel).parent.mkdir(parents=True, exist_ok=True)
        (res / rel).write_bytes(b"x")
    monkeypatch.setenv("IELTS_RESOURCES", str(res))
    assert sp.list_shadowing_audios() == ["Cambridge IELTS 17/AUDIO/T1 AUDIO 1.mp3", "Cambridge IELTS 17/AUDIO/T1 AUDIO 2.mp3"]
    from ielts.ingest.schema import ListeningPart
    td = TestData(book="b", book_title="B", test=1,
                  listening=[ListeningPart(part=1, qstart=1, qend=10, audio="Cambridge IELTS 17/AUDIO/T1 AUDIO 1.mp3")])
    assert review.candidate_audios(td) == ["Cambridge IELTS 17/AUDIO/T1 AUDIO 1.mp3", "Cambridge IELTS 17/AUDIO/T1 AUDIO 2.mp3"]
    td.listening[0].audio = None
    assert len(review.candidate_audios(td)) == 4                          # sin pistas asignadas: todos los mp3


def test_audio_src_is_signed_url_in_cloud_and_local_path_otherwise(tmp_path, monkeypatch):
    from ielts import ui
    monkeypatch.setenv("IELTS_RESOURCES", str(tmp_path / "res"))
    (tmp_path / "res").mkdir()
    (tmp_path / "res" / "a.mp3").write_bytes(b"x")
    assert Path(ui.audio_src("a.mp3")) == (tmp_path / "res" / "a.mp3").resolve()
    mem = MemoryStore()
    mem.write_bytes("a.mp3", b"x")
    monkeypatch.setattr(storage, "resources_store", lambda: mem)
    assert ui.audio_src("a.mp3") == "memory://a.mp3"
    assert derived_store(tmp_path / "d").root == tmp_path / "d"
