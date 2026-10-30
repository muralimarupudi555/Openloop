# ADR-001: Published numbers come from the virtual clock, with the real clock as witness

Status: accepted

## Context

The repository publishes latency figures, and latency measured on a wall clock is a fact about the
machine that measured it. A tail percentile moves between a laptop and a loaded CI runner, so a
wall-clock headline either goes stale on the first re-run or teaches the reader to ignore the
receipts check.

## Decision

Every published figure is produced by the discrete-event simulator in `sim.py`, which advances a
virtual clock through an event heap. The same `WorkloadSpec` therefore yields the same histogram to
the last bucket count on every machine and every Python version in the CI matrix, which is what lets
`tools/check_numbers.py` hold documents to exact values.

The wall-clock driver exists to keep the simulator honest, not to produce numbers. Experiment E4
replays one stalled workload on both clocks and verifies agreement within 25 percent, a tolerance
fixed in advance. The measured deltas land in the experiment JSON for inspection and are never quoted
in prose, because they move with the machine.

## Alternative considered

Wall-clock measurement only, with best-of-N and published spread. Rejected: the numbers this
repository exists for are ratios between generators, and a CI runner stall in either generator's run
would move a published ratio without saying anything about the code. The receipts mechanism would
then fail builds over runner weather, and a check that fails for reasons nobody respects gets
deleted.

## Consequence

The simulator's model is small by design and its boundary has to be stated: ADR-005 lists what a
virtual clock cannot say about a real network. E4 is the only experiment that costs real time to
run, and the only one whose raw output is machine-dependent.
