"""Gráficos sintéticos de Writing Task 1 (matplotlib, datos inventados con semilla)."""
from __future__ import annotations

import io
import random
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CHART_TYPES = ["line", "bar", "pie", "table", "mixed"]

_SCENARIOS = [
    ("the percentage of households with internet access", "%", ["Canada", "Brazil", "Japan"]),
    ("the number of international students (in thousands)", "thousands", ["UK", "Australia", "Canada"]),
    ("average weekly hours of exercise", "hours", ["Men", "Women", "Teenagers"]),
    ("annual electricity consumption per person (MWh)", "MWh", ["Urban", "Rural", "Industrial"]),
    ("the percentage of people who commute by public transport", "%", ["City A", "City B", "City C"]),
]
_PIE_SCENARIOS = [
    ("how a typical household spent its monthly income", ["Housing", "Food", "Transport", "Leisure", "Savings", "Other"]),
    ("sources of electricity in one country", ["Coal", "Gas", "Nuclear", "Wind", "Solar", "Other"]),
]


@dataclass
class ChartTask:
    kind: str
    prompt: str          # enunciado oficial-style en inglés
    png: bytes
    data_text: str       # descripción de los datos para el evaluador LLM


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _series(rng: random.Random, n_series: int, years: list[int], lo: int, hi: int) -> dict[int, list[int]]:
    out = {}
    for i in range(n_series):
        start = rng.randint(lo, hi)
        trend = rng.choice([-1, 1]) * rng.randint(2, max(3, (hi - lo) // 6))
        vals = [max(1, start + trend * k + rng.randint(-3, 3)) for k in range(len(years))]
        out[i] = vals
    return out


def make_chart(kind: str, seed: int | None = None) -> ChartTask:
    rng = random.Random(seed)
    suffix = ("Summarise the information by selecting and reporting the main features, "
              "and make comparisons where relevant.\n\nWrite at least 150 words.")
    if kind == "pie":
        topic, cats = rng.choice(_PIE_SCENARIOS)
        years = [rng.choice([1990, 2000, 2005]), rng.choice([2015, 2020])]
        fig, axes = plt.subplots(1, 2, figsize=(8, 4))
        lines = []
        for ax, y in zip(axes, years):
            raw = [rng.randint(5, 40) for _ in cats]
            vals = [round(v * 100 / sum(raw)) for v in raw]
            vals[0] += 100 - sum(vals)
            ax.pie(vals, labels=[f"{c} {v}%" for c, v in zip(cats, vals)], startangle=90)
            ax.set_title(str(y))
            lines.append(f"{y}: " + ", ".join(f"{c} {v}%" for c, v in zip(cats, vals)))
        return ChartTask(kind, f"The pie charts below show {topic} in {years[0]} and {years[1]}.\n\n{suffix}",
                         _png(fig), "\n".join(lines))
    topic, unit, groups = rng.choice(_SCENARIOS)
    if kind == "table":
        years = sorted(rng.sample(range(1995, 2021, 5), 4))
        data = _series(rng, len(groups), years, 20, 80)
        fig, ax = plt.subplots(figsize=(7, 1.4 + 0.4 * len(groups)))
        ax.axis("off")
        tbl = ax.table(cellText=[[str(v) for v in data[i]] for i in range(len(groups))],
                       rowLabels=groups, colLabels=[str(y) for y in years], loc="center")
        tbl.scale(1, 1.6)
        text = "\n".join(f"{g}: " + ", ".join(f"{y}={v}" for y, v in zip(years, data[i])) for i, g in enumerate(groups))
        return ChartTask(kind, f"The table below shows {topic} in three groups between {years[0]} and {years[-1]}.\n\n{suffix}",
                         _png(fig), text)
    years = sorted(rng.sample(range(1990, 2021, 5), 5))
    data = _series(rng, len(groups), years, 20, 70)
    text = "\n".join(f"{g}: " + ", ".join(f"{y}={v}" for y, v in zip(years, data[i])) for i, g in enumerate(groups))
    fig, ax = plt.subplots(figsize=(7, 4))
    if kind == "bar":
        w = 0.8 / len(groups)
        for i, g in enumerate(groups):
            ax.bar([x + i * w for x in range(len(years))], data[i], w, label=g)
        ax.set_xticks([x + w for x in range(len(years))], [str(y) for y in years])
        verb = "bar chart"
    elif kind == "mixed":
        w = 0.6
        ax.bar(range(len(years)), data[0], w, label=groups[0], color="#9ecae1")
        ax2 = ax.twinx()
        ax2.plot(range(len(years)), data[1], "o-", color="#d94801", label=groups[1])
        ax.set_xticks(range(len(years)), [str(y) for y in years])
        ax.set_ylabel(f"{groups[0]} ({unit})")
        ax2.set_ylabel(f"{groups[1]} ({unit})")
        text = f"Bars ({groups[0]}): " + ", ".join(f"{y}={v}" for y, v in zip(years, data[0])) + \
               f"\nLine ({groups[1]}): " + ", ".join(f"{y}={v}" for y, v in zip(years, data[1]))
        verb = "bar chart and line graph"
    else:
        for i, g in enumerate(groups):
            ax.plot(years, data[i], marker="o", label=g)
        verb = "line graph"
    ax.set_ylabel(unit) if kind != "mixed" else None
    ax.set_title(topic.capitalize())
    ax.legend(loc="upper left")
    return ChartTask(kind, f"The {verb} below shows {topic} between {years[0]} and {years[-1]}.\n\n{suffix}",
                     _png(fig), text)
