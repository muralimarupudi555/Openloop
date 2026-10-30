"""E3, the sweep: where the two generators stop telling the same story.

Question from the README: with no stall at all, at what offered load
do the generators diverge? As the rate approaches server capacity the
open-loop queue grows without bound while the closed loop self-limits
to what the server returns. The published knee is the lowest swept
rate where the open-loop p99 exceeds the closed-loop p99 by more than
fifty percent: below it a closed-loop test is honest, above it the
tool is measuring itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import print_table, write_result

from openloop.sim import run_closed_loop, run_open_loop
from openloop.workload import WorkloadSpec

RATES = (100.0, 160.0, 220.0, 280.0, 320.0, 360.0, 380.0)
DIVERGENCE_RATIO = 1.5
CAPACITY = 8
SERVICE_MEAN_S = 0.020  # capacity / mean = 400 rps of theoretical throughput


def spec_for(rate: float) -> WorkloadSpec:
    return WorkloadSpec(
        seed=7,
        duration_s=30.0,
        rate_rps=rate,
        workers=8,
        service_mean_s=SERVICE_MEAN_S,
        service_sigma=0.25,
        server_capacity=CAPACITY,
        warmup_s=5.0,
    )


def main() -> int:
    points = []
    knee_rps = None
    for rate in RATES:
        spec = spec_for(rate)
        open_result = run_open_loop(spec)
        closed_result = run_closed_loop(spec)
        ratio = open_result.percentile(99.0) / closed_result.percentile(99.0)
        points.append(
            {
                "rate_rps": rate,
                "open_p99_ms": round(open_result.percentile(99.0) * 1000, 2),
                "closed_p99_ms": round(closed_result.percentile(99.0) * 1000, 2),
                "ratio": round(ratio, 2),
                "closed_omitted": closed_result.omitted,
            }
        )
        if knee_rps is None and ratio > DIVERGENCE_RATIO:
            knee_rps = rate

    payload = {
        "question": "at what offered load do the generators diverge with no stall?",
        "server": {"capacity": CAPACITY, "service_mean_s": SERVICE_MEAN_S,
                   "theoretical_max_rps": CAPACITY / SERVICE_MEAN_S},
        "divergence_ratio": DIVERGENCE_RATIO,
        "points": points,
        "knee_rps": knee_rps,
    }
    write_result("e3_sweep", payload)
    print_table(
        "E3 sweep: offered load vs p99 ratio",
        [(f"{p['rate_rps']:.0f} rps", f"ratio {p['ratio']:.2f}, omitted {p['closed_omitted']}")
         for p in points] + [("knee", f"{knee_rps} rps")],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
