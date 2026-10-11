"""Reloj único de la app: zona horaria configurable (el servidor de Streamlit Cloud está en UTC)."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import load_app_config


def tz() -> ZoneInfo | None:
    name = load_app_config().timezone
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def now() -> datetime:
    """Hora actual en la zona configurada, sin tzinfo (la app guarda fechas ISO ingenuas)."""
    zone = tz()
    return datetime.now(zone).replace(tzinfo=None) if zone else datetime.now()


def today() -> date:
    """Hoy en la zona configurada; IELTS_TODAY=YYYY-MM-DD simula otra fecha al probar."""
    override = os.environ.get("IELTS_TODAY")
    return date.fromisoformat(override) if override else now().date()


def timestamp() -> str:
    return now().isoformat(timespec="seconds")
