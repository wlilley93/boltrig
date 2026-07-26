"""The catalogue that carries every other claim has to carry its own.

tests/invariants.yaml is the file that decides whether a boltrig guarantee is
bound to a test. Nothing ever checked the catalogue itself:

  * it is named ``.yaml`` and did not parse as YAML - 321 descriptions were
    plain scalars carrying colons and hashes, and five were folded block
    scalars that the gate's stdlib reader silently truncated to the literal
    ``>-``;
  * SEC-169 was declared TWICE (2026-07-17, the RLS tenant-table fence-drift
    guard; 2026-07-22, credential-at-rest sealing). Both the stdlib reader and
    PyYAML resolve a repeated key last-wins, so the RLS declaration was evicted
    from the catalogue, from the gate's coverage table and from
    docs/invariants.md, and every check stayed green for four months.

So this file binds three properties of the catalogue: it parses with a real
YAML parser, the gate's stdlib reader agrees with that parser exactly, and a
repeated invariant id is refused rather than eaten.

The gate itself stays stdlib-only on purpose (it must run before any install),
which is precisely why the agreement is asserted here, where PyYAML is
available, instead of by swapping the reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import check_invariants

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = REPO_ROOT / "tests" / "invariants.yaml"


class _DuplicateRefusingLoader(yaml.SafeLoader):
    """PyYAML accepts a repeated mapping key and keeps the last. This does not."""


def _no_duplicate_keys(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_DuplicateRefusingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


@pytest.mark.invariant("NFR-MNT-02")
def test_the_invariant_catalogue_is_the_yaml_its_name_claims() -> None:
    """A file named .yaml that no parser has ever read is an unbacked claim."""
    document = yaml.load(CATALOGUE.read_text(encoding="utf-8"), _DuplicateRefusingLoader)

    assert isinstance(document, dict), "the catalogue must be a mapping"
    assert set(document) == {"invariants"}, "the catalogue has exactly one top-level key"
    invariants = document["invariants"]
    assert invariants, "the catalogue is not empty"

    for inv_id, entry in invariants.items():
        assert isinstance(entry, dict), f"{inv_id}: entry must be a mapping"
        assert set(entry) <= {"description", "tests", "service_gated"}, (
            f"{inv_id}: unknown key - the stdlib reader would drop it silently"
        )
        assert isinstance(entry.get("description"), str) and entry["description"].strip(), (
            f"{inv_id}: needs a one-line description"
        )
        assert isinstance(entry.get("tests"), list) and entry["tests"], (
            f"{inv_id}: needs at least one bound test"
        )


@pytest.mark.invariant("NFR-MNT-02")
def test_the_gates_stdlib_reader_agrees_with_a_real_yaml_parser() -> None:
    """The gate reads the catalogue by hand. Its answer must be YAML's answer.

    Without this the reader can drift from the file (it did: a folded scalar
    read back as the two characters ``>-``) and the gate keeps reporting PASS
    against a document nobody wrote.
    """
    parsed = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["invariants"]
    read = check_invariants.load_catalogue(CATALOGUE)

    assert set(read) == set(parsed), "the reader and YAML disagree on which ids exist"

    for inv_id, entry in parsed.items():
        assert read[inv_id]["description"] == entry["description"], (
            f"{inv_id}: the reader's description is not the file's"
        )
        assert read[inv_id]["tests"] == list(entry["tests"]), (
            f"{inv_id}: the reader's bound tests are not the file's"
        )
        assert read[inv_id]["service_gated"] == list(entry.get("service_gated") or []), (
            f"{inv_id}: the reader's service_gated set is not the file's"
        )


@pytest.mark.invariant("NFR-MNT-02")
def test_a_repeated_invariant_id_is_refused_rather_than_eaten(tmp_path: Path) -> None:
    """The seeded failure: exactly the shape that hid SEC-169 for four months."""
    catalogue = tmp_path / "invariants.yaml"
    catalogue.write_text(
        "invariants:\n"
        "  SEC-1:\n"
        "    description: 'the first claim'\n"
        "    tests:\n"
        "      - tests/security/test_a.py::test_one\n"
        "  SEC-1:\n"
        "    description: 'a different claim wearing the same id'\n"
        "    tests:\n"
        "      - tests/security/test_b.py::test_two\n",
        encoding="utf-8",
    )

    with pytest.raises(check_invariants.CatalogueError) as raised:
        check_invariants.load_catalogue(catalogue)

    assert "SEC-1" in str(raised.value)
