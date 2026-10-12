"""``python -m cadgen.cli`` — the same dispatcher the ``cadgen`` console script runs."""

from __future__ import annotations

import sys

from cadgen.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
