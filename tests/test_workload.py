"""Properties of the workload model: validation, determinism, schedules."""

import pytest

from openloop.workload import (
    WorkloadError,
    WorkloadSpec,
    closed_loop_slots,
    open_loop_arrivals,
    service_time,
)


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"duration_s": 0.0},
            {"duration_s": -1.0},
            {"rate_rps": 0.0},
            {"rate_rps": -10.0},
            {"workers": 0},
            {"workers": -3},
            {"service_mean_s": 0.0},
            {"service_mean_s": -0.01},
            {"service_sigma": -0.1},
            {"server_capacity": 0},
            {"stall_duration_s": -0.5},
            {"stall_start_s": -1.0},
            {"warmup_s": -1.0},
        ],
    )
    def test_an_unrunnable_spec_is_refused_at_construction(self, kwargs):
        with pytest.raises(WorkloadError):
            WorkloadSpec(**kwargs)

    def test_a_stall_starting_after_the_run_ends_is_refused(self):
        with pytest.raises(WorkloadError):
            WorkloadSpec(duration_s=10.0, stall_start_s=10.0)

    def test_a_warmup_covering_the_whole_run_is_refused(self):
        with pytest.raises(WorkloadError):
            WorkloadSpec(duration_s=10.0, warmup_s=10.0)

    def test_the_error_message_names_the_offending_value(self):
        with pytest.raises(WorkloadError, match="-7"):
            WorkloadSpec(rate_rps=-7)

    def test_a_valid_spec_constructs_with_defaults(self):
        spec = WorkloadSpec()
        assert spec.rate_rps > 0


class TestStallWindow:
    def test_no_stall_means_in_stall_is_always_false(self):
        spec = WorkloadSpec()
        assert not spec.in_stall(0.0)
        assert not spec.in_stall(30.0)

    @pytest.mark.parametrize(
        "t,expected", [(9.99, False), (10.0, True), (10.49, True), (10.5, False)]
    )
    def test_the_stall_window_is_half_open(self, t, expected):
        spec = WorkloadSpec(stall_start_s=10.0, stall_duration_s=0.5)
        assert spec.in_stall(t) is expected

    def test_a_zero_length_stall_never_stalls(self):
        spec = WorkloadSpec(stall_start_s=10.0, stall_duration_s=0.0)
        assert not spec.in_stall(10.0)

    def test_stall_end_is_start_plus_duration(self):
        spec = WorkloadSpec(stall_start_s=10.0, stall_duration_s=0.5)
        assert spec.stall_end_s == 10.5


class TestOpenLoopArrivals:
    def test_arrivals_are_identical_for_the_same_seed(self):
        spec = WorkloadSpec(seed=3, duration_s=5.0)
        assert open_loop_arrivals(spec) == open_loop_arrivals(spec)

    def test_arrivals_differ_for_different_seeds(self):
        a = open_loop_arrivals(WorkloadSpec(seed=1, duration_s=5.0))
        b = open_loop_arrivals(WorkloadSpec(seed=2, duration_s=5.0))
        assert a != b

    def test_arrivals_are_sorted_and_inside_the_run(self):
        arrivals = open_loop_arrivals(WorkloadSpec(seed=3, duration_s=5.0))
        assert arrivals == sorted(arrivals)
        assert all(0 < t < 5.0 for t in arrivals)

    def test_the_arrival_count_tracks_rate_times_duration(self):
        spec = WorkloadSpec(seed=3, duration_s=50.0, rate_rps=100.0)
        count = len(open_loop_arrivals(spec))
        assert 0.9 * 5000 < count < 1.1 * 5000

    def test_arrivals_do_not_depend_on_server_parameters(self):
        a = open_loop_arrivals(WorkloadSpec(seed=3, duration_s=5.0, server_capacity=1))
        b = open_loop_arrivals(WorkloadSpec(seed=3, duration_s=5.0, server_capacity=64))
        assert a == b


