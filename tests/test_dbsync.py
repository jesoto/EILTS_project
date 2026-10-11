import time

import httpx
import pytest

from ielts import db, dbsync
from ielts.config import LLMConfig
from ielts.llm.base import LLMError
from ielts.llm.openai_provider import OpenAIProvider
from ielts.llm.usage import DbUsage, FileUsage, calls_today, usage_summary
from ielts.storage import MemoryStore


def open_db(store, tmp_path, name="a", debounce=None):
    return dbsync.open_cloud_db(store, tmp_path / name, debounce=debounce)


def count(conn, table="error_log"):
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def test_first_run_creates_the_remote_file_and_data_survives_a_restart(tmp_path):
    store = MemoryStore()
    c1 = open_db(store, tmp_path, "run1")
    assert c1.dirty and not store.exists(dbsync.DB_KEY)               # aún no subido
    db.log_error(c1, "writing", "Is clear", "It is clear", "subject_omission")
    assert c1.flush() and store.exists(dbsync.DB_KEY) and not c1.dirty

    c1.close()                                                          # «reinicio» de la app: disco efímero nuevo
    c2 = open_db(store, tmp_path, "run2")
    assert count(c2) == 1 and not c2.dirty                              # los datos volvieron de la nube
    db.log_error(c2, "writing", "x", "y", "articles")
    assert c2.flush()
    assert count(open_db(store, tmp_path, "run3")) == 2


def test_snapshot_is_a_valid_sqlite_file(tmp_path):
    store = MemoryStore()
    c = open_db(store, tmp_path)
    db.set_level(c, "writing", 7)
    c.flush()
    import sqlite3
    probe = sqlite3.connect(":memory:")
    probe.deserialize(store.read_bytes(dbsync.DB_KEY))
    assert probe.execute("SELECT level FROM skill_level WHERE skill='writing'").fetchone()[0] == 7


def test_commit_marks_dirty_and_debounce_uploads_in_background(tmp_path):
    store = MemoryStore()
    c = open_db(store, tmp_path, debounce=0.05)
    c.flush()                                                           # sube el estado inicial
    v0 = store.version(dbsync.DB_KEY)
    for i in range(5):                                                  # ráfaga de commits → una sola subida
        db.log_error(c, "writing", f"f{i}", f"c{i}", "articles")
    assert c.dirty
    for _ in range(100):
        if not c.dirty:
            break
        time.sleep(0.02)
    assert not c.dirty and store.version(dbsync.DB_KEY) != v0
    assert int(store.version(dbsync.DB_KEY)) - int(v0) <= 2             # no una subida por commit


def test_zero_debounce_uploads_synchronously(tmp_path):
    store = MemoryStore()
    c = open_db(store, tmp_path, debounce=0)
    db.log_error(c, "writing", "a", "b", "articles")
    assert not c.dirty and store.exists(dbsync.DB_KEY)


def test_two_instances_conflict_is_detected_and_local_data_is_kept(tmp_path):
    store = MemoryStore()
    a = open_db(store, tmp_path, "a")
    a.flush()
    b = open_db(store, tmp_path, "b")                                   # segunda instancia, misma nube
    db.log_error(a, "writing", "from-a", "A", "articles")
    assert a.flush()
    db.log_error(b, "writing", "from-b", "B", "articles")
    assert not b.flush() and b.conflict and "conflicto" in b.status()["error"]
    assert count(b) == 1 and b.dirty                                    # lo local no se pierde
    assert not b.flush()                                                # bloqueado hasta resolver

    assert b.force_upload() and not b.conflict                          # elegir «sobrescribir la nube»
    assert count(open_db(store, tmp_path, "c")) == 1
    assert open_db(store, tmp_path, "d").execute("SELECT fragment FROM error_log").fetchone()[0] == "from-b"


def test_reload_from_store_discards_local_changes(tmp_path):
    store = MemoryStore()
    a = open_db(store, tmp_path, "a")
    db.log_error(a, "writing", "keep", "K", "articles")
    a.flush()
    b = open_db(store, tmp_path, "b")
    db.log_error(a, "writing", "newer", "N", "articles")
    a.flush()
    db.log_error(b, "writing", "mine", "M", "articles")
    assert not b.flush() and b.conflict
    dbsync.reload_from_store(b)
    assert not b.conflict and not b.dirty and count(b) == 2
    assert {r[0] for r in b.execute("SELECT fragment FROM error_log")} == {"keep", "newer"}


