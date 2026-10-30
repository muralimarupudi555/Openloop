"""E1, the null result: with no stall, the two generators must agree.

Question from the README: if the generators disagree even on a calm
workload, every later comparison is measuring the generators rather
than the server. So E1 runs the headline workload with the stall
removed and publishes how far apart the two medians and tails are.
Publishing this null result first is what makes E2 credible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import print_table, write_result

from openloop.sim import run_closed_loop, run_open_loop
from openloop.workload import WorkloadSpec

SPEC = WorkloadSpec(
    seed=7,
    duration_s=60.0,
    rate_rps=200.0,
    workers=8,
    service_mean_s=0.010,
    service_sigma=0.25,
    server_capacity=16,
)


def delta_pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100.0


def main() -> int:
    open_result = run_open_loop(SPEC)
    closed_result = run_closed_loop(SPEC)

    p50 = delta_pct(open_result.percentile(50.0), closed_result.percentile(50.0))
    p99 = delta_pct(open_result.percentile(99.0), closed_result.percentile(99.0))

    payload = {
        "question": "do the generators agree when nothing is wrong?",
        "spec": {"rate_rps": SPEC.rate_rps, "duration_s": SPEC.duration_s, "stall": None},
        "open": open_result.summary(),
        "closed": closed_result.summary(),
        "p50_delta_pct": round(p50, 2),
        "p99_delta_pct": round(p99, 2),
        "omitted_without_stall": closed_result.omitted,
    }
    write_result("e1_null", payload)
    print_table(
        "E1 null result: no stall",
        [
            ("open p50 ms", f"{open_result.percentile(50.0) * 1000:.2f}"),
            ("closed p50 ms", f"{closed_result.percentile(50.0) * 1000:.2f}"),
            ("p50 delta %", f"{p50:.2f}"),
            ("p99 delta %", f"{p99:.2f}"),
            ("closed omitted", closed_result.omitted),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
