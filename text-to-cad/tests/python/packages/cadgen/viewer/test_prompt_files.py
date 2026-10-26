"""Quick Edit writes replayable JSON synchronously, never starting a render."""

from __future__ import annotations

import asyncio
import base64
import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cadgen.snapshot_cli import prepare_render_job_packet, read_job_file
from cadgen.snapshot_core import SnapshotError
from cadgen.viewer import handler as handler_module
from cadgen.viewer.http_app import create_cad_app
from cadgen.viewer.prompt_files import PromptFiles

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ANNOTATION = {"units": "mm", "marks": [
    {"id": "1", "kind": "stroke", "points": [0, 0, 0, 1, 1, 1] * 128, "color": "#ff2d55", "width": 2}]}
CAMERA = {"position": [10, -10, 10], "target": [0, 0, 0], "up": [0, 0, 1]}


class PromptFilesRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.model = self.tmp / "part.stl"
        self.model.write_text("solid part\nendsolid part\n", encoding="utf-8")
        self.files = self.tmp / "prompt-files"
        app = create_cad_app(host="127.0.0.1", port=0)
        app.prompt_files = PromptFiles(directory=self.files)
        server = handler_module.serve(app, "127.0.0.1", 0)
        self.port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def call(self, method: str, path: str, body=None, *, guard: bool = True) -> tuple[int, bytes, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"x-cadgen-viewer": "1", "content-type": "application/json"} if guard else {}
        try:
            connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), response.getheader("content-type") or ""
        finally:
            connection.close()

    def request(self, **overrides) -> dict:
        return {"acceptInline": True, "name": "part.stl", "input": str(self.model), "annotation": ANNOTATION, "views": [
            {"label": "view 1", "camera": CAMERA, "display": {"appearance": "dark"}, "width": 640, "height": 480},
            {"label": "view 2", "camera": "iso"},
        ], **overrides}

    def test_a_prompt_writes_replayable_json_without_rendering_or_image_files(self) -> None:
        with mock.patch("cadgen.snapshot_core.BatchSnapshotRenderer", side_effect=AssertionError("must not render")):
            status, body, _ = self.call("POST", "/__cad/prompt-files", self.request())
        answer = json.loads(body)
        snapshot_path = self.files / "part-1.snapshot.json"
        self.assertEqual((status, answer), (200, {"ok": True, "snapshot": str(snapshot_path)}))
        self.assertEqual([path.name for path in self.files.iterdir()], ["part-1.snapshot.json"])
        # Replay from another folder: one file carries the shared ink and absolute dependencies.
        packet = read_job_file(str(snapshot_path), cwd=self.tmp)
        _, replayed = prepare_render_job_packet(packet, cwd=self.tmp)
        self.assertEqual([entry.job["annotation"] for entry in replayed], [ANNOTATION, ANNOTATION])
        self.assertEqual([entry.annotation_source for entry in replayed], [""] * 2)
        common = {"output": {"padding": 0, "tightFrame": False}}
        self.assertEqual(packet, {"input": str(self.model), "annotation": ANNOTATION, "jobs": [
            {**common, "camera": CAMERA, "display": {"appearance": "dark"},
             "outputs": [{"path": str(self.files / "part-1-view-1.png"), "label": "view 1", "width": 640, "height": 480}]},
            {**common, "camera": "iso", "outputs": [{"path": str(self.files / "part-1-view-2.png"), "label": "view 2"}]},
        ]})
        status, _, content_type = self.call("GET", "/__cad/prompt-files/part-1.snapshot.json")
        self.assertEqual((status, content_type), (200, "application/json; charset=utf-8"))

    def test_a_drawings_view_is_its_plan_view_and_its_job_carries_ink(self) -> None:
        """A DXF's Quick Edit: the window on screen as a plan-view camera, the ink on the sheet,
        in a job `cadgen dxf snapshot` takes -- no 3D framing, no view name."""
        drawing = self.tmp / "panel.dxf"
        drawing.write_text("0\nSECTION\n", encoding="utf-8")
        plan = {"position": [50, 30, 120], "target": [50, 30, 0], "up": [0, 1, 0], "orthographicHalfHeight": 30}
        status, body, _ = self.call("POST", "/__cad/prompt-files", {
            "name": "panel.dxf", "input": str(drawing), "annotation": ANNOTATION,
            "views": [{"label": "view 1", "camera": plan, "width": 1600, "height": 900}]})
        self.assertEqual(status, 200, body)
        packet = json.loads((self.files / "panel-1.snapshot.json").read_text(encoding="utf-8"))
        [prepared] = prepare_render_job_packet(packet, cwd=self.tmp)[1]
        job = prepared.job
        self.assertEqual(job["camera"], plan)
        self.assertEqual(job["annotation"], ANNOTATION)
        self.assertNotIn("output", packet["jobs"][0])
        self.assertEqual(packet["jobs"][0]["outputs"], [{"path": str(self.files / "panel-1-view-1.png"), "width": 1600, "height": 900}])

    def test_a_prompt_without_an_annotation_names_none_and_the_next_prompt_is_numbered_on(self) -> None:
        _, first, _ = self.call("POST", "/__cad/prompt-files", self.request(annotation=None))
        _, second, _ = self.call("POST", "/__cad/prompt-files", self.request(annotation=None))
        self.assertNotIn("annotation", json.loads(first))
        packet = json.loads(json.loads(second)["inline"])
        self.assertIn("part-2-view-1.png", packet["jobs"][0]["outputs"][0]["path"])
        self.assertNotIn("annotation", json.loads(json.loads(first)["inline"]))
        self.assertEqual(list(self.files.glob("*.json")), [])

    def test_already_open_clients_get_a_real_file_unless_they_accept_inline(self) -> None:
        request = self.request(annotation=None, views=[{"label": "current view", "camera": CAMERA}])
        request.pop("acceptInline")
        for acceptance in (None, False, True):
            body_request = request if acceptance is None else {**request, "acceptInline": acceptance}
            status, body, _ = self.call("POST", "/__cad/prompt-files", body_request)
            self.assertEqual(status, 200, body)
            answer = json.loads(body)
            if acceptance is True:
                self.assertIn("inline", answer)
                self.assertNotIn("snapshot", answer)
                packet = json.loads(answer["inline"])
            else:
                self.assertNotIn("inline", answer)
                self.assertTrue(Path(answer["snapshot"]).is_file())
                packet = read_job_file(answer["snapshot"], cwd=self.tmp)
            self.assertEqual(len(prepare_render_job_packet(packet, cwd=self.tmp)[1]), 1)
        self.assertEqual(len(list(self.files.glob("*.snapshot.json"))), 2)

    def test_inline_cutoff_counts_utf8_bytes_and_both_forms_are_replayable(self) -> None:
        view = {"label": "a" * 48, "camera": CAMERA}  # the file name takes 48 characters of it, whatever follows
        request = self.request(annotation=None, views=[view])
        status, body, _ = self.call("POST", "/__cad/prompt-files", request)
        self.assertEqual(status, 200, body)
        base = json.loads(body)["inline"]
        view["label"] += "a" * (1024 - len(base.encode("utf-8")) - 2) + "é"
        status, body, _ = self.call("POST", "/__cad/prompt-files", request)
        inline = json.loads(body)["inline"]
        self.assertEqual(len(inline.encode("utf-8")), 1024)
        self.assertEqual(list(self.files.glob("*.json")), [])
        self.assertEqual(len(prepare_render_job_packet(json.loads(inline), cwd=self.tmp)[1]), 1)
        view["label"] += "a"
        status, body, _ = self.call("POST", "/__cad/prompt-files", request)
        self.assertEqual(status, 200, body)
        answer = json.loads(body)
        self.assertNotIn("inline", answer)
        saved = read_job_file(answer["snapshot"], cwd=self.tmp)
        self.assertEqual(len(prepare_render_job_packet(saved, cwd=self.tmp)[1]), 1)
        self.assertEqual(saved["jobs"][0]["outputs"][0]["label"], view["label"])

    def test_a_request_snapshot_would_refuse_is_refused_before_anything_renders(self) -> None:
        for request, said in (
            ([], "requested as an object"),
            (self.request(views=[]), "at least one"),
            (self.request(extra=1), "unknown field(s): extra"),
            (self.request(acceptInline="true"), "acceptInline is a boolean"),
            (self.request(sketch=ANNOTATION), "unknown field(s): sketch"),
            (self.request(input="part.stl"), "absolute path"),
            (self.request(input=str(self.tmp / "gone.step")), "no file at"),
            (self.request(views=[{"camera": "iso"}]), "views[0].label"),
            (self.request(views=[{"label": "a", "camera": "iso", "width": 0}]), "views[0].width"),
            (self.request(annotation={"marks": {}}), "annotation is null or an object"),
            # snapshot's own preparation: a camera key it does not take, a pose a mesh does not have
            (self.request(views=[{"label": "a", "camera": {"projection": "perspective"}}]), "display.camera"),
            (self.request(views=[{"label": "a", "camera": "iso", "kinematics": {"x": 1}}]), "kinematics"),
            # Quick Edit sends no measurements: the field is unknown like any other
            (self.request(measurements=[]), "unknown field(s): measurements"),
            # a routine's frame reaches snapshot's own check: a mesh has none
            (self.request(views=[{"label": "a", "camera": "iso", "animation": {"clip": "spin", "time": 1}}]), "animation in its sidecar"),
        ):
            status, body, _ = self.call("POST", "/__cad/prompt-files", request)
            self.assertEqual(status, 400, request)
            self.assertEqual(json.loads(body)["ok"], False)
            self.assertIn(said, json.loads(body)["error"])
        self.assertEqual(sorted(path.name for path in self.files.iterdir()) if self.files.exists() else [], [])

    def test_a_chips_copy_is_saved_as_the_file_snapshot_reads_and_answered_with_its_path(self) -> None:
        status, body, _ = self.call("POST", "/__cad/prompt-files/save", {"name": "part.stl", "kind": "annotation", "data": ANNOTATION})
        self.assertEqual((status, json.loads(body)), (200, {"ok": True, "path": str(self.files / "part-1.annotation.json")}))
        self.assertEqual(json.loads((self.files / "part-1.annotation.json").read_text(encoding="utf-8")), ANNOTATION)
        for request, said in (
            ({"name": "part.stl", "kind": "image", "data": {}}, "kind is annotation"),
            ({"name": "part.stl", "kind": "sketch", "data": ANNOTATION}, "kind is annotation"),
            ({"name": "part.stl", "kind": "annotation", "data": {"marks": {}}}, "marks (a list)"),
            ({"name": "part.stl", "kind": "measurement", "data": {}}, "kind is annotation"),
        ):
            status, body, _ = self.call("POST", "/__cad/prompt-files/save", request)
            self.assertEqual((status, json.loads(body)["ok"]), (400, False), request)
            self.assertIn(said, json.loads(body)["error"])

    def test_render_polling_is_not_an_endpoint(self) -> None:
        self.assertEqual(self.call("GET", "/__cad/prompt-files?id=nope")[0], 404)

    def test_files_are_served_from_the_prompt_files_directory_only_and_to_the_viewer_only(self) -> None:
        _, body, _ = self.call("POST", "/__cad/prompt-files", self.request())
        (self.files / "part-1-view-1.png").write_bytes(PNG)
        self.assertEqual(self.call("GET", "/__cad/prompt-files/part-1-view-1.png")[0], 404)
        (self.tmp / "secret.json").write_text("{}", encoding="utf-8")
        for name in ("..%2Fsecret.json", "../secret.json", "missing.png", "part-1.job.txt", ""):
            self.assertEqual(self.call("GET", f"/__cad/prompt-files/{name}")[0], 404, name)
        self.assertEqual(self.call("GET", "/__cad/prompt-files/part-1-current.png", guard=False)[0], 403)
        self.assertEqual(self.call("GET", "/__cad/prompt-files?id=old", guard=False)[0], 403)


