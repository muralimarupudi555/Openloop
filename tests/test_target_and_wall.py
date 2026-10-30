"""The bundled target and the wall-clock drivers, on short real runs.

No test here asserts an absolute wall-clock bound on a percentile.
Bounds are expressed as inequalities a loaded runner cannot flip
(ordering, counts, refusals) or as generous multiples, per the rule
that a millisecond assertion is an assertion about the runner.
"""

import asyncio
import builtins
import time

import httpx
import pytest

from openloop.target import build_app
from openloop.wallclock import run_closed_loop_wall, run_open_loop_wall
from openloop.workload import WorkloadSpec

SHORT = WorkloadSpec(
    seed=21, duration_s=1.5, rate_rps=40.0, workers=4, service_mean_s=0.005, server_capacity=8
)
SHORT_STALL = WorkloadSpec(
    seed=21,
    duration_s=1.5,
    rate_rps=40.0,
    workers=4,
    service_mean_s=0.005,
    server_capacity=8,
    stall_start_s=0.6,
    stall_duration_s=0.3,
)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://openloop.local", timeout=None
    )


def run(coro):
    return asyncio.run(coro)


class TestTargetContract:
    def test_work_before_start_is_refused_with_409(self):
        async def scenario():
            app = build_app(SHORT)
            async with _client(app) as client:
                return (await client.get("/work", params={"svc": 0.001})).status_code

        assert run(scenario()) == 409

    def test_health_reports_the_configured_capacity(self):
        async def scenario():
            app = build_app(SHORT)
            async with _client(app) as client:
                return (await client.get("/health")).json()

        assert run(scenario())["capacity"] == SHORT.server_capacity

    @pytest.mark.parametrize("bad_svc", [-0.1, 999.0])
    def test_service_times_outside_the_contract_are_refused(self, bad_svc):
        async def scenario():
            app = build_app(SHORT)
            async with _client(app) as client:
                await client.post("/start")
                return (await client.get("/work", params={"svc": bad_svc})).status_code

        assert run(scenario()) == 422

    def test_two_apps_hold_fully_independent_state(self):
        async def scenario():
            a, b = build_app(SHORT), build_app(SHORT)
            async with _client(a) as ca, _client(b) as cb:
                await ca.post("/start")
                started = (await ca.get("/work", params={"svc": 0.0})).status_code
                refused = (await cb.get("/work", params={"svc": 0.0})).status_code
                return started, refused

        assert run(scenario()) == (200, 409)

    def test_the_semaphore_holds_concurrency_at_capacity(self):
        """Counts, not milliseconds: peak concurrent sleeps <= capacity."""
        spec = WorkloadSpec(seed=1, duration_s=1.0, server_capacity=3)
        peak = {"now": 0, "max": 0}
        real_sleep = asyncio.sleep

        async def counting_sleep(delay, *args, **kwargs):
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            try:
                return await real_sleep(delay, *args, **kwargs)
            finally:
                peak["now"] -= 1

        async def scenario(monkey_sleep):
            app = build_app(spec)
            async with _client(app) as client:
                await client.post("/start")
                import openloop.target as target_module

                original = target_module.asyncio.sleep
                target_module.asyncio.sleep = monkey_sleep
                try:
                    await asyncio.gather(
                        *(client.get("/work", params={"svc": 0.02}) for _ in range(12))
                    )
                finally:
                    target_module.asyncio.sleep = original

        run(scenario(counting_sleep))
        assert peak["max"] <= spec.server_capacity

    def test_a_request_during_the_stall_waits_at_least_until_stall_end(self):
        spec = WorkloadSpec(
            seed=1, duration_s=2.0, stall_start_s=0.0, stall_duration_s=0.25, server_capacity=4
        )

        async def scenario():
            app = build_app(spec)
            async with _client(app) as client:
                await client.post("/start")
                t0 = time.monotonic()
                await client.get("/work", params={"svc": 0.0})
                return time.monotonic() - t0

        # Generous lower bound only: the stall must delay the start.
        assert run(scenario()) >= 0.25

    def test_building_the_app_without_fastapi_is_refused_with_guidance(self, monkeypatch):
        """The no-extras install must fail at the boundary, not mid-run."""
        import openloop.target as target_module

        monkeypatch.setattr(target_module, "FastAPI", None)
        with pytest.raises(ModuleNotFoundError, match="openloop\\[wall\\]"):
            build_app(SHORT)


class TestWallDrivers:
    def test_the_open_loop_wall_driver_sends_every_intended_request(self):
        result = run(run_open_loop_wall(SHORT, build_app(SHORT)))
        assert result.sent == result.intended
        assert result.completed == result.sent
        assert result.omitted == 0

    def test_the_closed_loop_wall_driver_accounts_for_every_slot(self):
        result = run(run_closed_loop_wall(SHORT, build_app(SHORT)))
        assert result.sent + result.omitted == result.intended
        assert result.completed == result.sent

    def test_a_stall_produces_omission_on_the_real_clock_too(self):
        result = run(run_closed_loop_wall(SHORT_STALL, build_app(SHORT_STALL)))
        assert result.omitted > 0

    def test_the_open_loop_wall_tail_sees_the_stall_and_the_closed_median_does_not(self):
        """At this sample size the closed p99 is NOT blind, and that is
        the point: four workers over fifty sends make the stall 8% of
        the closed-loop samples, which is above the 1% a p99 ignores.
        Blindness at a quantile q needs workers/sent below (100-q)/100,
        so the robust cross-driver property is tail versus median.
        """
        open_result = run(run_open_loop_wall(SHORT_STALL, build_app(SHORT_STALL)))
        closed_result = run(run_closed_loop_wall(SHORT_STALL, build_app(SHORT_STALL)))
        assert open_result.percentile(99.0) >= 0.5 * SHORT_STALL.stall_duration_s
        assert closed_result.percentile(50.0) < 0.1 * SHORT_STALL.stall_duration_s

    def test_the_wall_driver_without_httpx_is_refused_with_guidance(self, monkeypatch):
        import openloop.wallclock as wall_module

        monkeypatch.setattr(wall_module, "httpx", None)
        with pytest.raises(ModuleNotFoundError, match="openloop\\[wall\\]"):
            run(run_open_loop_wall(SHORT, object()))

    def test_the_refusal_path_works_with_httpx_truly_unimportable(self, monkeypatch):
        """Pins the import ordering rule from the no-extras CI trap.

        The guard must trip before anything touches httpx, so it holds
        even when the module cannot be imported at all.
        """
        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name.startswith("httpx"):
                raise ModuleNotFoundError("No module named 'httpx'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)
        import importlib

        import openloop.wallclock as wall_module

        importlib.reload(wall_module)
        try:
            with pytest.raises(ModuleNotFoundError, match="openloop\\[wall\\]"):
                run(wall_module.run_open_loop_wall(SHORT, object()))
        finally:
            monkeypatch.setattr(builtins, "__import__", real_import)
            importlib.reload(wall_module)
