"""Offline audit contracts: never mistake an Austrian OSRM graph for DE."""

from scripts.audit_germany_routing_host import RoutingHostSnapshot, assess_readiness


def snapshot(**overrides):
    values = {
        "country": "DE",
        "service": "wohnwerk",
        "health_version": "0.4.33",
        "routing_mode": "de_graph_declared",
        "osrm_graph_path": "/var/lib/osrm/germany-latest.osrm",
        "germany_graph_files": {
            "base": True, "partition": True, "cells": True
        },
        "osrm_commands_installed": {
            "osrm-extract": False,
            "osrm-partition": False,
            "osrm-customize": False,
            "osrm-routed": True,
        },
        "available_memory_mib": 2800,
        "free_disk_gib": 16.3,
    }
    values.update(overrides)
    return RoutingHostSnapshot(**values)


def test_independently_staged_graph_needs_no_installed_builder_tools() -> None:
    # Live traffic still separately requires physical Germany route probes.
    assert assess_readiness(snapshot()) == []


def test_austria_production_is_visibly_blocked_and_cannot_claim_de() -> None:
    blocked = assess_readiness(snapshot(
        country="AT",
        routing_mode=None,
        osrm_graph_path="/var/lib/osrm/austria-latest.osrm",
        germany_graph_files={"base": False, "partition": False, "cells": False},
    ))
    assert "active_application_country_not_DE" in blocked
    assert "osrm_service_uses_non_german_graph" in blocked
    assert "germany_mld_graph_artifacts_missing" in blocked
    assert "de_routing_not_declared_after_acceptance" in blocked


def test_incomplete_mld_dataset_is_not_ready() -> None:
    blockers = assess_readiness(snapshot(germany_graph_files={
        "base": True, "partition": True, "cells": False
    }))
    assert blockers == ["germany_mld_graph_artifacts_missing"]


def test_health_unavailable_is_not_ready() -> None:
    blockers = assess_readiness(snapshot(
        country=None, service=None, health_version=None, routing_mode=None
    ))
    assert "wohnwerk_health_unavailable" in blockers
    assert "active_application_country_not_DE" in blockers
