"""E2, the headline: one 500 ms stall, two completely different stories.

Question from the README: when the target freezes for half a second,
how far apart are the two generators' reports of the same event? The
open loop keeps sending on schedule and its tail absorbs the queue
the stall created. The closed loop stops sending, skips the slots it
missed, and reports a tail that barely moves. The ratio between the
two p99s is the understatement, and the skipped slots are the
requests that were never measured at all.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import print_table, write_result
from e1_null import SPEC as NULL_SPEC

from openloop.results import compare
from openloop.sim import run_closed_loop, run_open_loop

SPEC = replace(NULL_SPEC, stall_start_s=30.0, stall_duration_s=0.5)


def main() -> int:
    open_result = run_open_loop(SPEC)
    closed_result = run_closed_loop(SPEC)
    comparison = compare(open_result, closed_result)

    understatement = comparison.understatement(99.0)
    # How many closed-loop samples the stall touched: latencies at or
    # above half the stall are stall-shaped, nothing in the baseline
    # service distribution gets near 250 ms.
    stall_samples = sum(
        1 for _, latency in _closed_latencies(closed_result) if latency >= SPEC.stall_duration_s / 2
    )
    stall_share_pct = stall_samples / closed_result.histogram.total * 100.0
    # Visibility rule: a quantile q only reports the stall when the
    # stall's share of samples exceeds (100 - q) percent.
    p99_blind = stall_share_pct < 1.0

    payload = {
        "question": "how much does the closed loop understate one 500 ms stall?",
        "spec": {
            "rate_rps": SPEC.rate_rps,
            "duration_s": SPEC.duration_s,
            "stall_start_s": SPEC.stall_start_s,
            "stall_duration_s": SPEC.stall_duration_s,
        },
        "open": open_result.summary(),
        "closed": closed_result.summary(),
        "understatement_p99": round(understatement, 1),
        "understatement_p50": round(comparison.understatement(50.0), 2),
        "omitted": closed_result.omitted,
        "omitted_fraction_pct": round(closed_result.omitted_fraction * 100.0, 2),
        "closed_stall_samples": stall_samples,
        "closed_stall_share_pct": round(stall_share_pct, 3),
        "closed_p99_blind_to_stall": p99_blind,
    }
    write_result("e2_stall", payload)
    print_table(
        "E2 headline: 500 ms stall at t=30",
        [
            ("open p99 ms", f"{open_result.percentile(99.0) * 1000:.2f}"),
            ("closed p99 ms", f"{closed_result.percentile(99.0) * 1000:.2f}"),
            ("understatement p99", f"{understatement:.1f}x"),
            ("omitted requests", closed_result.omitted),
            ("closed stall share %", f"{stall_share_pct:.3f}"),
            ("closed p99 blind", p99_blind),
        ],
    )
    return 0


def _closed_latencies(result):
    """Approximate per-sample view from the histogram's clamp-free data.

    The histogram does not keep raw samples, so stall-shaped samples
    are counted from bucket boundaries: every bucket whose lower edge
    is at or above the threshold contributes its full count. The
    threshold sits far from any bucket crowded by baseline service
    times, so bucket granularity cannot move the count.
    """
    import math

    h = result.histogram
    counts = h.counts()
    for i, count in enumerate(counts):
        if count == 0:
            continue
        lo = h.min_value * math.exp(i * math.log(h.growth))
        for _ in range(count):
            yield i, lo
    for _ in range(h.overflow):
        yield -1, h.max_value


if __name__ == "__main__":
    raise SystemExit(main())
