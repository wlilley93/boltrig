"""Validate the digest-pinned image environment emitted by a Boltrig release."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REQUIRED_IMAGE_VARIABLES = (
    "BOLTRIG_KERNEL_IMAGE",
    "BOLTRIG_FLEET_IMAGE",
    "BOLTRIG_UI_IMAGE",
    "BOLTRIG_PI_SIDECAR_IMAGE",
    "BOLTRIG_BACKUP_IMAGE",
)

_DIGEST_IMAGE = re.compile(r"^[^\s@=]+@sha256:[0-9a-f]{64}$")


def _read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key.strip() != key or value.strip() != value:
            raise ValueError(f"{path}:{line_number}: expected KEY=value")
        if key in values:
            raise ValueError(f"{path}:{line_number}: duplicate variable {key}")
        values[key] = value
    return values


def validate_release_image_environment(path: Path) -> dict[str, str]:
    """Return a complete release environment or raise on mutable/extra input."""
    if not path.is_file():
        raise ValueError(f"release image environment does not exist: {path}")
    values = _read_environment(path)
    required = set(REQUIRED_IMAGE_VARIABLES)
    missing = sorted(required - values.keys())
    unexpected = sorted(values.keys() - required)
    if missing:
        raise ValueError(f"missing release image variables: {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"unexpected release image variables: {', '.join(unexpected)}")
    mutable = sorted(key for key, value in values.items() if not _DIGEST_IMAGE.fullmatch(value))
    if mutable:
        raise ValueError(
            "release images must be immutable image@sha256 references: "
            + ", ".join(mutable)
        )
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        validate_release_image_environment(args.env_file)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"release image environment valid: {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
