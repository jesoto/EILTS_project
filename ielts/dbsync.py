"""SQLite persistente en la nube: el archivo vive en un Store (Google Cloud Storage) y se copia al disco efímero.

- Al arrancar se descarga `ielts.db`; tras cada `commit()` se marca «sucio» y se sube con debounce (1 s por defecto).
- Subida atómica con control de versión (generation de GCS): si otra instancia escribió antes → conflicto (no se pierde nada local).
- Copia diaria `backups/ielts-AAAA-MM-DD.db`, se conservan las últimas 14.
"""
from __future__ import annotations

import atexit
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from . import clock, db
from .storage import ConflictError, Store, make_store

DB_KEY = "ielts.db"
BACKUP_PREFIX = "backups/ielts-"
KEEP_BACKUPS = 14
DEBOUNCE_SECONDS = 1.0


class SyncedConnection(sqlite3.Connection):
    """Conexión SQLite que sube el archivo al Store después de cada commit."""

    # Valores por defecto de clase: db.connect() hace commit() del esquema antes de que se llame a attach().
    store: Store | None = None
    version: str | None = None
    debounce: float | None = None
    dirty: bool = False
    conflict: bool = False
    last_error: str | None = None
    last_upload: float | None = None
    _backup_day: str | None = None
    _timer: threading.Timer | None = None
    _lock = threading.RLock()

    # -- configuración (no se puede usar __init__ con sqlite3.connect(factory=...))
    def attach(self, store: Store, version: str | None, debounce: float | None) -> None:
        self.store, self.version, self.debounce = store, version, debounce
        self.dirty, self.conflict, self.last_error, self.last_upload = False, False, None, None
        self._backup_day, self._timer, self._lock = None, None, threading.RLock()

    # -- API de sqlite3
    def commit(self):
        super().commit()
        self._mark_dirty()

    # -- sincronización
    def _mark_dirty(self) -> None:
        with self._lock:
            self.dirty = True
            if self.debounce is None or self._timer is not None:
                return
            if self.debounce <= 0:
                self.flush()
                return
            self._timer = threading.Timer(self.debounce, self._timer_fired)
            self._timer.daemon = True
            self._timer.start()

    def _timer_fired(self) -> None:
        with self._lock:
            self._timer = None
        self.flush()

    def _snapshot(self) -> bytes:
        """Copia consistente de la base (aunque otro hilo esté escribiendo)."""
        mem = sqlite3.connect(":memory:")
        try:
            self.backup(mem)
            return mem.serialize()
        finally:
            mem.close()

    def flush(self) -> bool:
        """Sube los cambios pendientes. Devuelve True si quedó sincronizado."""
        with self._lock:
            if not self.dirty or self.conflict:
                return not self.dirty
            try:
                data = self._snapshot()
                self.version = self.store.write_bytes(DB_KEY, data, content_type="application/x-sqlite3",
                                                      if_version=self.version)
                self.dirty, self.last_error, self.last_upload = False, None, time.time()
                self._daily_backup(data)
                return True
            except ConflictError as e:
                self.conflict, self.last_error = True, f"conflicto: {e}"
                return False
            except Exception as e:  # noqa: BLE001 — red caída: se reintentará en el siguiente commit
                self.last_error = f"{type(e).__name__}: {e}"
                return False

    def _daily_backup(self, data: bytes) -> None:
        day = clock.now().date().isoformat()
        if self._backup_day == day:
            return
        try:
            key = f"{BACKUP_PREFIX}{day}.db"
            if not self.store.exists(key):
                self.store.write_bytes(key, data, content_type="application/x-sqlite3")
            for old in sorted(k for k in self.store.list(BACKUP_PREFIX))[:-KEEP_BACKUPS]:
                self.store.delete(old)
            self._backup_day = day
        except Exception:  # noqa: BLE001 — la copia diaria nunca debe romper la sincronización
            pass

    # -- resolución manual de conflictos
    def force_upload(self) -> bool:
        """Sobrescribe la nube con la copia local (descarta lo que escribió la otra instancia)."""
        with self._lock:
            self.version = self.store.version(DB_KEY)
            self.conflict, self.dirty = False, True
            return self.flush()

    def status(self) -> dict:
        return {"dirty": self.dirty, "conflict": self.conflict, "error": self.last_error,
                "last_upload": self.last_upload, "version": self.version}


def _local_dir() -> Path:
    return Path(tempfile.gettempdir()) / "ielts_cloud"


def open_cloud_db(store: Store | None = None, local_dir: Path | None = None,
                  debounce: float | None = DEBOUNCE_SECONDS) -> SyncedConnection:
    """Descarga la base del Store (si existe) y devuelve la conexión sincronizada."""
    store = store or make_store("db")
    local_dir = Path(local_dir) if local_dir else _local_dir()
    local_dir.mkdir(parents=True, exist_ok=True)
    path = local_dir / "ielts.db"
    for stale in local_dir.glob("ielts.db*"):
        stale.unlink()
    version = store.version(DB_KEY)
    existed = version is not None
    if existed:
        path.write_bytes(store.read_bytes(DB_KEY))
    conn = db.connect(path, factory=SyncedConnection)
    conn.attach(store, version, debounce)
    if not existed:
        conn._mark_dirty()                    # primera vez: crea el archivo en la nube
    atexit.register(conn.flush)
    return conn


def reload_from_store(conn: SyncedConnection) -> None:
    """Descarta lo local y vuelve a bajar la versión de la nube (tras un conflicto)."""
    data = conn.store.read_bytes(DB_KEY)
    src = sqlite3.connect(":memory:")
    src.deserialize(data)
    with conn._lock:
        src.backup(conn)
        conn.version = conn.store.version(DB_KEY)
        conn.conflict, conn.dirty, conn.last_error = False, False, None
    src.close()
