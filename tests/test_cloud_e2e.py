import sqlite3
import threading
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from ielts import auth, dbsync, doctor, storage, sync
from ielts.ingest import schema
from ielts.ingest.schema import ListeningPart, TestData, save_test
from ielts.storage import GCSStore, MemoryStore

from .test_ingest import mk_test
from .test_storage import FakeBlob, FakeBucket, FakeClient

APP = str(Path(__file__).resolve().parent.parent / "app.py")


# ---------------------------------------------------------------- plan y subida
def local_tree(tmp_path):
    derived = tmp_path / "derived"
    (derived / "c17" / "images").mkdir(parents=True)
    td = TestData(book="c17", book_title="C17", test=1, listening=[
        ListeningPart(part=1, qstart=1, qend=10, audio="Book/Audios/T1 AUDIO 1.mp3"),
        ListeningPart(part=2, qstart=11, qend=20, audio="Book/Audios/T1 AUDIO 2.mp3"),
        ListeningPart(part=3, qstart=21, qend=30, audio="Book/Missing.mp3"),
        ListeningPart(part=4, qstart=31, qend=40, audio=None)])
    save_test(td, derived)
    (derived / "c17" / "images" / "k.png").write_bytes(b"\x89PNG-k")
    res = tmp_path / "res"
    (res / "Book" / "Audios").mkdir(parents=True)
    (res / "Book" / "Audios" / "T1 AUDIO 1.mp3").write_bytes(b"a" * 100)
    (res / "Book" / "Audios" / "T1 AUDIO 2.mp3").write_bytes(b"b" * 200)
    (res / "Book" / "Audios" / "OTHER CAMBRIDGE.mp3").write_bytes(b"c" * 50)
    (res / "Book" / "libro.pdf").write_bytes(b"%PDF" * 1000)
    db = tmp_path / "ielts.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "w1_p2.wav").write_bytes(b"RIFF")
    return derived, res, db, rec, con


def new_stores():
    return {ns: MemoryStore() for ns in ("derived", "resources", "recordings", "db")}


def test_collect_only_what_the_tests_use_and_never_the_pdf(tmp_path):
    derived, res, db, rec, con = local_tree(tmp_path)
    audio = sync.collect_audio(res, derived)
    assert [(i.key, i.action) for i in audio] == [("Book/Audios/T1 AUDIO 1.mp3", "new"), ("Book/Audios/T1 AUDIO 2.mp3", "new"),
                                                  ("Book/Missing.mp3", "blocked")]
    assert not [i for i in audio if i.key.endswith(".pdf")]
    assert "OTHER CAMBRIDGE.mp3" not in {i.key.split("/")[-1] for i in audio}
    assert len(sync.collect_audio(res, derived, all_cambridge=False)) == 3
    assert {i.key for i in sync.collect_derived(derived)} == {"c17/test1.json", "c17/images/k.png"}
    assert [i.key for i in sync.collect_recordings(rec)] == ["w1_p2.wav"]
    assert sync.collect_db(tmp_path / "no.db") == [] and sync.collect_derived(tmp_path / "no") == []
    con.close()


def test_plan_execute_is_incremental_and_never_overwrites_the_cloud_db_by_accident(tmp_path):
    derived, res, db, rec, con = local_tree(tmp_path)
    stores = new_stores()

    def everything():
        return (sync.collect_derived(derived) + sync.collect_audio(res, derived) + sync.collect_db(db)
                + sync.collect_recordings(rec))
    items = sync.plan(everything(), stores)
    s = sync.summarize(items)
    assert s["upload"] == 6 and [b.label for b in s["blocked"]] == ["resources/Book/Missing.mp3"]       # json, png, 2 mp3, db, wav
    report = sync.execute(items, stores)
    assert report == {"uploaded": 6, "failed": 0, "errors": []}
    assert stores["resources"].read_bytes("Book/Audios/T1 AUDIO 2.mp3") == b"b" * 200
    assert stores["resources"].list() == ["Book/Audios/T1 AUDIO 1.mp3", "Book/Audios/T1 AUDIO 2.mp3"]    # el PDF no se sube
    snapshot = sqlite3.connect(":memory:")
    snapshot.deserialize(stores["db"].read_bytes("ielts.db"))
    assert snapshot.execute("SELECT x FROM t").fetchone()[0] == 1

    # segunda pasada: todo igual → nada que subir; la DB queda bloqueada para no pisar datos de la nube
    again = sync.plan(everything(), stores)
    assert sync.summarize(again)["upload"] == 0 and {i.action for i in again if i.namespace != "db"} <= {"same", "blocked"}
    assert [i.action for i in again if i.namespace == "db"] == ["blocked"] and "--force-db" in [i for i in again if i.namespace == "db"][0].note

    # cambia un audio (otro tamaño) y la DB local: solo sube el audio; con force_db también la base
    (res / "Book" / "Audios" / "T1 AUDIO 1.mp3").write_bytes(b"z" * 300)
    con.execute("INSERT INTO t VALUES (2)")
    con.commit()
    changed = sync.plan(everything(), stores)
    assert [i.label for i in changed if i.action == "changed"] == ["resources/Book/Audios/T1 AUDIO 1.mp3"]
    forced = sync.plan(everything(), stores, force_db=True)
    assert "db/ielts.db" in [i.label for i in forced if i.action == "changed"]
    sync.execute(forced, stores, force_db=True)
    snapshot2 = sqlite3.connect(":memory:")
    snapshot2.deserialize(stores["db"].read_bytes("ielts.db"))
    assert snapshot2.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    con.close()


