"""Properties of the log-bucket histogram, including its error bound."""

import math
import random

import pytest

from openloop.histogram import DEFAULT_GROWTH, HistogramError, LogHistogram


class TestConstruction:
    def test_a_fresh_histogram_is_empty(self):
        assert LogHistogram().total == 0

    def test_the_default_layout_covers_microseconds_to_minutes(self):
        h = LogHistogram()
        assert h.min_value == 1e-6
        assert h.max_value == 100.0

    def test_the_stated_error_bound_follows_from_the_growth_factor(self):
        h = LogHistogram()
        assert h.max_relative_error == pytest.approx(math.sqrt(DEFAULT_GROWTH) - 1.0)

    def test_the_default_error_bound_is_below_one_percent(self):
        assert LogHistogram().max_relative_error < 0.01

    @pytest.mark.parametrize("bad_min", [0.0, -1.0, -1e-9])
    def test_a_non_positive_min_value_is_refused(self, bad_min):
        with pytest.raises(HistogramError):
            LogHistogram(min_value=bad_min)

    @pytest.mark.parametrize("bad_growth", [1.0, 0.5, 0.0, -2.0])
    def test_a_growth_factor_at_or_below_one_is_refused(self, bad_growth):
        with pytest.raises(HistogramError):
            LogHistogram(growth=bad_growth)

    def test_a_max_value_at_or_below_min_value_is_refused(self):
        with pytest.raises(HistogramError):
            LogHistogram(min_value=1.0, max_value=1.0)

    def test_bucket_count_is_finite_and_positive(self):
        assert 0 < LogHistogram().bucket_count < 2_000_000


class TestRecording:
    def test_recording_increments_the_total(self):
        h = LogHistogram()
        h.record(0.01)
        assert h.total == 1

    @pytest.mark.parametrize("value", [1e-7, 1e-9, 0.0])
    def test_values_below_range_clamp_into_the_underflow_bucket(self, value):
        h = LogHistogram()
        h.record(value)
        assert h.underflow == 1

    @pytest.mark.parametrize("value", [100.0, 500.0, 1e6])
    def test_values_at_or_above_range_clamp_into_the_overflow_bucket(self, value):
        h = LogHistogram()
        h.record(value)
        assert h.overflow == 1

    def test_min_and_max_seen_track_the_raw_values_not_the_buckets(self):
        h = LogHistogram()
        h.record(0.0123)
        h.record(0.0456)
        assert h.min_seen == 0.0123
        assert h.max_seen == 0.0456

    @pytest.mark.parametrize("bad", [float("nan"), -0.001, -5.0])
    def test_negative_or_nan_samples_are_refused(self, bad):
        with pytest.raises(HistogramError):
            LogHistogram().record(bad)


class TestPercentiles:
    def test_a_percentile_of_an_empty_histogram_is_refused(self):
        with pytest.raises(HistogramError):
            LogHistogram().percentile(50)

    @pytest.mark.parametrize("bad_q", [-1, 101, 1000])
    def test_a_quantile_outside_zero_to_one_hundred_is_refused(self, bad_q):
        h = LogHistogram()
        h.record(0.01)
        with pytest.raises(HistogramError):
            h.percentile(bad_q)

    @pytest.mark.parametrize(
        "value",
        [2e-6, 1e-5, 1e-4, 1e-3, 0.0077, 0.013, 0.09, 0.4, 1.7, 9.0, 42.0, 99.0],
    )
    def test_a_single_sample_is_reported_within_the_error_bound(self, value):
        h = LogHistogram()
        h.record(value)
        reported = h.percentile(50)
        assert abs(reported - value) / value <= h.max_relative_error * 1.000001

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    def test_every_quantile_of_a_random_sample_is_within_the_error_bound(self, seed):
        rng = random.Random(seed)
        values = sorted(rng.uniform(1e-4, 10.0) for _ in range(500))
        h = LogHistogram()
        for v in values:
            h.record(v)
        for q in (1, 10, 25, 50, 75, 90, 99, 100):
            exact = values[max(0, math.ceil(len(values) * q / 100) - 1)]
            reported = h.percentile(q)
            assert abs(reported - exact) / exact <= h.max_relative_error * 1.000001

    def test_percentiles_never_decrease_as_the_quantile_increases(self):
        rng = random.Random(9)
        h = LogHistogram()
        for _ in range(1000):
            h.record(rng.uniform(1e-4, 5.0))
        reported = [h.percentile(q) for q in range(1, 101)]
        assert reported == sorted(reported)

    def test_the_p100_of_identical_samples_equals_their_bucket_midpoint(self):
        h = LogHistogram()
        for _ in range(100):
            h.record(0.02)
        assert h.percentile(100) == h.percentile(1)

    def test_underflowed_samples_report_as_the_range_minimum(self):
        h = LogHistogram()
        h.record(1e-9)
        assert h.percentile(50) == h.min_value

    def test_overflowed_samples_report_as_the_range_maximum(self):
        h = LogHistogram()
        h.record(1e6)
        assert h.percentile(99) == h.max_value


class TestMerge:
    def test_merging_adds_totals_and_bucket_counts(self):
        a, b = LogHistogram(), LogHistogram()
        a.record(0.01)
        b.record(0.02)
        b.record(0.03)
        a.merge(b)
        assert a.total == 3
        assert sum(a.counts()) == 3

    def test_merging_preserves_the_extremes_of_both_sides(self):
        a, b = LogHistogram(), LogHistogram()
        a.record(0.5)
        b.record(0.001)
        b.record(2.0)
        a.merge(b)
        assert a.min_seen == 0.001
        assert a.max_seen == 2.0

    def test_merging_folds_clamp_buckets_too(self):
        a, b = LogHistogram(), LogHistogram()
        b.record(1e-9)
        b.record(1e6)
        a.merge(b)
        assert a.underflow == 1
        assert a.overflow == 1

    def test_merging_a_different_layout_is_refused(self):
        a = LogHistogram()
        b = LogHistogram(growth=1.05)
        with pytest.raises(HistogramError):
            a.merge(b)

    def test_merging_an_empty_histogram_changes_nothing(self):
        a, b = LogHistogram(), LogHistogram()
        a.record(0.01)
        before = (a.total, a.min_seen, a.max_seen)
        a.merge(b)
        assert (a.total, a.min_seen, a.max_seen) == before
