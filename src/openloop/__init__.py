"""openloop: measure what a closed-loop load generator cannot see.

A closed-loop generator waits for each response before sending the next
request, so when the target stalls, the generator stops sending. The
requests that a real, independent client would have issued during the
stall are never sent and never measured. That omission is structural,
not a bug in any one tool, and this package exists to measure its size.

The package ships two drivers over one seeded workload model: a
discrete-event simulator (the deterministic source of every published
number) and a wall-clock driver against a bundled in-process ASGI
target (the demonstration that the simulator's behaviour is real).
"""

from openloop.histogram import LogHistogram
from openloop.results import RunResult, compare
from openloop.sim import run_closed_loop, run_open_loop
from openloop.workload import WorkloadSpec

__all__ = [
    "LogHistogram",
    "RunResult",
    "WorkloadSpec",
    "compare",
    "run_closed_loop",
    "run_open_loop",
]

__version__ = "1.0.0"
