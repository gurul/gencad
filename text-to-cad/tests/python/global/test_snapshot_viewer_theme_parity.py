"""Behavioral parity for the shared Viewer and Python snapshot display schema."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path, repo_path

add_repo_path("packages/cadgen/src")
from cadgen.snapshot_core import (
    CAMERA_OPTION_KEYS, CAD_MODEL_DISPLAY_MODES, DISPLAY_GROUP_KEYS, DISPLAY_MODES, DISPLAY_OPTION_KEYS,
    SnapshotError, display_modes_for_kind, load_display_option, normalize_common_job, validate_camera_option,
    validate_display_settings_values,
)

VIEW = repo_path("packages/core/src/common/viewSettings.js")
SCENE = repo_path("packages/core/src/common/sceneSettings.js")
CAMERA = repo_path("packages/core/src/common/camera.js")
VALIDATOR = repo_path("packages/core/src/common/snapshotJobValidation.js")


def javascript(expression: str, payload=None):
    script = f"""
import fs from "node:fs";
import * as view from {json.dumps(VIEW.as_uri())};
import * as scene from {json.dumps(SCENE.as_uri())};
import {{ CAMERA_SPEC_KEYS, normalizeCameraSpec }} from {json.dumps(CAMERA.as_uri())};
import {{ validateSnapshotRenderJob }} from {json.dumps(VALIDATOR.as_uri())};
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const accepts = fn => {{ try {{ fn(); return true; }} catch {{ return false; }} }};
console.log(JSON.stringify({expression}));
"""
    completed = subprocess.run(["node", "--input-type=module", "-e", script],
                               input=json.dumps(payload), text=True, capture_output=True,
                               check=True, cwd=repo_path())
    return json.loads(completed.stdout)


def python_accepts(values, validator):
    result = []
    for value in values:
        try:
            validator(value)
        except SnapshotError:
            result.append(False)
        else:
            result.append(True)
    return result


class SharedDisplayContractParityTests(unittest.TestCase):
    def test_exported_closed_key_sets_and_enums_match(self):
        expected = {
            # A file's modes are the snapshot's display modes; Preview's look is asked for on its
            # own (a snapshot's `preview`), and its settings are the viewer's alone.
            "VIEW_MODE_VALUES": DISPLAY_MODES,
            "VIEW_SETTINGS_KEYS": DISPLAY_OPTION_KEYS,
            **{f"VIEW_{name.upper()}_KEYS": keys for name, keys in DISPLAY_GROUP_KEYS.items()
               if name not in {"clip", "exploded"}},
        }
        actual = javascript("Object.fromEntries(cases.map(key => [key, view[key]]))", list(expected))
        for name, values in expected.items():
            with self.subTest(export=name):
                self.assertEqual(set(actual[name]), set(values))

    def test_each_kind_offers_the_same_modes_in_both_languages(self):
        # The viewer offers Parts only where a file has several parts, which a snapshot cannot know
        # before it reads the file: the snapshot takes it for any 3D file, and the page draws a
        # file of one part in Solid. Every other mode is offered alike.
        kinds = ["step", "stp", "stl", "3mf", "glb", "urdf", "sdf"]
        offered = javascript("cases.map(kind => view.viewFeaturesForKind(kind, { parts: 2 }).modes)", kinds)
        for kind, modes in zip(kinds, offered):
            with self.subTest(kind=kind):
                self.assertEqual(set(modes), set(display_modes_for_kind(kind)))
        self.assertEqual(DISPLAY_MODES - {"solid", "parts"}, CAD_MODEL_DISPLAY_MODES)

    def test_display_values_match_in_both_languages(self):
        valid = [
            {}, *({"mode": mode} for mode in DISPLAY_MODES), {"appearance": "dark"},
            {"grid": True}, {"grid": False}, {"mode": "parts", "grid": True},
            *({group: {}} for group in DISPLAY_GROUP_KEYS),
            {"camera": {"projection": "perspective", "focalLength": 20}},
            {"camera": {"projection": "orthographic", "focalLength": 200}},
            {"clip": {"partColors": True}}, {"clip": {"partColors": False}},
            {"clip": {"axis": "z", "at": -12.5, "invert": True}}, {"clip": {"enabled": False, "at": 3}},
            {"exploded": {"enabled": True, "amount": 1}},
        ]
        invalid = [
            None, [], True, "solid", {"render": {}}, {"preview": {}}, {"guides": {}}, {"partColor": {}},
            # A mode has no settings of its own: the per-mode tree, and every group it held, are gone.
            {"modes": {}}, {"modes": {"solid": {"flat": True}}}, {"modes": {"render": {"floor": {"enabled": False}}}},
            *({old: {}} for old in ("surfaces", "edges", "lighting", "background", "floor", "axes", "parts", "flat")),
            *({"grid": value} for value in (None, 0, 1, "on", {}, {"enabled": True})),
            *({"mode": value} for value in (None, [], {}, True, "", "SOLID", "Grid", "grid", "render", "hidden_line")),
            *({"appearance": value} for value in (None, [], {}, True, "system")),
            *({group: value} for group in DISPLAY_GROUP_KEYS for value in (None, [], True, "off", {"typo": 1}, {"enabled": 0})),
            *({"camera": {"focalLength": value}} for value in (None, "50", True, 19.9, 200.1)),
            {"camera": {"enabled": True}},
            *({"clip": {"partColors": value}} for value in (None, 0, "false", [])),
            {"clip": {"axis": "w"}}, {"clip": {"offset": 0.5}}, {"clip": {"offsets": {"x": 0.5}}},
            {"exploded": {"amount": 1.01}},
            *({"clip": {"at": value}} for value in (None, "3", True, [])),
        ]
        cases = valid + invalid
        python = python_accepts(cases, lambda value: validate_display_settings_values(value, source_label="parity"))
        shared = javascript("cases.map(value => accepts(() => view.normalizeViewSettings(value)))", cases)
        for index, value in enumerate(cases):
            with self.subTest(value=value):
                self.assertEqual(index < len(valid), python[index])
                self.assertEqual(python[index], shared[index])

    def test_python_packets_resolve_to_the_same_mode_and_grid(self):
        # A display, and whether the job asks for Preview's look (`preview`, never a display mode).
        cases = [
            ({}, False), ({}, True), ({"mode": "xray"}, False), ({"mode": "hidden-line"}, False), ({"mode": "wireframe"}, False),
            ({"mode": "shaded"}, False), ({"mode": "parts", "grid": True}, False),
            ({"mode": "solid", "camera": {"projection": "perspective"}, "grid": True}, False),
            ({"mode": "xray", "grid": True}, True),
        ]
        packets = [normalize_common_job({"input": "part.step", "outputs": [{"path": "out.png"}], "display": display, "preview": preview},
                                      mode="view", resolved_cwd=Path("."), timestamp="parity") for display, preview in cases]
        self.assertEqual([preview for _, preview in cases], [packet.get("preview", False) for packet in packets])
        expected = javascript("cases.map(([display, preview]) => view.resolveViewSettings(display, { preview }))", cases)
        actual = javascript("cases.map(packet => view.resolveViewSettings(packet.display, { preview: packet.preview === true }))", packets)
        self.assertEqual(expected, actual)
        self.assertEqual("perspective", actual[1]["camera"]["projection"])
        self.assertEqual("orthographic", actual[0]["camera"]["projection"])
        self.assertTrue(actual[1]["lighting"]["enabled"])
        self.assertEqual("origin", actual[1]["floor"]["placement"])
        self.assertFalse(actual[5]["edges"]["enabled"])
        self.assertEqual(("parts", "by-part", True), (actual[6]["mode"], actual[6]["surfaces"]["colorMode"], actual[6]["grid"]["enabled"]))
        self.assertTrue(actual[7]["grid"]["enabled"])
        self.assertEqual(("render", False), (actual[8]["mode"], actual[8]["grid"]["enabled"]), "Preview draws no grid")

    def test_public_camera_keys_match_the_shared_pose_fields(self):
        self.assertEqual(set(javascript('CAMERA_SPEC_KEYS.filter(key => !["projection", "focalLength"].includes(key))')), set(CAMERA_OPTION_KEYS))

    def test_camera_pose_and_projection_have_one_home(self):
        cases = [
            {"preset": "front"}, {"orthographicHalfHeight": 12},
            {"position": [1, 2, 3], "target": [0, 0, 0]},
            {"projection": "orthographic"}, {"focalLength": 85},
            {"position": [1, 2, "3"]}, {"up": None}, {"direction": [0, 0, 0]},
            {"zoom": "2"}, {"orthographicHalfHeight": False}, {"typo": 1},
        ]
        python = python_accepts(cases, lambda value: validate_camera_option(value, source_label="parity"))
        shared = javascript("cases.map(camera => accepts(() => { validateSnapshotRenderJob({camera}); normalizeCameraSpec(camera, {strict:true}); }))", cases)
        self.assertEqual([True] * 3 + [False] * 8, python)
        self.assertEqual(python, shared)


if __name__ == "__main__":
    unittest.main()