def test_db_race_after_planning_is_reported_not_overwritten(tmp_path):
    derived, res, db, rec, con = local_tree(tmp_path)
    stores = new_stores()
    items = sync.plan(sync.collect_db(db), stores)
    stores["db"].write_bytes("ielts.db", b"datos nuevos de la nube")                  # alguien la crea entre plan y subida
    report = sync.execute(items, stores)
    assert report["uploaded"] == 0 and report["failed"] == 1 and "ya existe" in report["errors"][0]
    assert stores["db"].read_bytes("ielts.db") == b"datos nuevos de la nube"
    con.close()


def test_snapshot_of_a_database_being_written_is_valid(tmp_path):
    derived, res, db, rec, con = local_tree(tmp_path)
    stop = threading.Event()

    def writer():
        c = sqlite3.connect(db)
        i = 0
        while not stop.is_set():
            c.execute("INSERT INTO t VALUES (?)", (i,))
            c.commit()
            i += 1
    th = threading.Thread(target=writer)
    th.start()
    try:
        for _ in range(5):
            data = sync.db_snapshot(db)
            probe = sqlite3.connect(":memory:")
            probe.deserialize(data)
            assert probe.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        stop.set()
        th.join()
        con.close()


def test_human_sizes():
    assert [sync.human(n) for n in (10, 2048, 5 * 1024 ** 2, 3 * 1024 ** 3)] == ["10 B", "2.0 KB", "5.0 MB", "3.0 GB"]


# ---------------------------------------------------------------- caché de lectura en la nube
def test_remote_list_tests_is_cached_invalidated_on_save_and_returns_copies(monkeypatch):
    client = FakeClient()
    store = GCSStore("bkt", "derived/", client=client)
    monkeypatch.setattr(schema, "derived_store", lambda root=None: store)
    schema.clear_cache()
    calls = {"n": 0}
    real = client.list_blobs

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(client, "list_blobs", counting)

    save_test(TestData(book="b", book_title="B", test=1))
    first = schema.list_tests()
    assert len(first) == 1 and calls["n"] == 1
    first[0].verified = True                                                         # la página de verificación edita en sitio…
    assert not schema.list_tests()[0].verified and calls["n"] == 1                   # …sin ensuciar la caché ni releer
    save_test(TestData(book="b", book_title="B", test=2))                            # guardar invalida
    assert len(schema.list_tests()) == 2 and calls["n"] == 2
    monkeypatch.setattr(schema, "LIST_CACHE_TTL", 0)                                  # TTL vencido: relee
    schema.list_tests()
    assert calls["n"] == 3
    schema.clear_cache()


def test_local_and_memory_stores_are_never_cached(tmp_path, monkeypatch):
    mem = MemoryStore()
    monkeypatch.setattr(schema, "derived_store", lambda root=None: mem)
    save_test(TestData(book="b", book_title="B", test=1))
    assert len(schema.list_tests()) == 1
    mem.delete("b/test1.json")
    assert schema.list_tests() == []                                                  # sin caché: ve el borrado al instante


# ---------------------------------------------------------------- bucket privado (diagnóstico)
class FakeIam:
    def __init__(self, prevention):
        self.public_access_prevention, self.uniform_bucket_level_access_enabled = prevention, True


class SecuredBucket(FakeBucket):
    prevention = "enforced"

    @property
    def iam_configuration(self):
        return FakeIam(self.prevention)

    def reload(self):
        pass


class SecuredClient(FakeClient):
    prevention = "enforced"

    def bucket(self, name):
        b = self.buckets.setdefault(name, SecuredBucket(name))
        b.prevention = self.prevention
        return b


