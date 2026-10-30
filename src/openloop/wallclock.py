"""Wall-clock drivers: proof the simulated behaviour is real.

This file exists for one claim only: that the simulator's story
survives contact with a real event loop, real sleeps and a real ASGI
stack. It replays the same WorkloadSpec against the bundled in-process
target through httpx's ASGI transport, so there is still no socket and
no network, just real time instead of virtual time.

Nothing in here is a source of published headline numbers. Wall-clock
tails belong to the machine that produced them; experiment E4 uses
this driver to bound the gap between simulation and reality, and the
bound is the only wall-derived figure any document quotes.
"""

from __future__ import annotations

import asyncio
import time

from openloop.histogram import LogHistogram
from openloop.results import RunResult
from openloop.workload import WorkloadSpec, closed_loop_slots, open_loop_arrivals, service_time

try:
    import httpx
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via refusal test
    httpx = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _require_httpx() -> None:
    if httpx is None:
        raise ModuleNotFoundError(
            "wall-clock mode needs the 'wall' extra: pip install 'openloop[wall]'"
        ) from _IMPORT_ERROR


async def _client_for(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://openloop.local", timeout=None)


async def run_open_loop_wall(spec: WorkloadSpec, app) -> RunResult:
    """Open loop against the in-process target, on the real clock.

    Every request gets its own task fired at its intended time, so a
    slow response delays nothing that comes after it. Latency runs
    from the intended arrival, exactly as in the simulator.
    """
    _require_httpx()
    arrivals = open_loop_arrivals(spec)
    histogram = LogHistogram()
    completed = 0

    async with await _client_for(app) as client:
        await client.post("/start")
        t0 = time.monotonic()

        async def one(request_id: int, intended: float) -> None:
            nonlocal completed
            delay = intended - (time.monotonic() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            svc = service_time(spec, request_id)
            response = await client.get("/work", params={"svc": svc})
            response.raise_for_status()
            completed += 1
            if intended >= spec.warmup_s:
                histogram.record((time.monotonic() - t0) - intended)

        tasks = [asyncio.create_task(one(i, t)) for i, t in enumerate(arrivals)]
        await asyncio.gather(*tasks)

    return RunResult(
        generator="open",
        spec=spec,
        histogram=histogram,
        intended=len(arrivals),
        sent=len(arrivals),
        completed=completed,
        omitted=0,
    )


async def run_closed_loop_wall(spec: WorkloadSpec, app) -> RunResult:
    """Closed loop against the in-process target, on the real clock.

    Each worker keeps the same fixed slot schedule as the simulator
    and skips slots that pass while it is still waiting on a response.
    The skipped slots are counted, because they are the whole story.
    """
    _require_httpx()
    histogram = LogHistogram()
    counters = {"sent": 0, "omitted": 0, "completed": 0}
    request_ids = iter(range(10_000_000))

    async with await _client_for(app) as client:
        await client.post("/start")
        t0 = time.monotonic()

        async def worker(index: int) -> None:
            slots = closed_loop_slots(spec, index)
            i = 0
            while i < len(slots):
                now = time.monotonic() - t0
                if slots[i] < now:
                    counters["omitted"] += 1
                    i += 1
                    continue
                await asyncio.sleep(slots[i] - now)
                sent_at = time.monotonic() - t0
                counters["sent"] += 1
                svc = service_time(spec, next(request_ids))
                response = await client.get("/work", params={"svc": svc})
                response.raise_for_status()
                counters["completed"] += 1
                if sent_at >= spec.warmup_s:
                    histogram.record((time.monotonic() - t0) - sent_at)
                i += 1

        await asyncio.gather(*(worker(w) for w in range(spec.workers)))

    sent = counters["sent"]
    omitted = counters["omitted"]
    return RunResult(
        generator="closed",
        spec=spec,
        histogram=histogram,
        intended=sent + omitted,
        sent=sent,
        completed=counters["completed"],
        omitted=omitted,
    )