class TestClosedLoopSlots:
    def test_slots_are_identical_for_the_same_spec(self):
        spec = WorkloadSpec(seed=3, duration_s=5.0)
        assert closed_loop_slots(spec, 0) == closed_loop_slots(spec, 0)

    def test_each_worker_keeps_the_pacing_interval_between_slots(self):
        spec = WorkloadSpec(duration_s=5.0, rate_rps=100.0, workers=4)
        slots = closed_loop_slots(spec, 1)
        gaps = [b - a for a, b in zip(slots, slots[1:], strict=False)]
        assert all(abs(g - spec.pacing_interval_s) < 1e-9 for g in gaps)

    def test_workers_are_offset_so_slots_interleave(self):
        spec = WorkloadSpec(duration_s=5.0, rate_rps=100.0, workers=4)
        firsts = [closed_loop_slots(spec, w)[0] for w in range(4)]
        assert firsts == sorted(firsts)
        assert len(set(firsts)) == 4

    @pytest.mark.parametrize(
        "duration,rate,workers",
        [(5.0, 100.0, 4), (10.0, 50.0, 2), (3.0, 300.0, 8), (60.0, 200.0, 8)],
    )
    def test_the_aggregate_slot_count_offers_the_requested_rate(self, duration, rate, workers):
        spec = WorkloadSpec(duration_s=duration, rate_rps=rate, workers=workers)
        total = sum(len(closed_loop_slots(spec, w)) for w in range(workers))
        assert abs(total - duration * rate) <= workers

    @pytest.mark.parametrize("bad_worker", [-1, 4, 99])
    def test_a_worker_index_outside_the_pool_is_refused(self, bad_worker):
        spec = WorkloadSpec(workers=4)
        with pytest.raises(WorkloadError):
            closed_loop_slots(spec, bad_worker)

    def test_the_pacing_interval_is_workers_over_rate(self):
        spec = WorkloadSpec(rate_rps=200.0, workers=8)
        assert spec.pacing_interval_s == pytest.approx(0.04)


class TestServiceTimes:
    def test_the_same_request_id_always_gets_the_same_service_time(self):
        """Pins the design rule that lets wall-clock replay the simulator.

        Service time is a pure function of (seed, request id), not a
        draw from a shared stream, so the value cannot depend on the
        order a driver processes requests in.
        """
        spec = WorkloadSpec(seed=4)
        assert service_time(spec, 17) == service_time(spec, 17)

    def test_different_request_ids_get_different_service_times(self):
        spec = WorkloadSpec(seed=4)
        draws = {service_time(spec, i) for i in range(50)}
        assert len(draws) == 50

    def test_sigma_zero_makes_service_time_constant(self):
        spec = WorkloadSpec(service_sigma=0.0, service_mean_s=0.015)
        assert all(service_time(spec, i) == 0.015 for i in range(10))

    def test_the_sample_mean_tracks_the_configured_mean(self):
        spec = WorkloadSpec(seed=4, service_mean_s=0.010)
        draws = [service_time(spec, i) for i in range(4000)]
        assert 0.009 < sum(draws) / len(draws) < 0.011

    def test_service_times_are_always_positive(self):
        spec = WorkloadSpec(seed=4)
        assert all(service_time(spec, i) > 0 for i in range(200))

    def test_seeding_accepts_any_seed_integer(self):
        """Pins a real bug: tuple seeds crash on modern Python.

        The first draft seeded random.Random with a tuple like
        (seed, "service", request_id). CPython 3.11 restricted seed
        types and 3.13 raises TypeError for tuples, so the very first
        smoke run of the CLI crashed before producing a number. The
        fix derives a string key instead. This test exists so the
        seeding path is exercised on every Python in the CI matrix.
        """
        spec = WorkloadSpec(seed=2**63)
        assert service_time(spec, 0) > 0
        assert open_loop_arrivals(WorkloadSpec(seed=2**63, duration_s=0.5))


