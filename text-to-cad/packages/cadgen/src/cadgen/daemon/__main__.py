"""``python -m cadgen.daemon`` — run the warm build daemon."""

from __future__ import annotations

import sys

from cadgen.daemon.server import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
