"""Discrete-event simulator: the deterministic source of every number.

This file exists because wall-clock tail latencies are facts about the
machine that ran them, and the claims this repository publishes have to
reproduce exactly on any machine. The simulator advances a virtual
clock through an event heap, so the same WorkloadSpec produces the same
histogram to the last count, on every Python version in CI.

The server model is deliberately small: ``capacity`` concurrent service
slots, one FIFO queue, and an optional stall window during which no
service may start (requests already in service finish normally, the way
a connection-pool freeze or a stop-the-world pause behaves). Everything
the experiments claim traces back to these rules, and the boundary ADR
states what such a model cannot say about a real network.
"""

from __future__ import annotations

import heapq
import itertools
from collections import deque
from dataclasses import dataclass

from openloop.histogram import LogHistogram
from openloop.results import RunResult
from openloop.workload import WorkloadSpec, closed_loop_slots, open_loop_arrivals, service_time

_ARRIVAL = 0
_WAKE = 1
_DEPART = 2


@dataclass(frozen=True)
class _Request:
    request_id: int
    intended_s: float
    sent_s: float
    worker: int | None = None


class _Server:
    """Capacity-limited FIFO server with a start-blocking stall window."""

    def __init__(self, spec: WorkloadSpec, events: list, counter) -> None:
        self._spec = spec
        self._events = events
        self._counter = counter
        self._free = spec.server_capacity
        self._queue: deque[_Request] = deque()
        self.peak_in_service = 0
        self.starts: list[tuple[float, float]] = []  # (start time, service time) per request

    def submit(self, now: float, request: _Request) -> None:
        self._queue.append(request)
        self.pump(now)

    def pump(self, now: float) -> None:
        """Start queued requests until capacity or the stall stops us."""
        while self._free > 0 and self._queue:
            if self._spec.in_stall(now):
                # No starts during the stall. Park until it ends; the
                # wake event re-runs this pump at stall_end.
                heapq.heappush(
                    self._events,
                    (self._spec.stall_end_at(now), next(self._counter), _WAKE, None),
                )
                return
            request = self._queue.popleft()
            self._free -= 1
            in_service = self._spec.server_capacity - self._free
            self.peak_in_service = max(self.peak_in_service, in_service)
            svc = service_time(self._spec, request.request_id)
            self.starts.append((now, svc))
            heapq.heappush(self._events, (now + svc, next(self._counter), _DEPART, request))

    def release(self) -> None:
        self._free += 1


def run_open_loop(spec: WorkloadSpec) -> RunResult:
    """Replay the open-loop schedule: every intended request is sent.

    Latency is measured from the intended arrival time, because an
    open-loop client owes nothing to the server's state: if the server
    is stalled, the request still arrives and waits, and the wait is
    part of the latency a real client would see.
    """
    arrivals = open_loop_arrivals(spec)
    events: list = []
    counter = itertools.count()
    server = _Server(spec, events, counter)
    for request_id, t in enumerate(arrivals):
        heapq.heappush(
            events, (t, next(counter), _ARRIVAL, _Request(request_id, intended_s=t, sent_s=t))
        )

    histogram = LogHistogram()
    completed = 0
    while events:
        now, _, kind, payload = heapq.heappop(events)
        if kind == _ARRIVAL:
            server.submit(now, payload)
        elif kind == _WAKE:
            server.pump(now)
        else:  # _DEPART
            server.release()
            completed += 1
            if payload.intended_s >= spec.warmup_s:
                histogram.record(now - payload.intended_s)
            server.pump(now)

    return RunResult(
        generator="open",
        spec=spec,
        histogram=histogram,
        intended=len(arrivals),
        sent=len(arrivals),
        completed=completed,
        omitted=0,
        peak_in_service=server.peak_in_service,
        service_starts=server.starts,
    )


def run_closed_loop(spec: WorkloadSpec) -> RunResult:
    """Replay the closed-loop schedule: workers wait, slots get skipped.

    Each worker has a fixed intended schedule but sends only when its
    previous response has arrived, taking the first intended slot at or
    after that moment. Slots that pass while the worker is still
    waiting are counted as omitted: they are the requests a real client
    population would have sent and this generator never did. Latency is
    measured from the actual send, because that is exactly what a
    closed-loop tool reports, and reporting it faithfully is the point.
    """
    slots_by_worker = [closed_loop_slots(spec, w) for w in range(spec.workers)]
    events: list = []
    counter = itertools.count()
    server = _Server(spec, events, counter)
    request_ids = itertools.count()

    next_slot_index = [0] * spec.workers
    sent = 0
    omitted = 0

    def send_from(worker: int, ready_s: float) -> None:
        """Send at the first intended slot >= ready_s, skipping missed ones."""
        nonlocal sent, omitted
        slots = slots_by_worker[worker]
        i = next_slot_index[worker]
        while i < len(slots) and slots[i] < ready_s:
            omitted += 1
            i += 1
        if i >= len(slots):
            next_slot_index[worker] = i
            return
        intended = slots[i]
        next_slot_index[worker] = i + 1
        sent += 1
        request = _Request(next(request_ids), intended_s=intended, sent_s=intended, worker=worker)
        heapq.heappush(events, (intended, next(counter), _ARRIVAL, request))

    for worker in range(spec.workers):
        send_from(worker, ready_s=0.0)

    histogram = LogHistogram()
    completed = 0
    while events:
        now, _, kind, payload = heapq.heappop(events)
        if kind == _ARRIVAL:
            server.submit(now, payload)
        elif kind == _WAKE:
            server.pump(now)
        else:  # _DEPART
            server.release()
            completed += 1
            if payload.sent_s >= spec.warmup_s:
                histogram.record(now - payload.sent_s)
            server.pump(now)
            send_from(payload.worker, ready_s=now)

    intended = sum(len(s) for s in slots_by_worker)
    # Slots that were still ahead of a worker when the run ended were
    # neither sent nor skipped; they fall outside the measured window
    # and are excluded from both sides of the accounting.
    unreached = intended - sent - omitted

    return RunResult(
        generator="closed",
        spec=spec,
        histogram=histogram,
        intended=intended - unreached,
        sent=sent,
        completed=completed,
        omitted=omitted,
        peak_in_service=server.peak_in_service,
        service_starts=server.starts,
    )
