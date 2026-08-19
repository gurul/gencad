"""Measure whether the noise-zero gate's primitive counts are actually stable.

Not a test. This is the evidence behind one assertion: `tests/test_e2e_noise0.py`
insists that the fitter returns exactly the primitives each synthetic part was
built with, and CGAL Efficient RANSAC draws from a generator this project cannot
seed (docs/STACK_NOTES.md). "Seed 1337" pins the sampler that writes the point
cloud, not the shape fitter that reads it, so an exact count assertion is a
claim about stability that has to be measured rather than assumed.

The script fits each model repeatedly from one fixed cloud and records the
distribution of (plane count, cylinder count) it saw. It writes
`out/gate_repeat.txt` and exits 1 if any repeat disagreed with the construction,
so a disagreement is visible without reading the file.

Run it after any change to `ransac_cgal.py`:

    .venv/bin/python scripts/gate_repeat.py --repeats 30
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "tools" / "make_synthetic.py"
DEFAULT_OUT = REPO_ROOT / "out" / "gate_repeat.txt"

# Pinned by PLAN.md WI-10, and repeated here rather than imported so this file
# stays runnable when the test suite is not.
GATE_SEED = 1337
GATE_POINTS = 80_000
MODELS = ("bracket", "lbracket", "bossbox")

CAPTION = (
    "PLUMBING VERIFICATION ONLY -- synthetic noise model; NOT predictive of "
    "iPhone accuracy."
)


def _load_generator():
    """Import tools/make_synthetic.py by path; tools/ is not a package."""
    spec = importlib.util.spec_from_file_location("make_synthetic", GENERATOR)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"cannot load the generator at {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _plural(count: int, noun: str) -> str:
    """Return "1 plane" or "6 planes"; the reports say it this way too."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def measure(repeats: int) -> tuple[list[str], bool]:
    """Fit every model `repeats` times and return (report lines, all matched).

    Assumes the heavy wheels are importable. One point cloud is built per model
    and reused for every repeat, so the only thing varying between repeats is
    the fitter itself.
    """
    from scan2cad.ransac_cgal import fit_primitives  # noqa: PLC0415 - heavy import
    from scan2cad.sources import FileMeshSource  # noqa: PLC0415 - heavy import
    from scan2cad.thresholds import COARSE  # noqa: PLC0415 - heavy import

    generator = _load_generator()
    lines = [
        "Repeated-fit stability evidence for the noise-zero gate.",
        "",
        CAPTION,
        "",
        "Why this file exists. CGAL Efficient RANSAC draws from a generator this",
        "project cannot seed, so two identical invocations are not guaranteed to",
        "return an identical inlier partition. The noise-zero gate nevertheless",
        "asserts an exact primitive count. This file is the measurement that says",
        "whether that assertion holds, run repeatedly on one fixed point cloud at",
        f"the pinned sampler seed {GATE_SEED} and {GATE_POINTS} points.",
        "",
        f"Repeats per model: {repeats}.",
        "",
    ]
    all_matched = True
    work = Path(tempfile.mkdtemp(prefix="scan2cad_gate_repeat_"))
    for model in MODELS:
        params = generator.SamplerParams(
            n_points=GATE_POINTS, sigma_mm=0.0, seed=GATE_SEED
        )
        points, normals, truth = generator.make_model(model, params)
        expected = (int(truth["n_planes"]), int(truth["n_cylinders"]))

        # Through the PLY and the normal estimator, not straight off the
        # generator's exact normals: the gate reads a file, and the estimated
        # normals are what the fitter actually sees. The two paths behave
        # differently, and only this one is the gate.
        ply = work / f"{model}.ply"
        generator.write_ply(ply, points, normals)
        cloud = FileMeshSource(
            str(ply),
            units="mm",
            provenance="synthetic",
            seed=GATE_SEED,
            sample_count=GATE_POINTS,
        ).load_cloud()

        seen: collections.Counter = collections.Counter()
        started = time.time()
        for _ in range(repeats):
            result = fit_primitives(cloud.points, cloud.normals, thresholds=COARSE)
            seen[(len(result.planes), len(result.cylinders))] += 1
        elapsed = time.time() - started

        lines.append(f"Model {model}.")
        lines.append(
            "Construction truth: "
            f"{_plural(expected[0], 'plane')} and {_plural(expected[1], 'cylinder')}."
        )
        for pair, count in sorted(seen.items()):
            verdict = "matches" if pair == expected else "DOES NOT MATCH"
            lines.append(
                f"Observed {_plural(pair[0], 'plane')} and "
                f"{_plural(pair[1], 'cylinder')} in {count} of {repeats} runs, "
                f"{verdict}."
            )
            if pair != expected:
                all_matched = False
        lines.append(f"Seconds for {repeats} fits: {elapsed:.1f}.")
        lines.append("")

    lines.append(
        "Result: every repeat matched the construction."
        if all_matched
        else "Result: at least one repeat did not match. That is a finding."
    )
    lines.append("")
    lines.append("Read this as evidence about these three synthetic parts only.")
    lines.append("It is not a proof of determinism and it says nothing about a")
    lines.append("real scan.")
    return lines, all_matched


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 when every repeat matched the construction."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    lines, ok = measure(args.repeats)
    text = "\n".join(lines) + "\n"
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="ascii")
    print(text, end="")
    print(f"Written to {target}.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
