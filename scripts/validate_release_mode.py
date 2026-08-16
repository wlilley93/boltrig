"""Validate the protected release mode without guessing operator intent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Same reason as scripts/validate_release_compose.py, and the same latent bug:
# release.yml runs `python3 scripts/validate_release_mode.py` on a bare runner
# with no install, so this import would have raised ModuleNotFoundError at the
# FIRST gate of a release. It has not fired yet only because that workflow runs
# on release events and the compose job found the shared defect first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boltrig.release_mode import (  # noqa: E402
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
