"""E4, the validation: the simulator against a real event loop.

Question from the README: why believe a virtual clock? E4 replays one
stalled workload twice, once through the simulator and once on the
real clock against the bundled ASGI target, and checks that the two
agree within a fixed tolerance on the shapes that matter: the open
tail that sees the stall, the closed median that does not, and the
omission count. The tolerance is a constant chosen in advance, not a
measurement: the measured deltas land in the JSON for inspection, and
the pass verdict is the only thing a document may quote, because the
deltas themselves move with the machine.

This is the one experiment that takes real time to run (two replays
of a ten second scenario) and the only one whose raw numbers are
machine-dependent, which is exactly why none of them is anchored.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import print_table, write_result

from openloop.sim import run_closed_loop, run_open_loop
from openloop.target import build_app
from openloop.wallclock import run_closed_loop_wall, run_open_loop_wall
from openloop.workload import WorkloadSpec

# Service times sit an order of magnitude above the event loop's
# per-request overhead (ASGI dispatch plus client bookkeeping, around
# a millisecond here). E4 validates queueing and stall behaviour, not
# the runtime's constant cost: with 5 ms services that cost was a
# third of the median and the first run of this experiment failed its
# own tolerance, which is recorded in ADR-005 as a boundary of the
# simulator. The residual delta in the JSON is that overhead.
SPEC = WorkloadSpec(
    seed=13,
    duration_s=10.0,
    rate_rps=50.0,
    workers=4,
    service_mean_s=0.025,
    service_sigma=0.25,
    server_capacity=16,
    stall_start_s=5.0,
    stall_duration_s=0.3,
)
TOLERANCE_PCT = 25.0


def delta_pct(wall: float, sim: float) -> float:
    return abs(wall - sim) / sim * 100.0


def main() -> int:
    sim_open = run_open_loop(SPEC)
    sim_closed = run_closed_loop(SPEC)
    wall_open = asyncio.run(run_open_loop_wall(SPEC, build_app(SPEC)))
    wall_closed = asyncio.run(run_closed_loop_wall(SPEC, build_app(SPEC)))

    checks = {
        "open_p99_delta_pct": round(
            delta_pct(wall_open.percentile(99.0), sim_open.percentile(99.0)), 2
        ),
        "open_p50_delta_pct": round(
            delta_pct(wall_open.percentile(50.0), sim_open.percentile(50.0)), 2
        ),
        "closed_p50_delta_pct": round(
            delta_pct(wall_closed.percentile(50.0), sim_closed.percentile(50.0)), 2
        ),
        "omitted_delta_pct": round(
            delta_pct(max(wall_closed.omitted, 1), max(sim_closed.omitted, 1)), 2
        ),
    }
    passed = all(v <= TOLERANCE_PCT for v in checks.values())

    payload = {
        "question": "does the real clock agree with the virtual one?",
        "spec": {
            "duration_s": SPEC.duration_s,
            "rate_rps": SPEC.rate_rps,
            "stall_duration_s": SPEC.stall_duration_s,
        },
        "tolerance_pct": TOLERANCE_PCT,
        "deltas": checks,
        "sim": {"open": sim_open.summary(), "closed": sim_closed.summary()},
        "wall": {"open": wall_open.summary(), "closed": wall_closed.summary()},
        "passed": passed,
        "note": "deltas are machine-dependent; only tolerance_pct and passed may be quoted",
    }
    write_result("e4_sim_vs_wall", payload)
    print_table(
        "E4 validation: sim vs wall clock",
        [(k, f"{v:.2f}%") for k, v in checks.items()]
        + [("tolerance %", f"{TOLERANCE_PCT:.0f}"), ("passed", passed)],
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
