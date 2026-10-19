"""Unified display, technical output, and tessellation are closed schemas."""

from __future__ import annotations

import inspect
import re
import tempfile
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path, repo_path

add_repo_path("packages/cadgen/src")

from cadgen.snapshot_core import (  # noqa: E402
    MIN_RENDER_TESSELLATION,
    DISPLAY_APPEARANCES,
    DISPLAY_MODES,
    SUPPORTED_OUTPUT_SETTINGS_KEYS,
    SUPPORTED_QUALITY_KEYS,
    SnapshotError,
    load_display_option,
    normalize_common_job,
    validate_render_tessellation,
)


def normalize(**settings: object) -> dict[str, object]:
    return normalize_common_job(
        {"input": "part.step", "outputs": [{"path": "out.png"}], **settings},
        mode="view",
        resolved_cwd=Path("."),
        timestamp="20260907-000000",
    )


class RenderDisplaySchemaTest(unittest.TestCase):
    def test_modes_and_appearance_are_closed(self):
        # Preview's look is no display mode: it is its own request (`preview`). Grid is a switch.
        self.assertEqual({"solid", "shaded", "parts", "xray", "hidden-line", "wireframe"}, set(DISPLAY_MODES))
        self.assertEqual({"light", "dark"}, set(DISPLAY_APPEARANCES))
        for mode in DISPLAY_MODES:
            self.assertEqual({"mode": mode}, load_display_option(mode, cwd=Path(".")))
        for invalid in ("render", "preview", "grid", "Grid", "transparent", "hidden_edges", "unshaded", None, True, [], {}):
            with self.subTest(mode=invalid), self.assertRaises(SnapshotError):
                load_display_option({"mode": invalid}, cwd=Path("."))
        for invalid in ("system", "LIGHT", None, False, [], {}):
            with self.subTest(appearance=invalid), self.assertRaises(SnapshotError):
                load_display_option({"appearance": invalid}, cwd=Path("."))
        for invalid in (None, 1, "on", {"enabled": True}):
            with self.subTest(grid=invalid), self.assertRaises(SnapshotError):
                load_display_option({"grid": invalid}, cwd=Path("."))

    def test_mode_names_do_not_depend_on_existing_output_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wireframe").mkdir()
            self.assertEqual({"mode": "wireframe"}, load_display_option("wireframe", cwd=root))

    def test_a_display_is_a_mode_the_grid_and_what_modes_share_and_stays_sparse(self):
        display = {
            "mode": "parts", "grid": True, "appearance": "dark",
            "camera": {"projection": "perspective", "focalLength": 85},
            "clip": {"enabled": True, "axis": "z", "at": 0.5},
            "exploded": {"enabled": True, "amount": 0.5},
        }
        self.assertEqual(display, load_display_option(display, cwd=Path(".")))
        with tempfile.TemporaryDirectory() as tmp:
            import json
            root = Path(tmp)
            (root / "display.json").write_text(json.dumps(display), encoding="utf-8")
            self.assertEqual(display, load_display_option("display.json", cwd=root))

    def test_group_values_are_strict(self):
        for display in ({"camera": {"focalLength": 19.9}}, {"camera": {"focalLength": 200.1}},
                        {"camera": {"projection": "ortho"}}, {"exploded": {"amount": 1.01}}, {"clip": {"axis": "w"}}):
            with self.subTest(display=display), self.assertRaises(SnapshotError):
                load_display_option(display, cwd=Path("."))

    def test_per_mode_settings_and_older_groups_are_rejected(self):
        # A mode is drawn at its own defaults: the per-mode tree (and Preview's settings in it) is no
        # display setting, and neither is any group a mode used to hold.
        for key in ("modes", "render", "preview", "guides", "partColor", "surfaces", "edges", "lighting",
                    "background", "floor", "axes", "parts", "flat", "opacity"):
            with self.subTest(key=key), self.assertRaises(SnapshotError):
                load_display_option({key: {}}, cwd=Path("."))

    def test_default_job_is_light_solid_without_overriding_groups(self):
        self.assertEqual({"mode": "solid", "appearance": "light"}, normalize()["display"])
        # Preview's look is drawn over the same display: the page's own flag, never a display mode.
        previewed = normalize(preview=True)
        self.assertEqual(({"mode": "solid", "appearance": "light"}, True), (previewed["display"], previewed["preview"]))
        self.assertNotIn("preview", normalize(preview=False))
        self.assertNotIn("preview", normalize())
        self.assertEqual({"mode": "xray", "appearance": "dark", "grid": True},
                         normalize(display={"mode": "xray", "appearance": "dark", "grid": True})["display"])
        with self.assertRaises(SnapshotError):
            normalize(preview="yes")

    def test_animation_and_output_capture_controls_remain_composable(self):
        job = normalize(
            camera={"preset": "front"}, preview=True,
            animation={"clip": "spin", "time": 0.5},
            output={"sizeProfile": "diagnostic", "viewLabels": True},
        )
        self.assertEqual(job["camera"], {"preset": "front"})
        self.assertEqual((job["display"]["mode"], job["preview"]), ("solid", True))
        self.assertEqual(job["animation"], {"clip": "spin", "time": 0.5})
        self.assertEqual(job["output"], {"sizeProfile": "diagnostic", "viewLabels": True})

    def test_public_api_has_a_display_surface_and_grid_and_preview_beside_it(self):
        from cadgen import step
        signature = inspect.signature(step.snapshot)
        self.assertIn("display", signature.parameters)
        self.assertIn("camera", signature.parameters)
        self.assertIs(signature.parameters["grid"].default, False)
        self.assertIs(signature.parameters["preview"].default, False)
        self.assertNotIn("render", signature.parameters)

    def test_output_and_quality_are_closed(self):
        output = {
            "sizeProfile": "diagnostic", "padding": 0.1,
            "viewLabels": True, "tightFrame": True, "transparent": True, "renderScale": 2,
        }
        self.assertEqual(set(output), set(SUPPORTED_OUTPUT_SETTINGS_KEYS))
        self.assertEqual({"tessellation"}, set(SUPPORTED_QUALITY_KEYS))
        normalize(output=output, quality={"tessellation": {"chordTolerance": 0.001}})
        with self.assertRaisesRegex(SnapshotError, "output has unknown key"):
            normalize(output={"pixels": 2})
        # One name per setting: the old second spelling of `padding` names its replacement.
        with self.assertRaisesRegex(SnapshotError, r"output\.paddingPercent was removed; use output\.padding"):
            normalize(output={"paddingPercent": 0.1})


