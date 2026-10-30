"""The CLI contract: exit codes, config loading, output shapes."""

import json

import pytest

from openloop.cli import EXIT_OK, EXIT_OMISSION, EXIT_TOOL_FAILURE, main

QUIET = [
    "--seed", "11", "--duration-s", "4", "--rate-rps", "100",
    "--workers", "4", "--server-capacity", "16",
]
STALLED = QUIET + ["--stall-start-s", "2", "--stall-duration-s", "0.4"]


class TestExitCodes:
    def test_a_clean_closed_loop_run_exits_zero(self, capsys):
        assert main(["run", "--generator", "closed", *QUIET]) == EXIT_OK

    def test_a_closed_loop_run_that_omits_exits_three_not_one(self, capsys):
        """Pins the contract that 'the answer is no' is not a crash."""
        assert main(["run", "--generator", "closed", *STALLED]) == EXIT_OMISSION

    def test_an_open_loop_run_exits_zero_even_through_a_stall(self, capsys):
        assert main(["run", "--generator", "open", *STALLED]) == EXIT_OK

    def test_compare_exits_three_when_omission_was_found(self, capsys):
        assert main(["compare", *STALLED]) == EXIT_OMISSION

    def test_compare_exits_zero_on_a_quiet_workload(self, capsys):
        assert main(["compare", *QUIET]) == EXIT_OK

    def test_an_invalid_spec_exits_one_with_a_message_on_stderr(self, capsys):
        code = main(["run", "--generator", "open", "--rate-rps", "-5"])
        assert code == EXIT_TOOL_FAILURE
        assert "rate_rps" in capsys.readouterr().err

    def test_a_missing_config_file_exits_one(self, capsys):
        code = main(["run", "--generator", "open", "--config", "/nonexistent.toml"])
        assert code == EXIT_TOOL_FAILURE

    def test_an_unknown_generator_is_a_usage_error(self):
        with pytest.raises(SystemExit) as excinfo:
            main(["run", "--generator", "sideways"])
        assert excinfo.value.code == 2

    def test_a_missing_subcommand_is_a_usage_error(self):
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2


class TestOutput:
    def test_the_json_flag_emits_parseable_json(self, capsys):
        main(["run", "--generator", "open", "--json", *QUIET])
        payload = json.loads(capsys.readouterr().out)
        assert payload["generator"] == "open"

    def test_compare_json_carries_the_headline_fields(self, capsys):
        main(["compare", "--json", *STALLED])
        payload = json.loads(capsys.readouterr().out)
        assert "understatement_p99" in payload
        assert payload["omitted"] > 0

    def test_the_table_output_prints_the_understatement_sentence(self, capsys):
        main(["compare", *STALLED])
        out = capsys.readouterr().out
        assert "understates" in out
        assert "never sent" in out

    def test_the_run_table_has_a_header_row(self, capsys):
        main(["run", "--generator", "open", *QUIET])
        assert "p99 ms" in capsys.readouterr().out


class TestConfig:
    def test_flags_override_values_from_the_config_file(self, tmp_path, capsys):
        config = tmp_path / "work.toml"
        config.write_text("duration_s = 4.0\nrate_rps = 50.0\nseed = 11\n")
        main([
            "run", "--generator", "open", "--config", str(config),
            "--rate-rps", "100", "--json",
        ])
        payload = json.loads(capsys.readouterr().out)
        # 100 rps over 4 seconds, not 50 rps.
        assert payload["sent"] > 300

    def test_a_config_only_invocation_works(self, tmp_path, capsys):
        config = tmp_path / "work.toml"
        config.write_text("duration_s = 2.0\nrate_rps = 50.0\nseed = 1\n")
        assert main(["run", "--generator", "open", "--config", str(config)]) == EXIT_OK


class TestShippedExamples:
    @pytest.mark.parametrize("example", ["examples/headline.toml", "examples/sweep-knee.toml"])
    def test_every_shipped_example_config_loads_and_validates(self, example):
        from pathlib import Path

        from openloop.workload import WorkloadSpec

        root = Path(__file__).resolve().parent.parent
        spec = WorkloadSpec.from_toml(root / example)
        assert spec.rate_rps > 0
