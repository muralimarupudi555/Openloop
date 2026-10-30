"""E2, the headline: recurring 500 ms pauses, two different stories.

Question from the README: when the target pauses for half a second
every ten seconds (the shape of a GC or a rolling freeze), how far
apart are the two generators' reports of the same server? The open
loop keeps sending on schedule and its tail absorbs every queue the
pauses create. The closed loop stops sending, skips the slots it
missed, and reports a tail that barely moves.

E2 also runs the single-stall variant, because its result is the
second finding of this repository: one 500 ms stall in a 60 second
window is below one percent of the samples, so even the open loop's
p99 misses it. Which quantile can see a disturbance is arithmetic
(the disturbance's sample share against 100 minus q), not virtue.
"""

from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import print_table, write_result
from e1_null import SPEC as NULL_SPEC

from openloop.results import RunResult, compare
from openloop.sim import run_closed_loop, run_open_loop

SPEC = replace(NULL_SPEC, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0)
SINGLE = replace(NULL_SPEC, stall_start_s=30.0, stall_duration_s=0.5)


def stall_share_pct(result: RunResult, threshold_s: float) -> float:
    """Share of recorded samples at or above the threshold, in percent.

    Counted from bucket lower edges: every bucket whose lower edge is
    at or above the threshold contributes its full count. The
    threshold (half the stall) sits far above any bucket the baseline
    service distribution crowds, so bucket granularity cannot move it.
    """
    h = result.histogram
    hit = h.overflow
    for i, count in enumerate(h.counts()):
        lo = h.min_value * math.exp(i * math.log(h.growth))
        if lo >= threshold_s:
            hit += count
    return hit / h.total * 100.0


def main() -> int:
    open_result = run_open_loop(SPEC)
    closed_result = run_closed_loop(SPEC)
    comparison = compare(open_result, closed_result)
    understatement = comparison.understatement(99.0)
    threshold = SPEC.stall_duration_s / 2

    single_open = run_open_loop(SINGLE)
    single_closed = run_closed_loop(SINGLE)

    payload = {
        "question": "how much does the closed loop understate recurring 500 ms pauses?",
        "spec": {
            "rate_rps": SPEC.rate_rps,
            "duration_s": SPEC.duration_s,
            "stall_duration_s": SPEC.stall_duration_s,
            "stall_period_s": SPEC.stall_period_s,
            "stall_windows": len(SPEC.stall_windows()),
        },
        "open": open_result.summary(),
        "closed": closed_result.summary(),
        "understatement_p99": round(understatement, 1),
        "understatement_p50": round(comparison.understatement(50.0), 2),
        "omitted": closed_result.omitted,
        "omitted_fraction_pct": round(closed_result.omitted_fraction * 100.0, 1),
        "open_stall_share_pct": round(stall_share_pct(open_result, threshold), 2),
        "closed_stall_share_pct": round(stall_share_pct(closed_result, threshold), 2),
        "single_stall": {
            "question": "and why a single stall is the wrong demo",
            "open_p99_ms": round(single_open.percentile(99.0) * 1000, 2),
            "open_p999_ms": round(single_open.percentile(99.9) * 1000, 2),
            "closed_p999_ms": round(single_closed.percentile(99.9) * 1000, 2),
            "open_stall_share_pct": round(stall_share_pct(single_open, threshold), 2),
            "open_p99_understatement": round(
                single_open.percentile(99.0) / single_closed.percentile(99.0), 2
            ),
            "p999_understatement": round(
                single_open.percentile(99.9) / single_closed.percentile(99.9), 1
            ),
        },
    }
    write_result("e2_stall", payload)
    print_table(
        "E2 headline: 500 ms pause every 10 s",
        [
            ("open p99 ms", f"{open_result.percentile(99.0) * 1000:.2f}"),
            ("closed p99 ms", f"{closed_result.percentile(99.0) * 1000:.2f}"),
            ("understatement p99", f"{understatement:.1f}x"),
            ("omitted requests", closed_result.omitted),
            ("open stall share %", f"{payload['open_stall_share_pct']:.2f}"),
            ("closed stall share %", f"{payload['closed_stall_share_pct']:.2f}"),
            ("single-stall open p99 ratio", payload["single_stall"]["open_p99_understatement"]),
            ("single-stall p99.9 ratio", payload["single_stall"]["p999_understatement"]),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