class RenderTessellationLimitsTest(unittest.TestCase):
    def test_unknown_field_and_non_numbers_are_refused(self):
        for value in ({"quality": "high"}, {"chordTolerance": "0.001"}, {"chordTolerance": True}):
            with self.assertRaises(SnapshotError):
                validate_render_tessellation(value)
        with self.assertRaises(SnapshotError):
            validate_render_tessellation([0.001])

    def test_tolerances_below_the_floor_are_refused_here_not_in_the_browser(self):
        with self.assertRaises(SnapshotError) as caught:
            normalize(quality={"tessellation": {"chordTolerance": 1e-12}})
        self.assertIn("at least 1e-05", str(caught.exception))
        with self.assertRaises(SnapshotError):
            normalize(quality={"tessellation": {"angleTolerance": 1e-6}})
        # The floors themselves, and everything coarser, are legal requests.
        validate_render_tessellation(dict(MIN_RENDER_TESSELLATION))
        validate_render_tessellation({"chordTolerance": 0.0005, "angleTolerance": 0.10})
        validate_render_tessellation(None)

    def test_the_floors_match_the_page_that_tessellates(self):
        source = repo_path("packages/core/src/common/source.js").read_text(encoding="utf-8")
        block = re.search(r"RENDER_TESSELLATION_FLOORS = Object\.freeze\(\{(.*?)\}\)", source, re.S)
        self.assertIsNotNone(block, "source.js no longer declares RENDER_TESSELLATION_FLOORS")
        declared = {
            key: float(value)
            for key, value in re.findall(r"(\w+):\s*([0-9.e-]+)", block.group(1))
        }
        self.assertEqual(declared, MIN_RENDER_TESSELLATION)


if __name__ == "__main__":
    unittest.main()
