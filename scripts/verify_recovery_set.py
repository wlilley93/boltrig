"""Read-only verification for a complete Boltrig recovery-set marker."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


_MARKER = re.compile(r"^boltrig-(\d{8}T\d{6}Z)\.recovery\.sha256$")
_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)$")
_DATABASE = re.compile(r"^[A-Za-z0-9_-]+$")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _validate_databases(names: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not names
        or any(not _DATABASE.fullmatch(name) for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("required databases must be a non-empty unique list of safe names")
    return names


def _databases(value: str) -> tuple[str, ...]:
    return _validate_databases(tuple(value.split(",")))


def _artifact_database(name: str, timestamp: str) -> tuple[str, bool] | None:
    primary = re.fullmatch(rf"boltrig-{re.escape(timestamp)}\.dump(\.enc)?", name)
    if primary:
        return "boltrig", bool(primary.group(1))
    named = re.fullmatch(
        rf"boltrig-([A-Za-z0-9_-]+)-{re.escape(timestamp)}\.dump(\.enc)?",
        name,
    )
    if named:
        return named.group(1), bool(named.group(2))
    return None


def verify_recovery_set(
    marker: Path,
    *,
    required_databases: tuple[str, ...] = ("boltrig", "hatchet"),
) -> tuple[str, ...]:
    """Verify one complete set without decrypting, restoring, or changing files."""
    required_databases = _validate_databases(required_databases)
    match = _MARKER.fullmatch(marker.name)
    if not match:
        raise ValueError("recovery marker must be named boltrig-<UTC>.recovery.sha256")
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("recovery marker must be a regular file, not a symlink")
    timestamp = match.group(1)
    base = marker.parent
    lines = marker.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("recovery marker is empty")

    seen_names: set[str] = set()
    found_databases: set[str] = set()
    found_state = False
    for number, line in enumerate(lines, 1):
        parsed = _LINE.fullmatch(line)
        if not parsed:
            raise ValueError(f"recovery marker line {number} is malformed")
        expected_digest, name = parsed.groups()
        if name in seen_names:
            raise ValueError(f"recovery marker repeats artifact {name}")
        seen_names.add(name)

        database = _artifact_database(name, timestamp)
        state_name = f"boltrig-state-{timestamp}.tar.gz.enc"
        if database is not None:
            database_name, encrypted = database
            if not encrypted:
                raise ValueError(f"database artifact {name} is not encrypted")
            if database_name in found_databases:
                raise ValueError(f"recovery set repeats logical database {database_name}")
            found_databases.add(database_name)
        elif name == state_name:
            encrypted = True
            found_state = True
        else:
            raise ValueError(f"artifact {name} is not part of recovery timestamp {timestamp}")

        artifact = base / name
        sidecar = base / f"{name}.sha256"
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError(f"artifact {name} is missing or is a symlink")
        if sidecar.is_symlink() or not sidecar.is_file():
            raise ValueError(f"checksum sidecar for {name} is missing or is a symlink")
        if artifact.stat().st_size == 0:
            raise ValueError(f"artifact {name} is empty")
        if _digest(artifact) != expected_digest:
            raise ValueError(f"artifact {name} does not match the recovery marker")
        if sidecar.read_text(encoding="utf-8").rstrip("\n") != (f"{expected_digest}  {name}"):
            raise ValueError(f"checksum sidecar for {name} is inconsistent")
        if encrypted:
            with artifact.open("rb") as handle:
                if handle.read(8) != b"Salted__":
                    raise ValueError(f"encrypted artifact {name} has no OpenSSL salt header")

    missing = sorted(set(required_databases) - found_databases)
    if missing:
        raise ValueError(f"recovery set omits required database(s): {', '.join(missing)}")
    unexpected = sorted(found_databases - set(required_databases))
    if unexpected:
        raise ValueError(f"recovery set contains unexpected database(s): {', '.join(unexpected)}")
    if not found_state:
        raise ValueError("recovery set omits encrypted stack file state")
    return tuple(sorted(seen_names))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("marker", type=Path)
    parser.add_argument("--required-databases", default="boltrig,hatchet")
    args = parser.parse_args()
    try:
        required = _databases(args.required_databases)
        artifacts = verify_recovery_set(
            args.marker,
            required_databases=required,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"recovery set verified read-only: {args.marker} ({len(artifacts)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
