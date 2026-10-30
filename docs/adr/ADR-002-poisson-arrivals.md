# ADR-002: Open-loop arrivals are a seeded Poisson process, not a metronome

Status: accepted

## Context

The open-loop generator needs an arrival schedule that exists before the run starts and owes
nothing to the server. The two candidates were constant-rate ticks (one request every 1/rate
seconds) and a seeded Poisson process (exponential gaps at the same mean rate).

## Decision

Poisson, seeded from the workload spec so the schedule is replayable.

Independent clients arriving at a service are the textbook Poisson situation, and the difference is
not cosmetic: a metronome never sends two requests close together, so it understates queueing at
any utilisation, and a queue is exactly what the open loop exists to observe. With exponential gaps
the sweep in E3 shows the knee where queueing takes off; with constant ticks the same sweep stays
flat until the server is literally past capacity, which would flatter the closed-loop generator and
undersell the finding.

## Alternative considered

Constant-rate ticks. Kept available in spirit through `service_sigma = 0` for the service side, but
not for arrivals: a deterministic arrival schedule makes the null experiment E1 trivially perfect
and the divergence knee in E3 artificially sharp, both of which would look better and mean less.

## Consequence

Counts in the documents are exact but scenario-shaped: the number of arrivals in a window follows
the seed, so the published omission figure belongs to this seed and this schedule. The seed is in
the spec, the spec is in the experiment file, and one command reproduces the number.
