# Defense guide: openloop

How to talk about this repository in an interview. Every number here is re-measured by CI and held
to this document by `tools/check_numbers.py`, so what you say out loud is what the code produces.

## The 30 second version

"Load tests lie in a specific, structural way. A closed-loop generator waits for each response
before sending the next request, so when the server stalls, the generator stops sending, and the
requests a real client population would have issued during the stall are never sent and never
measured. I built a tool that replays one seeded workload through a closed-loop and an open-loop
generator against the same server and publishes the gap: on a server pausing 500 ms every 10
seconds, the closed loop understates p99 by 23.8x and silently drops 562 intended requests."

Then stop.

The question that usually comes next is "so is open loop just better?", and the answer is the
second finding: no generator beats arithmetic. A quantile only reports a disturbance whose sample
share exceeds 100 minus q percent, and for a single stall in a long window even the open loop's
p99 goes quiet (the ratio collapses to 1.17) while p99.9 still testifies at 20.3x at p99.9.

## The claims, each with how it is proved

**Claim: the closed loop understates a recurring 500 ms pause by 23.8x at p99.**
Prove it: `python -m openloop.cli compare --seed 7 --duration-s 60 --rate-rps 200 --workers 8
--server-capacity 16 --stall-start-s 5 --stall-duration-s 0.5 --stall-period-s 10`. Open loop p99
of 433.9 ms; closed loop reports 18.3 ms; 562 fewer requests sent than the schedule intended, 4.7
percent of its own schedule. If pushed on "that is one scenario": the scenario is seeded and
replayable, the figures live in `docs/experiments/e2_stall.json`, and E3 shows the same mechanism
with no stall at all.

**Claim: which quantile can see a stall is arithmetic, and the tool publishes it.**
Prove it: the same E2 JSON carries the stall's sample share per generator: 3.16 percent of the
open-loop samples against 0.42 percent of the closed-loop samples, either side of the 1 percent a
p99 ignores. If pushed: the single-stall variant in the same file shows the open loop's own p99
going blind at 0.54 percent in the single-stall run, which is why the tool reports shares, not
just percentiles.

**Claim: a healthy closed-loop test starts lying before the server is saturated.**
Prove it: `python experiments/e3_sweep.py`. Against a 400 rps server the generators diverge above
360 rps, and the ratio reaches 3.22 at the top of the sweep. If pushed on the 1.5 divergence
definition: it is a published constant in the experiment, argue with the constant, the data is in
the JSON either way.

**Claim: every published figure is machine-checked.**
Prove it: break one. Edit any figure in the README, run `python tools/check_numbers.py`, watch the
build fail naming the anchor and both values. If pushed on "could the checker be vacuous": it
matches anchor phrases with the number substituted, reports every number no metric re-measures,
and the deliberate-break is part of this guide precisely so the failure has been seen.

**Claim: the simulator's numbers survive contact with a real event loop.**
Prove it: `python experiments/e4_sim_vs_wall.py` replays a stalled workload on the real clock
against the bundled in-process ASGI target and verifies agreement within 25 percent on the shapes
that matter. If pushed on why not publish the wall numbers: they are facts about the machine;
ADR-001 is the argument in full.

## Questions that are meant to be hard

**Isn't this just a wrapper around a benchmark library?**
There is no benchmark library in it. The simulator is stdlib (heapq, random, dataclasses), the
histogram is in-repo with a tested 0.995 percent worst-case error bound, and the drivers are plain
asyncio because the generator's own waiting behaviour is the thing under study (ADR-003). The one
framework present, FastAPI, is the optional demo target, not the measurement.

**The workload is synthetic. Does any of this transfer?**
The mechanism transfers; the absolute numbers do not, and the repository says so in its own
boundary section. Coordinated omission is a property of the generator's control loop, not of the
network, so the ratios and counts are the real finding. What does not transfer is priced in
ADR-005: no kernel, no NIC, one process of load, one stall shape.

**What is the weakest part?**
The server model. Capacity, FIFO, and a start-blocking stall is enough to produce the phenomenon,
but a real incident severs connections, drops in-flight work, or degrades gradually, and this
models none of those shapes. Second weakest: the wall-clock witness validates shape within a
deliberately loose 25 percent, because the runtime's constant per-request cost is visible rather
than modelled; E4's first run failed over exactly that, and the ADR records it instead of a
narrower tolerance I could not defend.

**Why should I believe the 23.8x rather than suspect a tuned scenario?**
Because the repository publishes the scenario where the headline collapses. The single-stall
variant is in the same experiment with the ratio collapses to 1.17 result, the quantile arithmetic
that explains both is a section of the README, and E1's null result shows the generators with a
measured median delta of 0.0 percent when nothing is wrong.

**What did you get wrong while building it?**
Three things on the record. The first E2 used a single stall and the headline evaporated, which
became the quantile-visibility finding instead of a quietly retuned demo. The periodic-stall
boundary hung the whole suite through a float modulo one-ulp loop, fixed with index arithmetic and
pinned by a boundary test across two hundred periods. And tuple seeds for random.Random crashed on
the first smoke run, which is why seed derivation has its own test on every Python in the matrix.

**Why a virtual clock? Real systems run on real clocks.**
Because the deliverable is reproducible numbers, and wall-clock tails are facts about the runner.
The real clock is present as a witness: E4 replays the same spec on both and bounds the gap. The
alternative, publishing best-of-N wall numbers, makes the receipts checker fail over runner
weather, and a check that fails for unrespected reasons gets deleted (ADR-001).

**What would you do differently with more time?**
Model the correction, not just the defect: record closed-loop latency from intended time the way
HdrHistogram's correction mode does, and show where the correction itself breaks. And derive
per-quantile confidence from sample counts so the visibility arithmetic becomes an API instead of
a README section.

## Things to say, things not to say

Say:
- "Omission is structural: the generator cannot send while it waits, so the sample is censored."
- "A quantile sees a disturbance only if its sample share exceeds 100 minus q percent."
- "Every figure is a ratio or a count because absolute latency belongs to the machine."
- "Exit code 3 means the tool worked and the answer is no."

Do not say:
- "Closed-loop tools are broken." They answer a different question: latency under self-limited
  load. The failure is quoting them as client experience.
- "The open loop is accurate." Say "the open loop preserves the intended schedule"; its absolute
  numbers still come from a model with a stated boundary.
- "p99 covers it." Not without the share arithmetic; this repository's own single-stall run is the
  counterexample.
- Any wall-clock millisecond as a finding. Point at ratios, counts, and the E4 tolerance instead.

## The live demo script

```bash
# 1. The calm baseline: generators agree, exit 0
python -m openloop.cli compare --seed 7 --duration-s 20 --rate-rps 200 --workers 8 --server-capacity 16

# 2. The headline: recurring pauses, exit 3, understated 23.8x
python -m openloop.cli compare --seed 7 --duration-s 60 --rate-rps 200 --workers 8 \
    --server-capacity 16 --stall-start-s 5 --stall-duration-s 0.5 --stall-period-s 10

# 3. The omission itemised as JSON
python -m openloop.cli run --generator closed --json --seed 7 --duration-s 60 --rate-rps 200 \
    --workers 8 --server-capacity 16 --stall-start-s 5 --stall-duration-s 0.5 --stall-period-s 10

# 4. Re-measure everything from scratch
make experiments

# 5. Hold this very document to the code
python tools/check_numbers.py
```