class TestTomlLoading:
    def test_a_spec_round_trips_through_toml(self, tmp_path):
        config = tmp_path / "work.toml"
        config.write_text('rate_rps = 250.0\nworkers = 4\nstall_start_s = 2.0\n'
                          'stall_duration_s = 0.25\nduration_s = 6.0\n')
        spec = WorkloadSpec.from_toml(config)
        assert spec.rate_rps == 250.0
        assert spec.stall_start_s == 2.0

    def test_unknown_keys_in_the_config_are_refused_not_ignored(self, tmp_path):
        config = tmp_path / "work.toml"
        config.write_text("stall_duration = 0.5\n")
        with pytest.raises(WorkloadError, match="stall_duration"):
            WorkloadSpec.from_toml(config)

    def test_values_from_toml_are_validated_like_any_other(self, tmp_path):
        config = tmp_path / "work.toml"
        config.write_text("rate_rps = -1.0\n")
        with pytest.raises(WorkloadError):
            WorkloadSpec.from_toml(config)


class TestStallEndWithoutAStall:
    def test_stall_end_without_a_stall_is_zero(self):
        assert WorkloadSpec().stall_end_s == 0.0


class TestPeriodicStall:
    def test_a_period_without_a_start_is_refused(self):
        with pytest.raises(WorkloadError, match="anchor"):
            WorkloadSpec(stall_period_s=10.0, stall_duration_s=0.5)

    @pytest.mark.parametrize("period", [0.5, 0.4, 0.0])
    def test_a_period_not_exceeding_the_duration_is_refused(self, period):
        with pytest.raises(WorkloadError):
            WorkloadSpec(stall_start_s=1.0, stall_duration_s=0.5, stall_period_s=period)

    @pytest.mark.parametrize(
        "t,expected",
        [
            (4.9, False),
            (5.0, True),
            (5.49, True),
            (5.5, False),
            (14.9, False),
            (15.0, True),
            (15.2, True),
            (15.5, False),
            (25.0, True),
        ],
    )
    def test_the_stall_recurs_every_period(self, t, expected):
        spec = WorkloadSpec(
            duration_s=30.0, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0
        )
        assert spec.in_stall(t) is expected

    def test_before_the_first_stall_nothing_stalls(self):
        spec = WorkloadSpec(
            duration_s=30.0, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0
        )
        assert not spec.in_stall(0.0)

    def test_stall_end_at_points_at_the_current_window(self):
        spec = WorkloadSpec(
            duration_s=30.0, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0
        )
        assert spec.stall_end_at(15.2) == pytest.approx(15.5)
        assert spec.stall_end_at(5.0) == pytest.approx(5.5)

    def test_stall_windows_enumerates_every_window_in_the_run(self):
        spec = WorkloadSpec(
            duration_s=30.0, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0
        )
        assert spec.stall_windows() == [(5.0, 5.5), (15.0, 15.5), (25.0, 25.5)]

    def test_a_single_stall_yields_one_window(self):
        spec = WorkloadSpec(duration_s=30.0, stall_start_s=5.0, stall_duration_s=0.5)
        assert spec.stall_windows() == [(5.0, 5.5)]

    def test_no_stall_yields_no_windows(self):
        assert WorkloadSpec().stall_windows() == []


class TestStallBoundaryExactness:
    @pytest.mark.parametrize("t", [5.0, 5.1, 5.2999999, 15.0, 15.49999, 95.0, 95.2, 1005.3])
    def test_the_wakeup_time_for_a_stalled_moment_is_never_itself_stalled(self, t):
        """Pins the hang: a wakeup at the window end must leave the stall.

        The first periodic implementation reconstructed the window end
        from a float modulo phase. At the scheduled wakeup time the
        recomputed phase came back one ulp below the duration, so the
        simulator saw itself still stalled and scheduled another wakeup
        one ulp later, billions of times. The symptom was a test run
        that never finished. This test holds the boundary exact for
        times across many periods, where the float error accumulates.
        """
        spec = WorkloadSpec(
            duration_s=2000.0, stall_start_s=5.0, stall_duration_s=0.5, stall_period_s=10.0
        )
        if spec.in_stall(t):
            assert not spec.in_stall(spec.stall_end_at(t))
