# ADR-005: What this repository deliberately cannot measure

Status: accepted

## Context

Every number here comes from a model: a capacity-limited FIFO server with a start-blocking stall,
driven by a virtual clock, with a wall-clock twin that still runs in a single process with no
socket. Stating the boundary of that model is part of the deliverable, because the strongest claim
a measurement tool can make is knowing where its own measurements stop.

## The boundary, stated

**No kernel, no NIC, no network.** Loopback-free in-process transport means nothing here prices TCP
backpressure, kernel scheduling, head-of-line blocking in a real socket, or cross-host clock skew.
Absolute latencies from this repository are not SLO inputs. The defensible claims are the ratios
and counts between two generators replaying the same schedule, which is why every headline is a
ratio or a count.

**The runtime's constant cost is visible, not modelled.** The first run of experiment E4 failed its
own tolerance: with five-millisecond service times, the event loop and ASGI dispatch overhead was a
third of the wall-clock median, and the simulator does not model it. The experiment now uses
service times an order of magnitude above that overhead, the residual delta in the JSON is the
overhead itself, and this ADR records the choice rather than hiding it in a constant.

**One stall shape.** The stall blocks service starts and lets in-flight work finish, the shape of a
connection-pool freeze or a stop-the-world pause. A crash that drops in-flight requests, a slow
leak of capacity, or a stall that also severs connections are different shapes with different
signatures, and nothing here speaks for them.

**One process of load.** Both drivers run in a single event loop, so the maximum offered rate the
wall-clock driver can sustain is a property of that loop. The simulator has no such ceiling, which
is one more reason it is the receipts source and the wall run is the witness.

## Consequence

The README carries a section with this boundary rather than a footnote, and the defense guide's
weakest-part answer points here.
