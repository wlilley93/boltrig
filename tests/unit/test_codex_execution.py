"""The Codex ledger scaffold (steps 1-2): a proven no-op behind the flag.

These bind the flag-off no-op property and the flag-on construct-but-call-nothing
property. Nothing here calls ``RootRoutingAdmission.admit`` or
``AssignmentAdmission.admit``; there is no admit call to make in this scaffold.
"""

from __future__ import annotations

import pytest

from boltrig.api.codex_execution import CodexExecutionStack, build_codex_execution_stack
from boltrig.config.settings import Settings, load_settings
from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.store import InMemoryStore


def test_codex_ledger_defaults_off() -> None:
    """The flag is off unless explicitly set (frozen default + env parse)."""
    assert Settings().codex_ledger is False
    assert load_settings({}).codex_ledger is False


def test_load_settings_parses_the_codex_ledger_flag() -> None:
    assert load_settings({"BOLTRIG_CODEX_LEDGER": "1"}).codex_ledger is True
    assert load_settings({"BOLTRIG_CODEX_LEDGER": "true"}).codex_ledger is True
    assert load_settings({"BOLTRIG_CODEX_LEDGER": "0"}).codex_ledger is False
    assert load_settings({"BOLTRIG_CODEX_LEDGER": ""}).codex_ledger is False


@pytest.mark.invariant("SEC-170")
def test_codex_ledger_defaults_off_and_builds_no_stack() -> None:
    """Flag off (the default) constructs nothing: a total no-op, even with a store."""
    settings = Settings(codex_ledger=False)
    assert build_codex_execution_stack(settings, InMemoryStore()) is None
    # And the same holds through the default settings, not just an explicit False.
    assert build_codex_execution_stack(Settings(), InMemoryStore()) is None


@pytest.mark.invariant("SEC-170")
def test_flag_on_constructs_both_admission_services() -> None:
    """Flag on with an in-memory store: both admission services are constructed,
    without error, and STILL nothing calls admit (there is no admit call to make;
    we assert only that the services exist and are the right types)."""
    settings = Settings(codex_ledger=True)
    stack = build_codex_execution_stack(settings, InMemoryStore())
    assert isinstance(stack, CodexExecutionStack)
    assert isinstance(stack.root_admission, RootRoutingAdmission)
    assert isinstance(stack.assignment_admission, AssignmentAdmission)
