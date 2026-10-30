"""Log-bucket latency histogram with a stated, tested error bound.

This file exists because percentiles are the product of this tool, so
the recording structure cannot be a black box. A geometric bucket
layout gives a provable worst-case relative error for any reported
quantile: a value is reported as its bucket's geometric midpoint, so
the error is at most (sqrt(growth) - 1). With the default growth of
1.02 that bound is below 1 percent, and a test holds the implementation
to it. Storing raw samples would be exact but unbounded in memory;
the bound is the price of a fixed footprint, and it is published.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_MIN_VALUE_S = 1e-6
DEFAULT_MAX_VALUE_S = 100.0
DEFAULT_GROWTH = 1.02


class HistogramError(ValueError):
    """A histogram configured or queried in a way that has no answer."""


@dataclass
class LogHistogram:
    """Fixed-memory histogram over [min_value, max_value) with geometric buckets."""

    min_value: float = DEFAULT_MIN_VALUE_S
    max_value: float = DEFAULT_MAX_VALUE_S
    growth: float = DEFAULT_GROWTH

    def __post_init__(self) -> None:
        if self.min_value <= 0:
            raise HistogramError(f"min_value must be positive, got {self.min_value}")
        if self.max_value <= self.min_value:
            raise HistogramError(
                f"max_value {self.max_value} must exceed min_value {self.min_value}"
            )
        if self.growth <= 1.0:
            raise HistogramError(f"growth must exceed 1.0, got {self.growth}")
        self._log_growth = math.log(self.growth)
        self._bucket_count = self._index_for(self.max_value) + 1
        self._counts = [0] * (self._bucket_count + 2)  # plus under/overflow
        self._total = 0
        self._min_seen: float | None = None
        self._max_seen: float | None = None

    @property
    def bucket_count(self) -> int:
        """Number of in-range buckets, excluding the clamp buckets."""
        return self._bucket_count

    @property
    def total(self) -> int:
        return self._total

    @property
    def min_seen(self) -> float | None:
        return self._min_seen

    @property
    def max_seen(self) -> float | None:
        return self._max_seen

    @property
    def max_relative_error(self) -> float:
        """Worst-case relative error of any reported quantile.

        A value lands in a bucket spanning [lo, lo * growth) and is
        reported as the geometric midpoint lo * sqrt(growth). The worst
        case is a value at either edge, giving sqrt(growth) - 1.
        """
        return math.sqrt(self.growth) - 1.0

    def _index_for(self, value: float) -> int:
        return int(math.log(value / self.min_value) / self._log_growth)

    def record(self, value: float) -> None:
        """Record one sample. Out-of-range samples clamp and are counted."""
        if math.isnan(value) or value < 0:
            raise HistogramError(f"cannot record {value}: samples must be finite and non-negative")
        self._total += 1
        self._min_seen = value if self._min_seen is None else min(self._min_seen, value)
        self._max_seen = value if self._max_seen is None else max(self._max_seen, value)
        if value < self.min_value:
            self._counts[-2] += 1
        elif value >= self.max_value:
            self._counts[-1] += 1
        else:
            self._counts[self._index_for(value)] += 1

    def percentile(self, q: float) -> float:
        """Value at quantile ``q`` in [0, 100], as a bucket midpoint."""
        if not 0 <= q <= 100:
            raise HistogramError(f"quantile must be in [0, 100], got {q}")
        if self._total == 0:
            raise HistogramError("cannot take a percentile of an empty histogram")
        target = max(1, math.ceil(self._total * q / 100.0))
        running = self._counts[-2]  # underflow sits below every bucket
        if running >= target:
            return self.min_value
        for i in range(self._bucket_count):
            running += self._counts[i]
            if running >= target:
                lo = self.min_value * math.exp(i * self._log_growth)
                return lo * math.sqrt(self.growth)
        return self.max_value

    def counts(self) -> list[int]:
        """In-range bucket counts, for tests and serialisation."""
        return list(self._counts[:-2])

    @property
    def underflow(self) -> int:
        return self._counts[-2]

    @property
    def overflow(self) -> int:
        return self._counts[-1]

    def merge(self, other: LogHistogram) -> None:
        """Fold another histogram with identical layout into this one."""
        if (self.min_value, self.max_value, self.growth) != (
            other.min_value,
            other.max_value,
            other.growth,
        ):
            raise HistogramError("cannot merge histograms with different layouts")
        for i, c in enumerate(other._counts):
            self._counts[i] += c
        self._total += other._total
        for v in (other._min_seen, other._max_seen):
            if v is not None:
                self._min_seen = v if self._min_seen is None else min(self._min_seen, v)
                self._max_seen = v if self._max_seen is None else max(self._max_seen, v)
