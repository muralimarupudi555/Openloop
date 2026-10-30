"""Collect every published figure from the machine, never from a hand.

Reads the test count from junit.xml, coverage from coverage.json, and
every experiment figure from docs/experiments/*.json, then writes
docs/metrics.json: the values, the anchor phrases each document must
use around them, and the list of documents check_numbers.py holds to
them. Nothing in the output is typed by a person.

Run with --skip-tests in CI, where pytest already ran as its own step
and left junit.xml and coverage.json behind; without the flag the
suite is run here first.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "docs" / "experiments"
METRICS = ROOT / "docs" / "metrics.json"

CHECKED_DOCUMENTS = [
    "README.md",
    "docs/defense-guide.md",
    "docs/adr/ADR-001-virtual-clock-receipts.md",
    "docs/adr/ADR-002-poisson-arrivals.md",
    "docs/adr/ADR-003-plain-asyncio-over-a-framework.md",
    "docs/adr/ADR-004-in-repo-histogram.md",
    "docs/adr/ADR-005-what-this-cannot-measure.md",
]

EXPERIMENT_SCRIPTS = {
    "e1_null": "experiments/e1_null.py",
    "e2_stall": "experiments/e2_stall.py",
    "e3_sweep": "experiments/e3_sweep.py",
    "e4_sim_vs_wall": "experiments/e4_sim_vs_wall.py",
}


def run_tests() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--junitxml=junit.xml",
            "--cov=openloop",
            "--cov-report=json",
            "-q",
        ],
        cwd=ROOT,
        check=True,
    )


def read_test_count() -> int:
    """From junit.xml, never from a parsed progress line."""
    junit = ROOT / "junit.xml"
    if not junit.exists():
        raise SystemExit(
            "collect_metrics: junit.xml not found. Run 'make test' first, "
            "or drop --skip-tests so the suite runs here."
        )
    root = ET.parse(junit).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    if failures:
        raise SystemExit(f"collect_metrics: refusing to publish over {failures} failing tests")
    return tests


def read_coverage_pct() -> float:
    payload = json.loads((ROOT / "coverage.json").read_text())
    return round(payload["totals"]["percent_covered"], 1)


def read_experiment(name: str) -> dict:
    path = EXPERIMENTS / f"{name}.json"
    if not path.exists():
        print(f"collect_metrics: {path.name} missing, running {EXPERIMENT_SCRIPTS[name]}")
        subprocess.run([sys.executable, EXPERIMENT_SCRIPTS[name]], cwd=ROOT, check=True)
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true",
                        help="read junit.xml and coverage.json left by a prior pytest step")
    args = parser.parse_args()

    if not args.skip_tests:
        run_tests()

    e1 = read_experiment("e1_null")
    e2 = read_experiment("e2_stall")
    e3 = read_experiment("e3_sweep")
    e4 = read_experiment("e4_sim_vs_wall")

    from openloop.histogram import LogHistogram

    hist = LogHistogram()
    metrics = {
        "tests_total": read_test_count(),
        "coverage_pct": read_coverage_pct(),
        "e2_understatement_p99": e2["understatement_p99"],
        "e2_omitted": e2["omitted"],
        "e2_omitted_fraction_pct": e2["omitted_fraction_pct"],
        "e2_windows": e2["spec"]["stall_windows"],
        "e2_open_p99_ms": round(e2["open"]["percentiles_ms"]["99.0"], 1),
        "e2_closed_p99_ms": round(e2["closed"]["percentiles_ms"]["99.0"], 1),
        "e2_open_stall_share_pct": e2["open_stall_share_pct"],
        "e2_closed_stall_share_pct": e2["closed_stall_share_pct"],
        "e2_single_p99_ratio": e2["single_stall"]["open_p99_understatement"],
        "e2_single_open_share_pct": e2["single_stall"]["open_stall_share_pct"],
        "e2_single_p999_ratio": e2["single_stall"]["p999_understatement"],
        "e1_p50_delta_pct": e1["p50_delta_pct"],
        "e1_p99_delta_pct": e1["p99_delta_pct"],
        "e3_knee_rps": int(e3["knee_rps"]),
        "e3_capacity_rps": int(e3["server"]["theoretical_max_rps"]),
        "e3_top_ratio": e3["points"][-1]["ratio"],
        "e4_tolerance_pct": int(e4["tolerance_pct"]),
        "hist_error_pct": round(hist.max_relative_error * 100.0, 3),
    }
    if not e4["passed"]:
        raise SystemExit("collect_metrics: E4 failed its tolerance; nothing to publish")

    anchors = {
        "tests_total": ["{} tests", "{} of them"],
        "coverage_pct": ["{} percent line and branch coverage"],
        "e2_understatement_p99": ["by {}x", "factor of {}"],
        "e2_omitted": ["{} intended requests", "{} fewer requests"],
        "e2_omitted_fraction_pct": ["{} percent of its own schedule"],
        "e2_windows": ["{} pauses", "{} windows"],
        "e2_open_p99_ms": ["p99 of {} ms", "open loop reports {} ms"],
        "e2_closed_p99_ms": ["closed loop reports {} ms"],
        "e2_open_stall_share_pct": ["{} percent of the open-loop samples"],
        "e2_closed_stall_share_pct": ["{} percent of the closed-loop samples"],
        "e2_single_p99_ratio": ["ratio collapses to {}", "a ratio of {}"],
        "e2_single_open_share_pct": ["{} percent in the single-stall run"],
        "e2_single_p999_ratio": ["{}x at p99.9"],
        "e1_p50_delta_pct": ["measured median delta of {} percent"],
        "e1_p99_delta_pct": ["measured p99 delta of {} percent"],
        "e3_knee_rps": ["above {} rps", "at {} rps the"],
        "e3_capacity_rps": ["a {} rps server", "{} rps of theoretical"],
        "e3_top_ratio": ["ratio reaches {}", "to {} by the top"],
        "e4_tolerance_pct": ["within {} percent"],
        "hist_error_pct": ["{} percent worst-case", "error of {} percent"],
    }

    payload = {
        "metrics": metrics,
        "anchors": anchors,
        "required_in_readme": [
            "tests_total",
            "coverage_pct",
            "e2_understatement_p99",
            "e2_omitted",
            "e3_knee_rps",
            "e4_tolerance_pct",
        ],
        "checked_documents": CHECKED_DOCUMENTS,
        "note": "every value here is produced by running the suite and the experiments",
    }
    METRICS.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"collect_metrics: wrote {len(metrics)} metrics to {METRICS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
