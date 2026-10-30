"""Properties of result summaries, comparison and the terminal table."""

import json

import pytest

from openloop.results import compare, table
from openloop.sim import run_closed_loop, run_open_loop


class TestComparison:
    def test_compare_wants_one_of_each_generator(self, quiet_spec):
        open_result = run_open_loop(quiet_spec)
        with pytest.raises(ValueError, match="open"):
            compare(open_result, open_result)

    def test_the_understatement_ratio_is_open_over_closed(self, stall_spec):
        comparison = compare(run_open_loop(stall_spec), run_closed_loop(stall_spec))
        expected = comparison.open_result.percentile(99.0) / comparison.closed_result.percentile(
            99.0
        )
        assert comparison.understatement(99.0) == pytest.approx(expected)

    def test_without_a_stall_the_understatement_is_near_one(self, quiet_spec):
        comparison = compare(run_open_loop(quiet_spec), run_closed_loop(quiet_spec))
        assert 0.8 < comparison.understatement(50.0) < 1.2

    def test_with_a_stall_the_understatement_exceeds_five(self, stall_spec):
        comparison = compare(run_open_loop(stall_spec), run_closed_loop(stall_spec))
        assert comparison.understatement(99.0) > 5.0

    def test_the_comparison_summary_carries_the_omission_count(self, stall_spec):
        comparison = compare(run_open_loop(stall_spec), run_closed_loop(stall_spec))
        summary = comparison.summary()
        assert summary["omitted"] == comparison.closed_result.omitted
        assert summary["understatement_p99"] > 1.0


class TestSummaries:
    def test_a_summary_is_json_serialisable(self, quiet_spec):
        summary = run_open_loop(quiet_spec).summary()
        assert json.loads(json.dumps(summary)) == summary

    def test_a_summary_reports_latency_in_milliseconds(self, quiet_spec):
        result = run_open_loop(quiet_spec)
        summary = result.summary()
        assert summary["percentiles_ms"]["50.0"] == pytest.approx(
            result.percentile(50.0) * 1000.0, rel=1e-3
        )

    def test_a_summary_names_its_generator(self, quiet_spec):
        assert run_closed_loop(quiet_spec).summary()["generator"] == "closed"

    def test_omitted_fraction_of_a_zero_intended_result_is_zero(self, quiet_spec):
        result = run_open_loop(quiet_spec)
        result.intended = 0
        assert result.omitted_fraction == 0.0


class TestTable:
    def test_the_table_has_one_row_per_result_plus_header(self, quiet_spec):
        results = [run_open_loop(quiet_spec), run_closed_loop(quiet_spec)]
        lines = table(results).splitlines()
        assert len(lines) == 2 + len(results)

    def test_the_table_names_both_generators(self, quiet_spec):
        rendered = table([run_open_loop(quiet_spec), run_closed_loop(quiet_spec)])
        assert "open" in rendered
        assert "closed" in rendered

    def test_the_table_reports_the_omission_column(self, stall_spec):
        closed = run_closed_loop(stall_spec)
        rendered = table([closed])
        assert str(closed.omitted) in rendered


class TestEdgeCases:
    def test_an_understatement_with_a_zero_closed_percentile_is_refused(self, quiet_spec):
        from openloop.results import Comparison

        open_result = run_open_loop(quiet_spec)
        closed_result = run_closed_loop(quiet_spec)

        class ZeroPercentile(type(closed_result)):
            def percentile(self, q):
                return 0.0

        zero = ZeroPercentile(**{f: getattr(closed_result, f) for f in (
            "generator", "spec", "histogram", "intended", "sent", "completed", "omitted"
        )})
        with pytest.raises(ZeroDivisionError):
            Comparison(open_result, zero).understatement(99.0)
