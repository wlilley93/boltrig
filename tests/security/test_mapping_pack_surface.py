"""A mapping pack may only name an operation the provider actually publishes.

``apply_mapping_pack`` skips an id the door does not expose, which is right for
staleness and is what stops a pack minting a binding onto an operation that is
not there. The cost is that an upstream RENAME unmaps a capability in silence:
no error, no log, the canonical verb simply stops being offered and the raw one
comes back. Nobody would notice until an agent stopped being able to do
something it did yesterday.

This is the check that turns that silence into a failure, against the vendored
surface in ``tests/fixtures/opbox-verb-surface.txt``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.capabilities.mapping_packs import load_packs

ROOT = Path(__file__).resolve().parents[2]
SURFACES = {"opbox": ROOT / "tests" / "fixtures" / "opbox-verb-surface.txt"}


def _surface(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


@pytest.mark.security
def test_every_shipped_mapping_names_an_operation_the_provider_publishes():
    for provider, pack in load_packs().items():
        surface_path = SURFACES.get(provider)
        if surface_path is None:
            # A pack for a provider with no vendored surface is not silently
            # exempt; it is a gap in THIS gate, and saying so is the point.
            pytest.fail(
                f"pack {pack.name!r} maps provider {provider!r} with no vendored "
                f"verb surface, so nothing checks its operation ids exist"
            )
        surface = _surface(surface_path)
        missing = sorted({m.operation_id for m in pack.mappings} - surface)
        assert not missing, (
            f"pack {pack.name!r} names operations {provider} does not publish: "
            f"{missing}. Either the door renamed them (and the capability is "
            f"now silently unmapped) or the pack was written from a guess."
        )


@pytest.mark.security
def test_the_vendored_surface_is_not_empty_or_the_check_above_is_vacuous():
    """An empty surface would make every mapping look missing, not present.

    Stated the safe way round: this pins that the fixture actually carries a
    provider surface, so a truncated file fails here rather than turning the
    check above into an assertion about nothing.
    """
    for provider, path in SURFACES.items():
        surface = _surface(path)
        assert len(surface) > 100, f"{provider} surface looks truncated: {len(surface)}"
        assert all(name.startswith(f"{provider}.") for name in surface)
