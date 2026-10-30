"""Run results and comparison: the shapes every other module speaks.

This file exists so that the simulator, the wall-clock driver, the CLI
and the experiments all describe an outcome the same way. A RunResult
carries the recorded histogram plus the counters that make the
histogram honest: how many requests were intended, how many were
actually sent, and how many a closed-loop generator silently dropped.
The comparison deliberately reports the omission count next to the
percentile ratio, because the ratio alone understates the problem: the
missing samples are not in either histogram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openloop.histogram import LogHistogram

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from openloop.workload import WorkloadSpec

PERCENTILES = (50.0, 90.0, 99.0, 99.9)


@dataclass
class RunResult:
    """Outcome of one generator replaying one WorkloadSpec."""

    generator: str
    spec: WorkloadSpec
    histogram: LogHistogram
    intended: int
    sent: int
    completed: int
    omitted: int
    peak_in_service: int = 0
    service_starts: list[tuple[float, float]] = field(default_factory=list, repr=False)

    @property
    def omitted_fraction(self) -> float:
        """Share of intended requests that were never sent."""
        if self.intended == 0:
            return 0.0
        return self.omitted / self.intended

    def percentile(self, q: float) -> float:
        return self.histogram.percentile(q)

    def summary(self) -> dict:
        """JSON-ready summary. Latencies are reported in milliseconds."""
        return {
            "generator": self.generator,
            "intended": self.intended,
            "sent": self.sent,
            "completed": self.completed,
            "omitted": self.omitted,
            "omitted_fraction": round(self.omitted_fraction, 6),
            "percentiles_ms": {
                str(q): round(self.percentile(q) * 1000.0, 3) for q in PERCENTILES
            },
            "max_ms": round((self.histogram.max_seen or 0.0) * 1000.0, 3),
        }


@dataclass(frozen=True)
class Comparison:
    """Closed-loop and open-loop runs of the same spec, side by side."""

    open_result: RunResult
    closed_result: RunResult

    def understatement(self, q: float) -> float:
        """How many times larger the open-loop percentile is.

        Above 1.0 means the closed-loop generator reported a smaller
        number than an independent client would have experienced.
        """
        closed = self.closed_result.percentile(q)
        if closed == 0:
            raise ZeroDivisionError("closed-loop percentile is zero; ratio undefined")
        return self.open_result.percentile(q) / closed

    def summary(self) -> dict:
        return {
            "open": self.open_result.summary(),
            "closed": self.closed_result.summary(),
            "understatement_p99": round(self.understatement(99.0), 2),
            "understatement_p50": round(self.understatement(50.0), 2),
            "omitted": self.closed_result.omitted,
        }


def compare(open_result: RunResult, closed_result: RunResult) -> Comparison:
    if open_result.generator != "open" or closed_result.generator != "closed":
        raise ValueError(
            "compare() wants one open-loop and one closed-loop result, got "
            f"{open_result.generator!r} and {closed_result.generator!r}"
        )
    return Comparison(open_result, closed_result)


def table(results: list[RunResult]) -> str:
    """Fixed-width table of per-generator outcomes for the terminal."""
    header = (
        f"{'generator':<10}{'sent':>8}{'omitted':>9}{'p50 ms':>10}"
        f"{'p99 ms':>10}{'p99.9 ms':>11}{'max ms':>10}"
    )
    lines = [header, "-" * len(header)]
    for r in results:
        lines.append(
            f"{r.generator:<10}{r.sent:>8}{r.omitted:>9}"
            f"{r.percentile(50.0) * 1000:>10.2f}{r.percentile(99.0) * 1000:>10.2f}"
            f"{r.percentile(99.9) * 1000:>11.2f}{(r.histogram.max_seen or 0) * 1000:>10.2f}"
        )
    return "\n".join(lines)
