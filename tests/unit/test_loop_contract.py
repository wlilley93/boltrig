"""Closed, typed and bounded flow.loop contract tests."""

from __future__ import annotations

import pytest

from boltrig.workflows.loop_contract import (
    LoopItemsError,
    bind_loop_params,
    resolve_bounded_items,
    validate_loop_contract,
)


def _issue(steps: list[dict]) -> str | None:
    issue = validate_loop_contract({"steps": steps})
    return issue.reason if issue is not None else None


def test_valid_contract_binds_whole_typed_values_without_mutation():
    item = {"title": "A", "labels": ["x"]}
    step = {
        "id": "create",
        "action": "ticket.create",
        "parents": ["loop"],
        "params": {"payload": None, "position": None, "constant": "kept"},
        "loop_bindings": {"payload": "item", "position": "index"},
    }
    assert (
        _issue(
            [
                {
                    "id": "loop",
                    "action": "flow.loop",
                    "params": {"items": [item]},
                },
                step,
            ]
        )
        is None
    )

    clone = bind_loop_params(step, item=item, index=4)

    assert clone["params"] == {
        "payload": {"title": "A", "labels": ["x"]},
        "position": 4,
        "constant": "kept",
    }
    assert step["params"]["payload"] is None
    item["labels"].append("later")
    assert clone["params"]["payload"]["labels"] == ["x"]


def test_contract_rejects_ambiguous_sources_and_non_ancestor_references():
    assert (
        _issue(
            [
                {
                    "id": "loop",
                    "action": "flow.loop",
                    "params": {"items": [], "items_from": "$seed.output.rows"},
                },
            ]
        )
        == "loop_requires_one_item_source"
    )
    assert (
        _issue(
            [
                {
                    "id": "loop",
                    "action": "flow.loop",
                    "params": {"items_from": "$later.output.rows"},
                },
                {"id": "later", "action": "job.one", "parents": ["loop"], "params": {}},
            ]
        )
        == "loop_items_from_must_reference_ancestor"
    )


def test_contract_rejects_nested_or_unscoped_bindings():
    assert (
        _issue(
            [
                {"id": "outer", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "inner",
                    "action": "flow.loop",
                    "parents": ["outer"],
                    "params": {"items": [2]},
                },
            ]
        )
        == "nested_loop_not_supported"
    )
    assert (
        _issue(
            [
                {"id": "loop", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "outside",
                    "action": "job.one",
                    "params": {"value": None},
                    "loop_bindings": {"value": "item"},
                },
            ]
        )
        == "loop_bindings_require_one_loop_body"
    )


def test_empty_legacy_binding_object_is_a_noop_outside_a_loop():
    assert (
        _issue(
            [
                {
                    "id": "ordinary",
                    "action": "job.one",
                    "params": {},
                    "loop_bindings": {},
                }
            ]
        )
        is None
    )


def test_loop_reserves_deterministic_clone_id_namespace():
    assert (
        _issue(
            [
                {"id": "loop", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "body__0",
                    "action": "job.one",
                    "parents": ["loop"],
                    "params": {},
                },
            ]
        )
        == "loop_step_id_reserved"
    )


def test_contract_rejects_unknown_sources_and_missing_targets():
    assert (
        _issue(
            [
                {"id": "loop", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "body",
                    "action": "job.one",
                    "parents": ["loop"],
                    "params": {"value": None},
                    "loop_bindings": {"value": "expression"},
                },
            ]
        )
        == "loop_binding_source_invalid"
    )
    assert (
        _issue(
            [
                {"id": "loop", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "body",
                    "action": "job.one",
                    "parents": ["loop"],
                    "params": {"value": None},
                    "loop_bindings": {"missing": "item"},
                },
            ]
        )
        == "loop_binding_target_missing"
    )


def test_resolved_items_are_capped_and_digest_is_order_sensitive():
    first = resolve_bounded_items(list(range(105)))
    same = resolve_bounded_items(list(range(105)))
    reversed_items = resolve_bounded_items(list(reversed(range(105))))

    assert len(first.items) == 100
    assert first.overflow == 5
    assert first.digest == same.digest
    assert first.digest != reversed_items.digest


def test_contract_refuses_oversized_non_json_and_excessive_bindings():
    with pytest.raises(LoopItemsError, match="loop_items_too_large"):
        resolve_bounded_items(["x" * (256 * 1024)])
    with pytest.raises(LoopItemsError, match="loop_items_not_json"):
        resolve_bounded_items([float("nan")])

    bindings = {f"value_{index}": "item" for index in range(33)}
    params = {target: None for target in bindings}
    assert (
        _issue(
            [
                {"id": "loop", "action": "flow.loop", "params": {"items": [1]}},
                {
                    "id": "body",
                    "action": "job.one",
                    "parents": ["loop"],
                    "params": params,
                    "loop_bindings": bindings,
                },
            ]
        )
        == "loop_binding_limit_exceeded"
    )
