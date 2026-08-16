"""Executable backend -> SDK -> Worker surface parity ledger."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.store import InMemoryStore
from tests.worker_surface_ledger import (
    EXPECTED_ROUTE_COUNT,
    INDIRECT_WORKER_ROUTES,
    NON_UI_ROUTES,
    SDK_ONLY_METHODS,
    WORKER_ROUTES,
)


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdks" / "web" / "src" / "client.ts"
WORKER = ROOT / "apps" / "worker" / "src"


def _http_routes() -> set[tuple[str, str]]:
    app = create_app(Kernel(InMemoryStore()))
    observed = [
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/v1") or route.path in {"/healthz", "/readyz"}
        for method in route.methods - {"HEAD", "OPTIONS"}
    ]
    assert len(observed) == EXPECTED_ROUTE_COUNT
    return set(observed)


def _public_sdk_methods(source: str) -> set[str]:
    methods = set(re.findall(r"^  (?:async )?([a-z][A-Za-z0-9_]*)\(", source, re.MULTILINE))
    methods.discard("constructor")
    return methods


@pytest.mark.invariant("SEC-WRK-22")
def test_every_http_route_has_an_exact_worker_or_non_ui_classification():
    declared = set(WORKER_ROUTES) | set(INDIRECT_WORKER_ROUTES) | set(NON_UI_ROUTES)
    assert len(declared) == EXPECTED_ROUTE_COUNT
    assert not (set(WORKER_ROUTES) & set(INDIRECT_WORKER_ROUTES))
    assert not (set(WORKER_ROUTES) & set(NON_UI_ROUTES))
    assert not (set(INDIRECT_WORKER_ROUTES) & set(NON_UI_ROUTES))
    assert _http_routes() == declared

    assert set(NON_UI_ROUTES.values()) == {
        "advanced-compatibility",
        "external-ingress",
        "governed-agent-surface",
        "internal-composition",
        "legacy-superseded",
        "operator-only",
        "service-native",
        "service-probe",
    }


@pytest.mark.invariant("SEC-WRK-22")
@pytest.mark.invariant("SEC-WRK-30")
def test_every_worker_route_names_a_real_sdk_contract_and_component_callsite():
    sdk_source = SDK.read_text(encoding="utf-8")
    sdk_methods = _public_sdk_methods(sdk_source)

    for route, surface in WORKER_ROUTES.items():
        source = ROOT / surface.source
        assert surface.sdk_method in sdk_methods, f"{route}: missing SDK method"
        assert source.is_file(), f"{route}: missing Worker source {surface.source}"
        assert f"client.{surface.sdk_method}" in source.read_text(encoding="utf-8"), (
            f"{route}: {surface.source} does not call client.{surface.sdk_method}"
        )

    for route, surface in INDIRECT_WORKER_ROUTES.items():
        source = ROOT / surface.source
        assert surface.sdk_method in sdk_methods, f"{route}: missing route SDK method"
        assert surface.replacement_method in sdk_methods, f"{route}: missing replacement SDK method"
        assert source.is_file(), f"{route}: missing Worker source {surface.source}"
        assert f"client.{surface.replacement_method}" in source.read_text(encoding="utf-8"), (
            f"{route}: replacement is not used by {surface.source}"
        )
        assert surface.rationale


@pytest.mark.invariant("SEC-WRK-22")
def test_every_sdk_method_is_used_by_worker_or_explicitly_classified():
    sdk_methods = _public_sdk_methods(SDK.read_text(encoding="utf-8"))
    worker_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in WORKER.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )
    called = set(re.findall(r"\bclient\.([A-Za-z][A-Za-z0-9_]*)\b", worker_source))
    sdk_only = sdk_methods - called

    assert sdk_only == set(SDK_ONLY_METHODS)
    for method, (classification, rationale) in SDK_ONLY_METHODS.items():
        assert method in sdk_methods
        assert classification in {
            "advanced-compatibility",
            "compatibility-helper",
            "internal-helper",
            "service-probe",
            "superseded-read",
            "unsupported-contract",
        }
        assert rationale
