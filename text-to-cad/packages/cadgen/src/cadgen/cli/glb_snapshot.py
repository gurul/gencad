"""``cadgen glb snapshot`` — render a GLB mesh.

A GENERATED CLI over :func:`cadgen.glb.snapshot`. There is no parser here on
purpose: everything the command accepts is derived from the verb function's
signature by :mod:`cadgen._internal.cli_from_function`, so a flag cannot drift
from a parameter (README law 6). Which input kinds the door accepts
is declared once, beside the verb, in
:data:`cadgen._internal.snapshot_door.DOOR_KINDS`.

The mesh half of ``cadgen step snapshot``, re-homed: GLB is a format with a
door (``cadgen glb build``), so its snapshot belongs behind the same door. Its
verb is the MESH shape: no kinematics or selection flags.
``--display`` takes ``solid`` or ``parts`` (``--grid`` and ``--preview`` beside it);
``display.clip`` cuts it (``at`` in metres) and ``display.exploded`` moves a GLB of
several parts apart. What describes a CAD model (the edge-made modes, Shaded) is
refused by name rather than ignored.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cadgen._internal.cli_from_function import generated_main, generated_parser

DEFAULT_PROG = "cadgen glb snapshot"
VERB = ("cadgen.glb", "snapshot")


def build_parser(prog: str = DEFAULT_PROG) -> argparse.ArgumentParser:
    return generated_parser(VERB, prog=prog)


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    return generated_main(VERB, argv, prog=prog)


if __name__ == "__main__":
    raise SystemExit(main())
