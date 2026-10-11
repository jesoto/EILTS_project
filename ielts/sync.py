"""Subida de tus datos locales al bucket privado (tests extraídos, audios usados, base de datos, grabaciones).

Lógica pura y testeable: `scripts/sync_to_cloud.py` solo pide confirmación y la ejecuta. Nunca cambia permisos del bucket.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .storage import ConflictError, GCSStore, Store

CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".mp3": "audio/mpeg", ".wav": "audio/wav",
                 ".db": "application/x-sqlite3"}


@dataclass
class Item:
    namespace: str          # derived | resources | recordings | db
    key: str                # clave dentro del namespace
    src: Path | None        # archivo local (None si son bytes en memoria)
    size: int
    action: str = "new"     # new | changed | same | blocked
    note: str = ""
    data: bytes | None = None

    @property
    def label(self) -> str:
        return f"{self.namespace}/{self.key}"


def cloud_stores(bucket: str, client=None) -> dict[str, Store]:
    return {ns: GCSStore(bucket, ns + "/", client=client) for ns in ("derived", "resources", "recordings", "db")}


def _ctype(p: Path | str) -> str:
    return CONTENT_TYPES.get(Path(str(p)).suffix.lower(), "application/octet-stream")


def collect_derived(derived_dir: Path) -> list[Item]:
    if not derived_dir.exists():
        return []
    return [Item("derived", str(p.relative_to(derived_dir)).replace("\\", "/"), p, p.stat().st_size)
            for p in sorted(derived_dir.rglob("*")) if p.is_file()]


def referenced_audio(derived_dir: Path) -> list[str]:
    """Audios (claves relativas a resources/) que usan los tests ya extraídos."""
    from .ingest.schema import list_tests
    keys: set[str] = set()
    for t in list_tests(derived_dir):
        keys |= {p.audio for p in t.listening if p.audio}
    return sorted(keys)


def collect_audio(resources_dir: Path, derived_dir: Path, all_cambridge: bool = False) -> list[Item]:
    keys = set(referenced_audio(derived_dir))
    if all_cambridge:
        keys |= {str(p.relative_to(resources_dir)).replace("\\", "/") for p in resources_dir.rglob("*.mp3")
                 if "cambr" in str(p).lower() and "grammar" not in str(p).lower()}
    items = []
    for k in sorted(keys):
        p = resources_dir / k
        items.append(Item("resources", k, p, p.stat().st_size) if p.is_file()
                     else Item("resources", k, None, 0, "blocked", "no existe en resources/"))
    return items


def db_snapshot(db_path: Path) -> bytes:
    """Copia consistente de la base local, aunque la app la tenga abierta."""
    src = sqlite3.connect(str(db_path))
    mem = sqlite3.connect(":memory:")
    try:
        src.backup(mem)
        return mem.serialize()
    finally:
        mem.close()
        src.close()


def collect_db(db_path: Path) -> list[Item]:
    if not db_path.exists():
        return []
    data = db_snapshot(db_path)
    return [Item("db", "ielts.db", None, len(data), data=data)]


def collect_recordings(rec_dir: Path) -> list[Item]:
    if not rec_dir.exists():
        return []
    return [Item("recordings", p.name, p, p.stat().st_size) for p in sorted(rec_dir.glob("*.wav"))]


def plan(items: list[Item], stores: dict[str, Store], force_db: bool = False) -> list[Item]:
    """Marca cada elemento: new / changed (tamaño distinto) / same / blocked. La base solo se sobrescribe con force_db."""
    for it in items:
        if it.action == "blocked":
            continue
        remote = stores[it.namespace].size(it.key)
        if it.namespace == "db":
            if remote is None:
                it.action = "new"
            elif force_db:
                it.action, it.note = "changed", "sobrescribe la base de datos de la nube"
            else:
                it.action, it.note = "blocked", "ya existe en la nube (puede tener datos más nuevos): usa --force-db"
            continue
        it.action = "new" if remote is None else ("same" if remote == it.size else "changed")
    return items


def summarize(items: list[Item]) -> dict:
    todo = [i for i in items if i.action in ("new", "changed")]
    return {"upload": len(todo), "bytes": sum(i.size for i in todo), "same": sum(i.action == "same" for i in items),
            "blocked": [i for i in items if i.action == "blocked"]}


def execute(items: list[Item], stores: dict[str, Store], force_db: bool = False, progress=None) -> dict:
    done = failed = 0
    errors: list[str] = []
    for it in items:
        if it.action not in ("new", "changed"):
            continue
        try:
            data = it.data if it.data is not None else it.src.read_bytes()
            kw = {"content_type": _ctype(it.key)}
            if it.namespace == "db" and not force_db:
                kw["if_version"] = None          # solo crear: jamás pisa datos de la nube por accidente
            stores[it.namespace].write_bytes(it.key, data, **kw)
            done += 1
        except ConflictError:
            failed += 1
            errors.append(f"{it.label}: ya existe en la nube")
        except Exception as e:  # noqa: BLE001
            failed += 1
            errors.append(f"{it.label}: {type(e).__name__}: {e}")
        if progress:
            progress(it, done, failed)
    return {"uploaded": done, "failed": failed, "errors": errors}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
