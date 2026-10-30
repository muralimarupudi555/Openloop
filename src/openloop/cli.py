"""Command line interface: exit codes that distinguish 'no' from 'broken'.

This file exists to make the tool scriptable in CI, where the only
thing anyone reads is the exit code. The codes mean:

* 0: the measurement ran and found no coordinated omission.
* 3: the measurement ran and found omission. This is the tool doing
  its job and answering no, which must never look like a crash.
* 1: the tool failed to answer (bad spec, internal error).
* 2: usage error, from argparse.

A gate that cannot tell "the answer is no" from "the question failed"
ends up ignored, so the distinction is the whole design.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from openloop.results import table
from openloop.sim import run_closed_loop, run_open_loop
from openloop.workload import WorkloadError, WorkloadSpec

EXIT_OK = 0
EXIT_TOOL_FAILURE = 1
EXIT_OMISSION = 3

_SPEC_FLAGS = (
    ("seed", int),
    ("duration-s", float),
    ("rate-rps", float),
    ("workers", int),
    ("service-mean-s", float),
    ("service-sigma", float),
    ("server-capacity", int),
    ("stall-start-s", float),
    ("stall-duration-s", float),
    ("stall-period-s", float),
    ("warmup-s", float),
)


def _add_spec_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="TOML file with workload keys; flags override it")
    for flag, kind in _SPEC_FLAGS:
        parser.add_argument(f"--{flag}", type=kind, default=None)


def _build_spec(args: argparse.Namespace) -> WorkloadSpec:
    spec = WorkloadSpec.from_toml(args.config) if args.config else WorkloadSpec()
    overrides = {}
    for flag, _ in _SPEC_FLAGS:
        name = flag.replace("-", "_")
        value = getattr(args, name)
        if value is not None:
            overrides[name] = value
    if overrides:
        spec = replace(spec, **overrides)
    return spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openloop",
        description=(
            "Measure coordinated omission: how much a closed-loop load "
            "generator under-reports the latency an open-loop client sees."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one generator over one workload")
    run.add_argument("--generator", choices=("open", "closed"), required=True)
    _add_spec_arguments(run)
    run.add_argument("--json", action="store_true", help="emit a JSON summary instead of a table")

    comp = sub.add_parser("compare", help="run both generators and report the understatement")
    _add_spec_arguments(comp)
    comp.add_argument("--json", action="store_true", help="emit a JSON summary instead of a table")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = _build_spec(args)
        if args.command == "run":
            runner = run_open_loop if args.generator == "open" else run_closed_loop
            result = runner(spec)
            if args.json:
                print(json.dumps(result.summary(), indent=2))
            else:
                print(table([result]))
            return EXIT_OMISSION if result.omitted > 0 else EXIT_OK

        # compare
        open_result = run_open_loop(spec)
        closed_result = run_closed_loop(spec)
        from openloop.results import compare as compare_results

        comparison = compare_results(open_result, closed_result)
        if args.json:
            print(json.dumps(comparison.summary(), indent=2))
        else:
            print(table([open_result, closed_result]))
            ratio = comparison.understatement(99.0)
            print(
                f"\nclosed-loop p99 understates open-loop p99 by {ratio:.1f}x; "
                f"{closed_result.omitted} intended requests were never sent"
            )
        return EXIT_OMISSION if closed_result.omitted > 0 else EXIT_OK
    except (WorkloadError, OSError, ValueError) as exc:
        print(f"openloop: {exc}", file=sys.stderr)
        return EXIT_TOOL_FAILURE


if __name__ == "__main__":  # pragma: no cover - exercised through console script
    raise SystemExit(main())
