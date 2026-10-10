"""Conversión de raw score a banda (Academic) y redondeo del overall.

Los tramos 23+ coinciden con CLAUDE.md; los inferiores y 37+ completan la
tabla oficial publicada de IELTS Academic.
"""
from __future__ import annotations

from collections.abc import Iterable

# (raw mínimo, banda) en orden descendente
_READING = [(39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5), (23, 6.0),
            (19, 5.5), (15, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5)]
_LISTENING = [(39, 9.0), (37, 8.5), (35, 8.0), (32, 7.5), (30, 7.0), (26, 6.5), (23, 6.0),
              (18, 5.5), (16, 5.0), (13, 4.5), (11, 4.0), (8, 3.5), (6, 3.0), (4, 2.5)]


def _lookup(table: list[tuple[int, float]], raw: int) -> float:
    if not 0 <= raw <= 40:
        raise ValueError(f"raw score fuera de rango: {raw}")
    for minimum, band in table:
        if raw >= minimum:
            return band
    return 2.0


def reading_band(raw: int) -> float:
    return _lookup(_READING, raw)


def listening_band(raw: int) -> float:
    return _lookup(_LISTENING, raw)


def round_band(values: Iterable[float]) -> float:
    """Promedio redondeado a 0.5: .25 → .5 y .75 → siguiente entero.

    Aritmética entera (medias bandas ×2) para evitar errores de coma flotante.
    """
    halves = [round(v * 2) for v in values]
    if not halves:
        raise ValueError("se necesita al menos un valor")
    # media en bandas = sum/(2n); redondeo a 0.5 con empate hacia arriba
    return ((2 * sum(halves) + len(halves)) // (2 * len(halves))) / 2


def overall_band(listening: float, reading: float, writing: float, speaking: float) -> float:
    return round_band([listening, reading, writing, speaking])


def checkpoint_advice(overall: float) -> str:
    """Punto de control del 22 nov."""
    if overall >= 6.0:
        return "keep"        # mantener fecha
    if overall < 5.5:
        return "reschedule"  # sugerir mover el examen
    return "consult"         # consultarlo con la profesora
