"""The noise sweep's truth matcher compares like with like.

scripts/sweep_noise.py decides whether a required true dimension was
recovered. A length must be recovered by a plane-to-plane gap, and a bore or
boss diameter by a cylinder diameter. A spurious cylinder whose fitted length
happens to land near a true box length must not count as that box length.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sweep_noise.py"


def _load_sweep():
    spec = importlib.util.spec_from_file_location("sweep_noise", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sweep = _load_sweep()


def test_spurious_cylinder_length_does_not_recover_a_box_length():
    # bossbox: the 80 mm width gap is badly off, but a spurious cylinder's
    # fitted length lands on 80.0. That must not count as the 80 mm width.
    reported = {
        "width": 76.0,
        "depth": 50.1,
        "height": 31.0,
        "cyl_boss_1_diameter": 8.0,
        "cyl_boss_1_length": 6.0,
        "cylinder_2_length": 80.0,
    }
    errors, problems = sweep.match_required(reported, "bossbox", 0.5)
    assert errors[80.0] is None
    assert "the 80.0 mm dimension was not recovered" in problems
    assert errors[50.0] is not None and abs(errors[50.0] - 0.1) < 1e-9
    assert errors[8.0] == 0.0


def test_diameter_is_matched_only_by_a_cylinder_diameter():
    # bossbox: nothing reports an 8 mm diameter; an 8 mm gap must not stand in.
    reported = {
        "width": 80.0,
        "depth": 50.0,
        "height_2": 8.0,
        "cyl_boss_1_diameter": 12.0,
    }
    errors, problems = sweep.match_required(reported, "bossbox", 0.5)
    assert errors[8.0] is None
    assert "the 8.0 mm dimension was not recovered" in problems
    assert errors[80.0] == 0.0 and errors[50.0] == 0.0


def test_suffixed_gap_names_count_as_lengths():
    reported = {"width_2": 80.2, "depth": 50.0, "cyl_boss_1_diameter": 8.0}
    errors, problems = sweep.match_required(reported, "bossbox", 0.5)
    assert problems == []
    assert abs(errors[80.0] - 0.2) < 1e-9


def test_every_required_dimension_has_a_kind():
    for model, required in sweep.REQUIRED_MM.items():
        assert set(required) == set(sweep.REQUIRED_KIND[model])
        assert set(sweep.REQUIRED_KIND[model].values()) <= {"length", "diameter"}
