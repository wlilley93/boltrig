"""Validate the protected release mode without guessing operator intent."""

from __future__ import annotations

import argparse

from boltrig.release_mode import (
    VALID_RELEASE_MODES as VALID_RELEASE_MODES,
    validate_release_mode as validate_release_mode,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode")
    args = parser.parse_args()
    try:
        mode = validate_release_mode(args.mode)
    except ValueError as exc:
        parser.error(str(exc))
    print(mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
