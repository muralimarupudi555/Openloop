"""Shared fixtures: small, fast specs that still exercise every rule."""

import pytest

from openloop.workload import WorkloadSpec


@pytest.fixture
def quiet_spec() -> WorkloadSpec:
    """Low utilisation, no stall: both generators should agree here."""
    return WorkloadSpec(
        seed=11,
        duration_s=8.0,
        rate_rps=100.0,
        workers=4,
        service_mean_s=0.008,
        server_capacity=16,
    )


@pytest.fixture
def stall_spec() -> WorkloadSpec:
    """The scenario the tool exists for: a mid-run stall."""
    return WorkloadSpec(
        seed=11,
        duration_s=8.0,
        rate_rps=100.0,
        workers=4,
        service_mean_s=0.008,
        server_capacity=16,
        stall_start_s=4.0,
        stall_duration_s=0.4,
    )


@pytest.fixture
def saturating_spec() -> WorkloadSpec:
    """Offered load near server capacity, so queues actually form."""
    return WorkloadSpec(
        seed=5,
        duration_s=6.0,
        rate_rps=380.0,
        workers=8,
        service_mean_s=0.020,
        server_capacity=8,
    )
