"""`boltrig config-validate` (task #59): config gets a pre-flight, like schema has.

The 0040->0066 prod roll had an exhaustive DATABASE pre-flight and still
crash-looped - on a manifest field (`spawn_rules[0] is missing required fields:
priority`). A migration has a version chain, a head, and a parity gate; a
manifest had nothing. This command is the nothing's replacement: parse the
target's manifest with the SHIPPING loader and exit non-zero on rejection, so a
crash loop becomes a pre-flight failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.api.config_validate import main

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


def _cli(argv: list[str]) -> int:
    import sys

    from boltrig.api.cli import main as cli_main

    old = sys.argv
    sys.argv = ["boltrig", *argv]
    try:
        return cli_main()
    finally:
        sys.argv = old


def test_the_shipped_example_parses_with_the_shipping_loader() -> None:
    """The standing parity check: the example every deployment starts from must
    parse with the code that ships beside it. Runs in `make check`, so a commit
    that adds a required manifest field without a default goes red HERE, before
    any box crash-loops on it."""
    assert main(str(REPO / "manifest.example.yaml")) == 0


def test_the_exact_prod_crash_is_a_preflight_failure_now(tmp_path: Path) -> None:
    """The 2026-07-31 crash loop, replayed as an exit code.

    A spawn rule missing `priority` is what took prod down after a flawless
    database pre-flight. The command must refuse it, name the reason, and exit 1
    - not 2 (2 is operator error: no such file), because a deploy script treats
    those differently.
    """
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        (REPO / "manifest.example.yaml")
        .read_text(encoding="utf-8")
        .replace("    priority: ", "    _priority_removed: ", 1),
        encoding="utf-8",
    )
    assert main(str(manifest)) == 1


def test_a_missing_file_is_operator_error_not_a_rejection(tmp_path: Path) -> None:
    assert main(str(tmp_path / "absent.yaml")) == 2
    assert main("  ") == 2


def test_the_cli_subcommand_reaches_the_validator() -> None:
    """The wiring, not just the function: `boltrig config-validate <path>` is
    what the deploy recipe calls, so the subcommand must resolve."""
    assert _cli(["config-validate", str(REPO / "manifest.example.yaml")]) == 0
