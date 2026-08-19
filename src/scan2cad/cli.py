"""Placeholder command-line entry point (real CLI lands in WI-8)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Print a plain-language not-built-yet message and return exit code 2."""
    del argv
    print("scan2cad: the command line interface is not built yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
