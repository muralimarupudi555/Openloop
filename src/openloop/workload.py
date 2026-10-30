"""Workload model: the one seeded description both drivers replay.

This module exists so that the simulator and the wall-clock driver can
never drift apart on what the workload is. Arrival times, pacing slots
and service times are all pure functions of a WorkloadSpec, so the same
spec replayed anywhere produces the same intended traffic. Every
validation rule lives here, at the boundary, so a bad spec is refused
before any driver starts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, fields
from pathlib import Path

import tomllib

# Service times are drawn from a lognormal distribution. Sigma is kept
# deliberately small so the baseline tail is tight: the point of the
# tool is to show latency injected by the measurement loop, and a noisy
# service-time tail would blur that signal.
_DEFAULT_SIGMA = 0.25


class WorkloadError(ValueError):
    """A workload spec that cannot describe a runnable workload."""


@dataclass(frozen=True)
class WorkloadSpec:
    """Complete, replayable description of one load scenario.

    The same spec produces the same arrivals, the same pacing slots and
    the same service-time stream on every machine, which is what makes
    published numbers reproducible.
    """

    seed: int = 7
    duration_s: float = 60.0
    rate_rps: float = 200.0
    workers: int = 8
    service_mean_s: float = 0.010
    service_sigma: float = _DEFAULT_SIGMA
    server_capacity: int = 16
    stall_start_s: float | None = None
    stall_duration_s: float = 0.0
    warmup_s: float = 0.0
    extra: dict = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise WorkloadError(f"duration_s must be positive, got {self.duration_s}")
        if self.rate_rps <= 0:
            raise WorkloadError(f"rate_rps must be positive, got {self.rate_rps}")
        if self.workers < 1:
            raise WorkloadError(f"workers must be at least 1, got {self.workers}")
        if self.service_mean_s <= 0:
            raise WorkloadError(f"service_mean_s must be positive, got {self.service_mean_s}")
        if self.service_sigma < 0:
            raise WorkloadError(f"service_sigma must not be negative, got {self.service_sigma}")
        if self.server_capacity < 1:
            raise WorkloadError(f"server_capacity must be at least 1, got {self.server_capacity}")
        if self.stall_duration_s < 0:
            raise WorkloadError(
                f"stall_duration_s must not be negative, got {self.stall_duration_s}"
            )
        if self.stall_start_s is not None and self.stall_start_s < 0:
            raise WorkloadError(f"stall_start_s must not be negative, got {self.stall_start_s}")
        if self.stall_start_s is not None and self.stall_start_s >= self.duration_s:
            raise WorkloadError(
                "stall_start_s must fall inside the run: "
                f"{self.stall_start_s} >= duration {self.duration_s}"
            )
        if self.warmup_s < 0 or self.warmup_s >= self.duration_s:
            raise WorkloadError(
                f"warmup_s must be inside [0, duration_s), got {self.warmup_s}"
            )

    @property
    def stall_end_s(self) -> float:
        """End of the stall window, or 0.0 when there is no stall."""
        if self.stall_start_s is None:
            return 0.0
        return self.stall_start_s + self.stall_duration_s

    def in_stall(self, t: float) -> bool:
        """True when a service start at time ``t`` must be deferred."""
        if self.stall_start_s is None or self.stall_duration_s == 0:
            return False
        return self.stall_start_s <= t < self.stall_end_s

    @property
    def pacing_interval_s(self) -> float:
        """Per-worker send interval that offers ``rate_rps`` in aggregate."""
        return self.workers / self.rate_rps

    @classmethod
    def from_toml(cls, path: str | Path) -> WorkloadSpec:
        """Load a spec from a TOML file, refusing unknown keys loudly.

        Unknown keys are refused rather than ignored because a silently
        ignored ``stall_duration`` typo would produce a run that looks
        healthy for the wrong reason.
        """
        raw = tomllib.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)} - {"extra"}
        unknown = set(raw) - known
        if unknown:
            raise WorkloadError(f"unknown workload keys: {sorted(unknown)}")
        return cls(**raw)


def open_loop_arrivals(spec: WorkloadSpec) -> list[float]:
    """Poisson arrival times for an open-loop client, seeded and sorted.

    Arrivals are generated independently of any response, which is the
    definition of open loop: the schedule exists before the run starts
    and nothing the server does can change it.
    """
    rng = random.Random(f"{spec.seed}:arrivals")
    arrivals: list[float] = []
    t = 0.0
    while True:
        t += rng.expovariate(spec.rate_rps)
        if t >= spec.duration_s:
            break
        arrivals.append(t)
    return arrivals


def closed_loop_slots(spec: WorkloadSpec, worker: int) -> list[float]:
    """Intended send times for one closed-loop worker.

    Workers are offset so the aggregate intended schedule is evenly
    spread rather than eight sends landing on the same tick. These
    slots are the schedule the worker is trying to keep; the simulator
    records which of them it actually kept.
    """
    if not 0 <= worker < spec.workers:
        raise WorkloadError(f"worker index {worker} outside [0, {spec.workers})")
    interval = spec.pacing_interval_s
    offset = (worker / spec.workers) * interval
    slots: list[float] = []
    t = offset
    while t < spec.duration_s:
        slots.append(t)
        t += interval
    return slots


def service_time(spec: WorkloadSpec, request_id: int) -> float:
    """Service time for one request, a pure function of (seed, id).

    Keyed by request id rather than drawn from a shared stream so that
    the value does not depend on the order in which a driver happens to
    process requests. Two drivers asking about the same request get the
    same answer, which is what lets the wall-clock run replay the
    simulator's workload exactly.
    """
    rng = random.Random(f"{spec.seed}:service:{request_id}")
    if spec.service_sigma == 0:
        return spec.service_mean_s
    # lognormvariate takes the mu/sigma of the underlying normal. Mu is
    # adjusted so the distribution mean equals service_mean_s.
    mu = _lognormal_mu(spec.service_mean_s, spec.service_sigma)
    return rng.lognormvariate(mu, spec.service_sigma)


def _lognormal_mu(mean: float, sigma: float) -> float:
    """Mu of the underlying normal for a lognormal with the given mean."""
    import math

    return math.log(mean) - (sigma * sigma) / 2.0
