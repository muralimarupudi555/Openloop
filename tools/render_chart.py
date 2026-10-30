"""Render the E3 sweep chart as a committed SVG, from the real JSON.

The chart is generated from docs/experiments/e3_sweep.json by this
script, never drawn by hand, so a reviewer regenerates it with one
command and the picture cannot drift from the data. Rendering is
plain SVG written directly: no plotting dependency, intrinsic width
and height, an opaque light background, and labelled axes, which are
the committed-image rules this repository follows everywhere.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "experiments" / "e3_sweep.json"
OUT = ROOT / "docs" / "evidence" / "sweep.svg"

W, H = 760, 420
ML, MR, MT, MB = 80, 30, 52, 64
PW, PH = W - ML - MR, H - MT - MB


def x_pos(rate: float, lo: float, hi: float) -> float:
    return ML + (rate - lo) / (hi - lo) * PW


def y_pos(ms: float, lo: float, hi: float) -> float:
    return MT + PH - (math.log10(ms) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * PH


def polyline(points: list[tuple[float, float]], colour: str) -> str:
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{colour}"/>' for x, y in points
    )
    return (
        f'<polyline points="{path}" fill="none" stroke="{colour}" stroke-width="2.5"/>' + dots
    )


def main() -> int:
    data = json.loads(SOURCE.read_text())
    points = data["points"]
    rates = [p["rate_rps"] for p in points]
    lo_rate, hi_rate = min(rates), max(rates)
    all_ms = [p["open_p99_ms"] for p in points] + [p["closed_p99_ms"] for p in points]
    lo_ms = 10 ** math.floor(math.log10(min(all_ms)))
    hi_ms = 10 ** math.ceil(math.log10(max(all_ms)))
    knee = data["knee_rps"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="p99 latency by offered load">',
        f'<rect width="{W}" height="{H}" fill="#f7f9fc"/>',
        '<style>text{font:400 13px Helvetica,Arial,sans-serif;fill:#39465e}'
        ".t{font-weight:600;font-size:16px}.s{font-size:11px;fill:#6b7890}</style>",
        f'<text class="t" x="{ML}" y="26">p99 latency against offered load, no stall '
        "(E3, simulated)</text>",
        f'<text class="s" x="{ML}" y="44">open loop sees the queue; the closed loop '
        "self-limits and reports its own pace</text>",
    ]

    # Log-scale y gridlines by decade.
    ms = lo_ms
    while ms <= hi_ms:
        y = y_pos(ms, lo_ms, hi_ms)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{ML + PW}" y2="{y:.1f}" '
            'stroke="#dbe2ee" stroke-width="1"/>'
        )
        label = f"{ms:g} ms"
        parts.append(
            f'<text class="s" x="{ML - 10}" y="{y + 4:.1f}" text-anchor="end">{label}</text>'
        )
        ms *= 10

    for rate in rates:
        x = x_pos(rate, lo_rate, hi_rate)
        parts.append(
            f'<text class="s" x="{x:.1f}" y="{MT + PH + 20}" text-anchor="middle">{rate:g}</text>'
        )
    parts.append(
        f'<text class="s" x="{ML + PW / 2:.1f}" y="{H - 14}" text-anchor="middle">'
        "offered load, requests per second</text>"
    )

    kx = x_pos(knee, lo_rate, hi_rate)
    parts.append(
        f'<line x1="{kx:.1f}" y1="{MT}" x2="{kx:.1f}" y2="{MT + PH}" '
        'stroke="#e05d5d" stroke-width="1.5" stroke-dasharray="5 4"/>'
    )
    parts.append(
        f'<text class="s" x="{kx + 6:.1f}" y="{MT + 14}" fill="#b23b3b">divergence knee</text>'
    )

    open_pts = [(x_pos(p["rate_rps"], lo_rate, hi_rate), y_pos(p["open_p99_ms"], lo_ms, hi_ms))
                for p in points]
    closed_pts = [(x_pos(p["rate_rps"], lo_rate, hi_rate), y_pos(p["closed_p99_ms"], lo_ms, hi_ms))
                  for p in points]
    parts.append(polyline(open_pts, "#159a86"))
    parts.append(polyline(closed_pts, "#d08a2d"))
    parts.append(f'<text x="{ML + 8}" y="{MT + PH - 60}" fill="#159a86">open loop p99</text>')
    parts.append(f'<text x="{ML + 8}" y="{MT + PH - 38}" fill="#d08a2d">closed loop p99</text>')
    parts.append("</svg>")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n")
    print(f"render_chart: wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
