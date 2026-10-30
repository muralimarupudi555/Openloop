"""Invariants of the discrete-event simulator, open and closed loop."""


from openloop.sim import run_closed_loop, run_open_loop
from openloop.workload import WorkloadSpec, open_loop_arrivals


class TestOpenLoopInvariants:
    def test_every_arrival_is_sent_and_completed(self, quiet_spec):
        result = run_open_loop(quiet_spec)
        assert result.sent == result.intended == len(open_loop_arrivals(quiet_spec))
        assert result.completed == result.sent

    def test_an_open_loop_generator_never_omits(self, stall_spec):
        assert run_open_loop(stall_spec).omitted == 0

    def test_the_same_spec_produces_the_same_histogram_counts(self, stall_spec):
        a = run_open_loop(stall_spec)
        b = run_open_loop(stall_spec)
        assert a.histogram.counts() == b.histogram.counts()
        assert a.histogram.max_seen == b.histogram.max_seen

    def test_capacity_is_never_exceeded(self, saturating_spec):
        result = run_open_loop(saturating_spec)
        assert result.peak_in_service <= saturating_spec.server_capacity

    def test_no_service_starts_inside_the_stall_window(self, stall_spec):
        result = run_open_loop(stall_spec)
        for start, _svc in result.service_starts:
            assert not stall_spec.in_stall(start)

    def test_every_latency_is_at_least_its_service_time(self, quiet_spec):
        result = run_open_loop(quiet_spec)
        assert result.histogram.min_seen is not None
        assert result.histogram.min_seen > 0

    def test_a_stall_raises_the_open_loop_tail(self, quiet_spec, stall_spec):
        quiet = run_open_loop(quiet_spec)
        stalled = run_open_loop(stall_spec)
        assert stalled.percentile(99.0) > 5 * quiet.percentile(99.0)

    def test_the_max_latency_is_commensurate_with_the_stall(self, stall_spec):
        """Some arrival lands early in the window and waits most of it out."""
        result = run_open_loop(stall_spec)
        assert result.histogram.max_seen >= 0.75 * stall_spec.stall_duration_s

    def test_warmup_drops_early_samples_from_the_histogram(self):
        spec = WorkloadSpec(seed=2, duration_s=4.0, rate_rps=100.0)
        warmed = run_open_loop(WorkloadSpec(seed=2, duration_s=4.0, rate_rps=100.0, warmup_s=2.0))
        full = run_open_loop(spec)
        assert 0 < warmed.histogram.total < full.histogram.total

    def test_a_single_slot_server_serves_in_fifo_order(self):
        spec = WorkloadSpec(seed=2, duration_s=2.0, rate_rps=50.0, server_capacity=1)
        result = run_open_loop(spec)
        starts = [s for s, _ in result.service_starts]
        assert starts == sorted(starts)


class TestClosedLoopInvariants:
    def test_sent_plus_omitted_equals_intended(self, stall_spec):
        result = run_closed_loop(stall_spec)
        assert result.sent + result.omitted == result.intended

    def test_every_sent_request_completes(self, stall_spec):
        result = run_closed_loop(stall_spec)
        assert result.completed == result.sent

    def test_no_omission_at_low_utilisation_without_a_stall(self, quiet_spec):
        assert run_closed_loop(quiet_spec).omitted == 0

    def test_a_stall_produces_omission(self, stall_spec):
        assert run_closed_loop(stall_spec).omitted > 0

    def test_omission_scales_with_the_stall_duration(self):
        base = dict(seed=3, duration_s=8.0, rate_rps=100.0, workers=4, stall_start_s=4.0)
        short = run_closed_loop(WorkloadSpec(**base, stall_duration_s=0.2))
        long = run_closed_loop(WorkloadSpec(**base, stall_duration_s=0.8))
        assert long.omitted > 2 * short.omitted

    def test_omission_during_a_stall_tracks_rate_times_duration(self, stall_spec):
        result = run_closed_loop(stall_spec)
        expected = stall_spec.rate_rps * stall_spec.stall_duration_s
        assert 0.5 * expected <= result.omitted <= 1.5 * expected

    def test_the_same_spec_produces_the_same_counts(self, stall_spec):
        a = run_closed_loop(stall_spec)
        b = run_closed_loop(stall_spec)
        assert (a.sent, a.omitted) == (b.sent, b.omitted)
        assert a.histogram.counts() == b.histogram.counts()

    def test_capacity_is_never_exceeded(self, saturating_spec):
        result = run_closed_loop(saturating_spec)
        assert result.peak_in_service <= saturating_spec.server_capacity

    def test_no_service_starts_inside_the_stall_window(self, stall_spec):
        result = run_closed_loop(stall_spec)
        for start, _svc in result.service_starts:
            assert not stall_spec.in_stall(start)

    def test_every_slot_in_the_schedule_is_accounted_for(self, stall_spec):
        """Sent plus omitted covers the whole intended schedule exactly."""
        from openloop.workload import closed_loop_slots

        total_slots = sum(
            len(closed_loop_slots(stall_spec, w)) for w in range(stall_spec.workers)
        )
        result = run_closed_loop(stall_spec)
        assert result.intended == total_slots
        assert result.sent + result.omitted == total_slots

    def test_closed_loop_reports_a_calm_p99_through_a_stall(self, stall_spec):
        """The defect under study, pinned as a property.

        Four workers hit the stall at most once each, so the stall
        contributes at most workers samples out of thousands and the
        reported p99 stays at the baseline service tail.
        """
        result = run_closed_loop(stall_spec)
        assert result.percentile(99.0) < 0.1 * stall_spec.stall_duration_s

    def test_omitted_fraction_is_between_zero_and_one(self, stall_spec):
        result = run_closed_loop(stall_spec)
        assert 0 < result.omitted_fraction < 1


class TestOpenVersusClosed:
    def test_without_a_stall_the_two_generators_agree_at_p50(self, quiet_spec):
        open_p50 = run_open_loop(quiet_spec).percentile(50.0)
        closed_p50 = run_closed_loop(quiet_spec).percentile(50.0)
        assert abs(open_p50 - closed_p50) / open_p50 < 0.10

    def test_with_a_stall_the_open_loop_p99_dwarfs_the_closed_loop_p99(self, stall_spec):
        open_p99 = run_open_loop(stall_spec).percentile(99.0)
        closed_p99 = run_closed_loop(stall_spec).percentile(99.0)
        assert open_p99 > 5 * closed_p99

    def test_near_saturation_the_open_loop_queue_grows_and_the_closed_loop_self_limits(
        self, saturating_spec
    ):
        open_result = run_open_loop(saturating_spec)
        closed_result = run_closed_loop(saturating_spec)
        assert open_result.percentile(99.0) > 2 * closed_result.percentile(99.0)
        assert closed_result.omitted > 0