class SnapshotOwnershipTest(unittest.TestCase):
    """The real snapshot call chain borrows a session and owns a standalone render."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="warm-snapshot-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "part.stl").write_text(
            "solid part\nfacet normal 0 0 1\nouter loop\n"
            "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
            "endloop\nendfacet\nendsolid part\n", encoding="utf-8")
        self.renderers = []
        owner = self

        class Renderer:
            def __init__(self, runtime_dir) -> None:
                self.closed = 0
                self.jobs = []
                owner.renderers.append(self)

            async def render(self, job):
                owner.assertEqual(0, self.closed, "a borrowed renderer was closed between prompts")
                owner.assertEqual("stl", job["resolved"]["kind"])
                self.jobs.append(job)
                if Path(job["outputs"][0]["path"]).stem == "bad":
                    raise SnapshotError("render failed")
                return {"ok": True, "mode": "view", "outputs": [
                    {"path": output["path"], "mimeType": "image/png",
                     "dataUrl": "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")}
                    for output in job["outputs"]
                ]}

            async def close(self) -> None:
                self.closed += 1

        patcher = mock.patch("cadgen.snapshot_core.BatchSnapshotRenderer", Renderer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def job(self, name: str) -> Path:
        path = self.root / f"{name}.job.json"
        path.write_text(json.dumps({"input": "part.stl", "outputs": [{"path": f"{name}.png"}]}), encoding="utf-8")
        return path

    def test_real_pipeline_closes_its_own_renderer_on_success_and_failure(self) -> None:
        from cadgen._internal.snapshot_door import ALL_KINDS
        from cadgen.snapshot_cli import SnapshotOptions, run_snapshot_async

        def render(name):
            return asyncio.run(run_snapshot_async(
                SnapshotOptions(job=str(self.job(name))), kinds=ALL_KINDS,
                cwd=self.root, report=False))

        self.assertTrue(render("owned").ok)
        self.assertEqual((self.root / "owned.png").read_bytes(), PNG)
        self.assertEqual(self.renderers[0].closed, 1)
        with self.assertRaisesRegex(SnapshotError, "render failed"):
            render("bad")
        self.assertEqual([renderer.closed for renderer in self.renderers], [1, 1])


if __name__ == "__main__":
    unittest.main()
