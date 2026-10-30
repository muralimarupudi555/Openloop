# ADR-003: Plain asyncio and httpx, not a load-testing framework

Status: accepted

## Context

Locust, k6 and friends exist, are mature, and would have produced a working load generator in an
afternoon. Reaching for one here would have been the boring choice, and the boring choice is usually
right.

## Decision

Not this time, and the reason is the subject of the repository: the generator's own waiting
behaviour is the thing under measurement. A framework hides its event loop, its pacing strategy and
its omission behaviour behind configuration, which is precisely the information this tool exists to
surface. Measuring coordinated omission through a framework means reporting on that framework's
internals, and any fix or finding stops being transferable.

So the drivers are plain asyncio: the closed-loop worker is a visible while-loop whose slot-skipping
is nine lines a reviewer can audit, and the open-loop driver is one task per intended arrival. httpx
with its ASGI transport connects the wall-clock driver to the bundled target in-process, keeping the
runtime free of sockets, ports and network permissions.

## The boring choice that was made

FastAPI for the bundled target. Nothing about the target needs FastAPI; a raw ASGI callable would
do. FastAPI was chosen because it is the mainstream way such a service is written, its parameter
validation gives the target a real refusal path worth testing, and a reviewer recognises the shape
in ten seconds. Boring, recognisable, and isolated behind an optional extra so the core installs
with zero dependencies.

## Consequence

The wall-clock driver is capped by one event loop's throughput. That cap is a real property of
single-process generators and is acknowledged in the Pivot section of the README rather than worked
around.