def test_network_failure_keeps_data_dirty_and_retries(tmp_path):
    class Flaky(MemoryStore):
        fail = True

        def write_bytes(self, key, data, **kw):
            if self.fail and key == dbsync.DB_KEY:
                raise OSError("sin red")
            return super().write_bytes(key, data, **kw)
    store = Flaky()
    c = open_db(store, tmp_path)
    db.log_error(c, "writing", "a", "b", "articles")
    assert not c.flush() and c.dirty and "sin red" in c.status()["error"] and not c.conflict
    store.fail = False
    assert c.flush() and not c.dirty and c.status()["error"] is None


def test_daily_backup_is_created_once_and_rotated(tmp_path, monkeypatch):
    store = MemoryStore()
    c = open_db(store, tmp_path)
    for day in range(1, 20):                                            # 19 días distintos
        monkeypatch.setenv("IELTS_TZ", "UTC")
        monkeypatch.setattr(dbsync.clock, "now", lambda d=day: __import__("datetime").datetime(2026, 11, d, 12, 0))
        c._backup_day = None
        db.log_error(c, "writing", f"f{day}", "c", "articles")
        assert c.flush()
        db.log_error(c, "writing", f"g{day}", "c", "articles")
        assert c.flush()                                                # segunda subida del mismo día: sin copia nueva
    backups = store.list(dbsync.BACKUP_PREFIX)
    assert len(backups) == dbsync.KEEP_BACKUPS
    assert backups[0] == "backups/ielts-2026-11-06.db" and backups[-1] == "backups/ielts-2026-11-19.db"
    assert store.read_bytes(backups[-1])                                # la copia no está vacía


def test_stale_local_files_do_not_resurrect_old_data(tmp_path):
    store = MemoryStore()
    c = open_db(store, tmp_path, "x")
    db.log_error(c, "writing", "old", "O", "articles")
    c.flush()
    c.close()
    store2 = MemoryStore()                                              # nube vacía, disco local con datos viejos
    fresh = open_db(store2, tmp_path, "x")
    assert count(fresh) == 0                                            # manda la nube, no el archivo local


# ---------------------------------------------------------------- gasto del LLM en la base + tope diario
def completion(usage=(100, 50)):
    return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
                                     "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}})


def test_usage_in_database_persists_with_the_synced_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    store = MemoryStore()
    c = open_db(store, tmp_path)
    p = OpenAIProvider(LLMConfig(provider="openai", price_in_per_m=1, price_out_per_m=2),
                       transport=httpx.MockTransport(lambda r: completion((1000, 500))), usage=DbUsage(c))
    p.chat("s", "u", temperature=0.2)
    c.flush()
    c2 = open_db(store, tmp_path, "again")
    s = usage_summary(cfg=LLMConfig(price_in_per_m=1, price_out_per_m=2), tracker=DbUsage(c2))
    assert (s["calls"], s["prompt_tokens"], s["completion_tokens"], s["calls_today"]) == (1, 1000, 500, 1)
    assert s["cost_usd"] == pytest.approx(0.002)


def test_daily_call_cap_blocks_before_spending(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    hits = []

    def handler(request):
        hits.append(1)
        return completion()
    tracker = FileUsage(tmp_path / "u.jsonl")
    p = OpenAIProvider(LLMConfig(provider="openai", max_calls_per_day=2), transport=httpx.MockTransport(handler), usage=tracker)
    p.chat("s", "u", temperature=0.2)
    p.chat("s", "u", temperature=0.2)
    with pytest.raises(LLMError, match="Límite diario"):
        p.chat("s", "u", temperature=0.2)
    assert len(hits) == 2 and calls_today(tracker) == 2                  # la tercera ni salió a la red
    assert OpenAIProvider(LLMConfig(provider="openai", max_calls_per_day=0), transport=httpx.MockTransport(handler),
                          usage=tracker).chat("s", "u", temperature=0.2) == "{}"       # 0 = sin tope


def test_old_calls_do_not_count_toward_todays_cap(tmp_path):
    t = FileUsage(tmp_path / "u.jsonl")
    t.path.write_text('{"ts": "2020-01-01T10:00:00", "model": "m", "prompt_tokens": 1, "completion_tokens": 1}\n', encoding="utf-8")
    assert calls_today(t) == 0 and usage_summary(tracker=t)["calls"] == 1


def test_get_conn_uses_cloud_db_in_cloud_mode(tmp_path, monkeypatch):
    import streamlit as st

    from ielts import ui
    st.cache_resource.clear()
    store = MemoryStore()
    monkeypatch.setenv("IELTS_MODE", "cloud")
    monkeypatch.setattr(dbsync, "make_store", lambda ns, root=None: store)
    monkeypatch.setattr(dbsync, "_local_dir", lambda: tmp_path / "cloud")
    conn = ui.get_conn()
    assert isinstance(conn, dbsync.SyncedConnection)
    db.log_error(conn, "writing", "a", "b", "articles")
    conn.flush()
    assert store.exists(dbsync.DB_KEY)
    st.cache_resource.clear()
