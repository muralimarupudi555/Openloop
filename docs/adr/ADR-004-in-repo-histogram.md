# ADR-004: A ninety-line log-bucket histogram instead of the HdrHistogram dependency

Status: accepted

## Context

Percentiles are the product of this tool, so the recording structure is load-bearing. HdrHistogram
is the standard answer and its Python binding would have worked.

## Decision

An in-repo histogram with geometric buckets, for three reasons that are specific to this project.

First, the error bound has to be a published, tested claim rather than an imported reputation. A
value lands in a bucket spanning lo to lo times growth and is reported as the geometric midpoint, so
the worst-case relative error is the square root of the growth factor minus one: 0.995 percent
worst-case at the default growth of 1.02. A test holds the implementation to that bound across
random samples, which is a stronger statement than a dependency's README can make on this
repository's behalf.

Second, determinism across the CI matrix is what the receipts mechanism stands on, and a pure-Python
structure with no C extension removes a whole category of platform variance and build failure from
the one component every number flows through.

Third, the structure is small enough to audit in one sitting, and a reviewer who distrusts the
headline should be able to read the thing that produced it.

## Alternative considered

HdrHistogram via its Python package. Rejected for the reasons above, with the honest caveat that it
is faster and more featureful; neither matters at the sample counts the experiments produce.

## Consequence

Reported percentiles are bucket midpoints, so two nearby quantiles can return the same value and a
published figure carries up to the stated bound of quantisation. The E1 agreement deltas are
reported against exactly this resolution rather than pretended to be exact.