def test_doctor_warns_when_the_bucket_is_not_protected_against_public_access(monkeypatch):
    monkeypatch.setenv("IELTS_MODE", "cloud")
    for prevention, expected in (("enforced", doctor.OK), ("inherited", doctor.WARN), (None, doctor.WARN)):
        client = SecuredClient()
        client.prevention = prevention
        monkeypatch.setattr(storage, "make_store", lambda ns, root=None, c=client: GCSStore("bkt", ns + "/", client=c))
        checks = {c.id: c for c in doctor.run_live_checks()}
        assert checks["live_gcs"].status == doctor.OK and checks["live_gcs_private"].status == expected
        if expected == doctor.WARN:
            assert "Prevención de acceso público" in checks["live_gcs_private"].fix


# ---------------------------------------------------------------- recorrido completo en «cloud» simulado
class U:
    is_logged_in, email, name, email_verified = True, "yo@gmail.com", "Yo", True


@pytest.fixture()
def cloud_world(monkeypatch, tmp_path):
    st.cache_resource.clear()
    schema.clear_cache()
    stores = {ns: MemoryStore() for ns in ("derived", "resources", "recordings", "db")}
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setenv("ALLOWED_EMAILS", "yo@gmail.com")
    monkeypatch.setenv("IELTS_TZ", "America/Lima")
    monkeypatch.setattr("ielts.config.ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr(storage, "make_store", lambda ns, root=None: stores[ns])
    monkeypatch.setattr(dbsync, "make_store", lambda ns, root=None: stores[ns])
    monkeypatch.setattr(dbsync, "_local_dir", lambda: tmp_path / "ephemeral")
    monkeypatch.setattr(auth, "_user", lambda: U())
    yield stores
    st.cache_resource.clear()
    schema.clear_cache()


def seed_cloud(stores):
    td = mk_test(verified=True)
    td.listening = [ListeningPart(part=1, qstart=1, qend=1, audio="Book/Audios/T1 AUDIO 1.mp3")]
    stores["derived"].write_bytes("tb/test1.json", td.model_dump_json().encode("utf-8"))
    stores["resources"].write_bytes("Book/Audios/T1 AUDIO 1.mp3", b"ID3fake")


def run_wednesday(week=1):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["session"] = {"weekday": "wednesday", "week": week, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    return at


def test_cloud_run_uses_bucket_data_and_persists_progress_across_a_restart(cloud_world, monkeypatch):
    stores = cloud_world
    seed_cloud(stores)
    at = run_wednesday()
    assert not at.exception, at.exception
    assert any("Test Book · Test 1 · Pasaje 1" in m.value for m in at.markdown)       # los tests salieron del bucket
    pre = "rc_1_wednesday_reading_tb/test1_ans_"
    for q, v in {1: "TRUE", 2: "FALSE", 3: "NOT GIVEN", 6: "D", 7: "A"}.items():
        at.selectbox(key=pre + str(q)).select(v)
    at.text_input(key=pre + "4").input("orangutan")
    at.text_input(key=pre + "5").input("floors")
    next(b for b in at.button if b.label.startswith("Corregir")).click().run()
    assert not at.exception, at.exception
    assert any(m.label == "Aciertos" and m.value == "7/7" for m in at.metric)

    from ielts import ui
    conn = ui.get_conn()
    assert isinstance(conn, dbsync.SyncedConnection) and conn.dirty
    assert conn.flush() and stores["db"].exists(dbsync.DB_KEY)

    # «reinicio» de Streamlit Cloud: se pierde el disco y la caché; todo vuelve del bucket
    conn.close()
    st.cache_resource.clear()
    fresh = ui.get_conn()
    assert fresh.execute("SELECT COUNT(*) FROM receptive_attempt").fetchone()[0] == 1
    assert fresh.execute("SELECT raw, total FROM receptive_attempt").fetchone()[:2] == (7, 7)


def test_cloud_listening_gets_a_signed_style_url_not_a_local_path(cloud_world, monkeypatch):
    stores = cloud_world
    seed_cloud(stores)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["session"] = {"weekday": "tuesday", "week": 1, "phase": 1, "diagnostic": False}
    at.switch_page("pages/1_Sesion.py").run()
    assert not at.exception, at.exception
    assert any("Parte 1" in m.value for m in at.markdown if m.value.startswith("## "))


def test_cloud_without_login_exposes_nothing_from_the_bucket(cloud_world, monkeypatch):
    seed_cloud(cloud_world)

    class Anon:
        is_logged_in = False
    monkeypatch.setattr(auth, "_user", lambda: Anon())
    at = run_wednesday()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Test Book" not in text and not at.metric and any(b.key == "auth_login" for b in at.button)
    assert not cloud_world["db"].exists(dbsync.DB_KEY)                                # ni siquiera se tocó la base
