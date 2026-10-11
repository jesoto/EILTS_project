"""Almacenamiento de archivos: carpeta local (modo local) o Google Cloud Storage (modo cloud).

Todas las claves son rutas relativas con «/». Cada *espacio* (derived, resources, recordings, db) es una Store distinta.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from .config import ROOT, load_app_config, secret, secret_section

ANY = object()      # «no importa la versión» al escribir


class ConflictError(RuntimeError):
    """La versión del objeto cambió desde que se leyó (otra sesión escribió antes)."""


class Store(ABC):
    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def write_bytes(self, key: str, data: bytes, *, content_type: str | None = None, if_version=ANY) -> str:
        """Guarda y devuelve la nueva versión. if_version=None → solo crear; str → debe coincidir con la actual."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list(self, prefix: str = "") -> list[str]: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def version(self, key: str) -> str | None: ...

    def url(self, key: str, expires: int = 3600) -> str | None:
        """URL temporal para que el navegador lea el archivo (solo nube); None si no aplica."""
        return None

    def local_path(self, key: str) -> Path | None:
        """Ruta en disco si el backend es local; None en la nube."""
        return None

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def write_text(self, key: str, text: str, **kw) -> str:
        return self.write_bytes(key, text.encode("utf-8"), **kw)


def _check_version(current: str | None, if_version) -> None:
    if if_version is ANY:
        return
    if if_version is None and current is not None:
        raise ConflictError("el objeto ya existe")
    if if_version is not None and current != if_version:
        raise ConflictError(f"versión esperada {if_version}, actual {current}")


class DirStore(Store):
    """Una carpeta del disco."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"clave fuera de la carpeta: {key}")
        return p

    def read_bytes(self, key):
        p = self._p(key)
        if not p.is_file():
            raise FileNotFoundError(key)
        return p.read_bytes()

    def version(self, key):
        p = self._p(key)
        if not p.is_file():
            return None
        st = p.stat()
        return f"{st.st_mtime_ns}-{st.st_size}"

    def write_bytes(self, key, data, *, content_type=None, if_version=ANY):
        _check_version(self.version(key), if_version)
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)             # escritura atómica
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.version(key)

    def exists(self, key):
        return self._p(key).is_file()

    def list(self, prefix=""):
        if not self.root.exists():
            return []
        out = [str(p.relative_to(self.root)).replace("\\", "/") for p in self.root.rglob("*")
               if p.is_file() and not p.name.startswith(".tmp-")]
        return sorted(k for k in out if k.startswith(prefix))

    def delete(self, key):
        p = self._p(key)
        if p.is_file():
            p.unlink()

    def local_path(self, key):
        return self._p(key)


class MemoryStore(Store):
    """En memoria: para tests y para simular la nube sin red."""

    def __init__(self):
        self._d: dict[str, tuple[bytes, int]] = {}
        self._n = 0

    def read_bytes(self, key):
        if key not in self._d:
            raise FileNotFoundError(key)
        return self._d[key][0]

    def version(self, key):
        return str(self._d[key][1]) if key in self._d else None

    def write_bytes(self, key, data, *, content_type=None, if_version=ANY):
        _check_version(self.version(key), if_version)
        self._n += 1
        self._d[key] = (bytes(data), self._n)
        return str(self._n)

    def exists(self, key):
        return key in self._d

    def list(self, prefix=""):
        return sorted(k for k in self._d if k.startswith(prefix))

    def delete(self, key):
        self._d.pop(key, None)

    def url(self, key, expires=3600):
        return f"memory://{key}" if key in self._d else None


class GCSStore(Store):
    """Un prefijo dentro de un bucket de Google Cloud Storage (privado)."""

    def __init__(self, bucket: str, prefix: str = "", client=None):
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        self._client = client
        self._bucket_name = bucket
        self._bucket = None

    @property
    def bucket(self):
        if self._bucket is None:
            client = self._client or gcs_client()
            self._client = client
            self._bucket = client.bucket(self._bucket_name)
        return self._bucket

    def _blob(self, key):
        return self.bucket.blob(self.prefix + key)

    def read_bytes(self, key):
        blob = self._blob(key)
        try:
            return blob.download_as_bytes()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) == 404 or e.__class__.__name__ == "NotFound":
                raise FileNotFoundError(key) from e
            raise

    def version(self, key):
        blob = self.bucket.get_blob(self.prefix + key)
        return str(blob.generation) if blob is not None else None

    def write_bytes(self, key, data, *, content_type=None, if_version=ANY):
        blob = self._blob(key)
        kwargs = {}
        if if_version is None:
            kwargs["if_generation_match"] = 0
        elif if_version is not ANY:
            kwargs["if_generation_match"] = int(if_version)
        try:
            blob.upload_from_string(data, content_type=content_type or "application/octet-stream", **kwargs)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) == 412 or e.__class__.__name__ == "PreconditionFailed":
                raise ConflictError(str(e)) from e
            raise
        return str(blob.generation)

    def exists(self, key):
        return self._blob(key).exists()

    def list(self, prefix=""):
        _ = self.bucket                      # inicializa el cliente
        n = len(self.prefix)
        return sorted(b.name[n:] for b in self._client.list_blobs(self._bucket_name, prefix=self.prefix + prefix)
                      if not b.name.endswith("/"))

    def delete(self, key):
        blob = self._blob(key)
        if blob.exists():
            blob.delete()

    def url(self, key, expires=3600):
        return self._blob(key).generate_signed_url(version="v4", expiration=timedelta(seconds=expires), method="GET")


@lru_cache(maxsize=1)
def gcs_client():
    """Cliente de GCS con la cuenta de servicio de los secrets (`gcp_service_account`); si no hay, credenciales por defecto."""
    from google.cloud import storage
    info = secret_section("gcp_service_account")
    if info:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(info)
        return storage.Client(project=info.get("project_id"), credentials=creds)
    return storage.Client()


# ------------------------------------------------------------------ fábricas
def _local_roots() -> dict[str, Path]:
    return {
        "resources": Path(os.environ.get("IELTS_RESOURCES") or ROOT / "resources"),
        "recordings": Path(os.environ.get("IELTS_RECORDINGS") or ROOT / "data" / "recordings"),
        "derived": Path(os.environ.get("IELTS_DERIVED") or ROOT / "data" / "derived"),
    }


def make_store(namespace: str, local_root: Path | None = None) -> Store:
    """Store del espacio `namespace`: GCS en modo cloud, carpeta local en modo local."""
    if load_app_config().is_cloud:
        bucket = secret("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("Modo cloud sin GCS_BUCKET: defínelo en los secrets de Streamlit.")
        return GCSStore(bucket, namespace + "/")
    return DirStore(local_root or _local_roots()[namespace])


def resources_store() -> Store:
    return make_store("resources")


def recordings_store() -> Store:
    return make_store("recordings")


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]
