"""Shared experiment plumbing: one place that writes docs/experiments.

Each experiment answers one question the README asks, writes its
answer as JSON here, and prints a small table. The JSON files are the
only bridge between experiments and documents: collect_metrics.py
reads them, and check_numbers.py holds every document to them.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "experiments"


def write_result(name: str, payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def print_table(title: str, rows: list[tuple[str, object]]) -> None:
    width = max(len(k) for k, _ in rows)
    print(f"\n{title}")
    print("-" * len(title))
    for key, value in rows:
        print(f"{key:<{width}}  {value}")
