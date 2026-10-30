"""Fail the build when a document quotes a figure the code no longer produces.

Loads docs/metrics.json and holds every checked document to it:

1. Anchor check. Each metric carries anchor phrases, the exact wording
   a document uses with the value substituted in. Any anchor found
   with a different number is a stale claim and fails the build.
   Anchors match phrases, not bare digits, because a bare digit check
   passes while the sentence around it has gone stale, and because
   small numbers appear everywhere by coincidence.
2. Presence check. Metrics listed as required_in_readme must appear in
   the README through at least one anchor; a headline nothing
   re-measures is not a headline.
3. Reverse check. Every other number in a checked document must equal
   some metric's value or sit on the allowlist (years, versions,
   quantile labels, exit codes). Fenced code blocks, inline code and
   HTML attributes are excluded, because an example invocation is
   allowed to contain a made-up figure. Findings are reported, and
   --strict turns them fatal; the default stays advisory so a check
   that someone disagrees with gets argued about rather than deleted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "docs" / "metrics.json"

ALLOWLIST_PATTERNS = [
    r"^(19|20)\d\d$",               # years
    r"^3\.1[0-3]$",                 # Python versions in the CI matrix
    r"^\d+\.\d+\.\d+$",             # semantic versions
    r"^00[1-9]$",                   # ADR numbers
    r"^(0|1|2|3)$",                 # exit codes and tiny ordinals, anchor-only per rule 3
    r"^(50|90|95|99|99\.9|100)$",   # quantile labels and percent scales
    r"^10$",                        # the 10 second stall period, part of the scenario name
    r"^500$",                       # the 500 ms stall, part of the scenario name
    r"^60$",                        # the 60 second window, part of the scenario name
    r"^16$",                        # server capacity in the headline spec
    r"^8$",                         # worker count in the headline spec
    r"^200$",                       # offered rate in the headline spec
    r"^1\.5$",                      # the published divergence ratio definition
    r"^1\.02$",                     # the histogram growth factor
    r"^25$",                        # the E4 scenario's service mean in ms
    r"^30$",                        # sweep duration in the E3 scenario
]


def format_value(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    text = f"{value}"
    return text


def strip_uncheckable(markdown: str) -> str:
    """Remove fenced code, inline code and HTML tags from a document."""
    no_fences = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    no_inline = re.sub(r"`[^`\n]*`", " ", no_fences)
    no_html = re.sub(r"<[^>]+>", " ", no_inline)
    return no_html


def anchor_regex(anchor: str) -> re.Pattern:
    escaped = re.escape(anchor).replace(r"\{\}", r"(\d[\d,]*(?:\.\d+)?)")
    return re.compile(escaped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="treat unreceipted numbers as failures, not reports")
    args = parser.parse_args()

    payload = json.loads(METRICS.read_text())
    metrics: dict = payload["metrics"]
    anchors: dict = payload["anchors"]
    required = set(payload.get("required_in_readme", []))

    known_values = set()
    for value in metrics.values():
        text = format_value(value)
        known_values.add(text)
        if text.endswith(".0"):
            known_values.add(text[:-2])

    failures: list[str] = []
    reports: list[str] = []
    readme_hits: set[str] = set()

    for relative in payload["checked_documents"]:
        path = ROOT / relative
        if not path.exists():
            failures.append(f"{relative}: checked document is missing")
            continue
        body = strip_uncheckable(path.read_text())

        for name, phrases in anchors.items():
            expected = format_value(metrics[name])
            for phrase in phrases:
                for match in anchor_regex(phrase).finditer(body):
                    found = match.group(1).replace(",", "")
                    if found != expected and found != expected.rstrip("0").rstrip("."):
                        failures.append(
                            f"{relative}: stale figure for {name}: anchor {phrase!r} "
                            f"carries {found}, the code produces {expected}"
                        )
                    elif relative == "README.md":
                        readme_hits.add(name)

        for match in re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w.])", body):
            token = match.group(1).replace(",", "")
            if token in known_values:
                continue
            if any(re.match(p, token) for p in ALLOWLIST_PATTERNS):
                continue
            context = body[max(0, match.start() - 30): match.end() + 20].replace("\n", " ")
            reports.append(f"{relative}: unreceipted number {token} near '...{context}...'")

    for name in sorted(required - readme_hits):
        failures.append(
            f"README.md: required metric {name} appears through no anchor; "
            "a headline nothing re-measures is not a headline"
        )

    for line in reports:
        print(f"REPORT  {line}")
    for line in failures:
        print(f"FAIL    {line}")
    if not failures and not reports:
        print(f"check_numbers: {len(metrics)} metrics verified across "
              f"{len(payload['checked_documents'])} documents, nothing stale")
    elif not failures:
        print(f"check_numbers: no stale figures; {len(reports)} unreceipted numbers reported")

    if failures or (args.strict and reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
