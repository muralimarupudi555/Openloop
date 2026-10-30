"""Bundled ASGI target: the wall-clock twin of the simulated server.

This file exists so the wall-clock driver has something real to hit
without any network, credentials or external process. The app
implements the same three rules as the simulator's server: ``capacity``
concurrent slots, FIFO admission, and a stall window during which no
service may start. Service time arrives as a query parameter computed
from the same seeded workload function the simulator uses, so a wall
run replays the simulator's exact workload rather than a lookalike.

The app holds no global state: every piece of state lives on the
instance returned by build_app, so tests can build as many isolated
targets as they like.
"""

from __future__ import annotations

import asyncio
import time

from openloop.workload import WorkloadSpec

try:  # FastAPI is the resume-relevant frontend, but optional at import time.
    from fastapi import FastAPI, HTTPException, Query
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via refusal test
    FastAPI = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

MAX_SERVICE_S = 10.0


def build_app(spec: WorkloadSpec, clock=time.monotonic):
    """Build an isolated FastAPI target for one wall-clock run.

    The stall window is anchored to the moment /start is called, not to
    import time, so the driver controls exactly when the scenario
    begins. Requests before /start are refused rather than silently
    measured against an unanchored stall.
    """
    if FastAPI is None:
        raise ModuleNotFoundError(
            "the wall-clock target needs the 'wall' extra: pip install 'openloop[wall]'"
        ) from _IMPORT_ERROR

    app = FastAPI(title="openloop target")
    state = {"t0": None}
    slots = asyncio.Semaphore(spec.server_capacity)

    def elapsed() -> float:
        return clock() - state["t0"]

    @app.post("/start")
    async def start() -> dict:
        state["t0"] = clock()
        return {"started": True}

    @app.get("/work")
    async def work(svc: float = Query(..., ge=0.0, le=MAX_SERVICE_S)) -> dict:
        if state["t0"] is None:
            raise HTTPException(status_code=409, detail="call /start before /work")
        # Rule: no service may start inside the stall window. Waiting
        # happens before a slot is taken, matching the simulator, where
        # a stalled server holds no capacity for queued requests.
        if spec.in_stall(elapsed()):
            await asyncio.sleep(max(0.0, spec.stall_end_s - elapsed()))
        async with slots:
            await asyncio.sleep(svc)
        return {"served": True}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "capacity": spec.server_capacity}

    return app
