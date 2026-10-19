"""Quick Edit's JSON handoff files, written synchronously without rendering.

POST /__cad/prompt-files validates a snapshot packet in memory, then returns 200
with compact inline JSON up to 1024 UTF-8 bytes, or writes one .snapshot.json and returns its path. Shared input, inline annotation and
measurements are stored once; jobs reserve output names for an agent to render later with
``cadgen snapshot --job <file>``. No PNG is produced by this route.
POST /__cad/prompt-files/save writes an annotation or measurement chip's JSON.
Guarded GET /__cad/prompt-files/<name> reads only JSON from this process's
scratch directory. Files outlive the viewer until the system clears them.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from cadgen._internal.atomic_replace import write_bytes_atomic

__all__ = ["PROMPT_FILES_ROUTE", "PromptFiles"]

PROMPT_FILES_ROUTE = "/__cad/prompt-files"
# How long a request carries: an annotation is points, and a long session of annotating is megabytes.
MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_VIEWS = 16
# Compact UTF-8 JSON, not whitespace or a model-specific tokenizer.
INLINE_SNAPSHOT_BYTES = 1024
_REQUEST_KEYS = frozenset({"name", "input", "views", "annotation", "measurements", "acceptInline"})
_VIEW_KEYS = frozenset({"label", "camera", "display", "kinematics", "jointValues", "animation", "selection", "width", "height"})
_ANNOTATION_KEYS = frozenset({"units", "parts", "marks"})
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json")


def _slug(text: str, fallback: str) -> str:
    return _UNSAFE.sub("-", text).strip("-.")[:48] or fallback


def _stem(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/"))
    for suffix in (".step", ".stp", ".stl", ".3mf", ".glb", ".urdf", ".srdf", ".sdf", ".dxf"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    return _slug(base, "model")


def _directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="cadgen-prompt-files-"))


class PromptFiles:
    """This process's scratch directory and collision-free file numbering."""

    def __init__(self, *, directory=None) -> None:
        self._directory_factory = (lambda: Path(directory)) if directory is not None else _directory
        self._directory: Path | None = None
        self._lock = threading.Lock()
        self._count = 0

    @property
    def directory(self) -> Path:
        with self._lock:
            if self._directory is None:
                self._directory = self._directory_factory()
                self._directory.mkdir(parents=True, exist_ok=True)
            return self._directory

    # --- POST ----------------------------------------------------------------

    def save(self, body: bytes) -> tuple[int, dict]:
        """A Quick Edit chip's copy as a file, written at once: ``200 {"ok": true, "path"}``, or ``400``.

        ``{"name", "kind": "annotation", "data": <an annotation>}`` writes ``<name>-<n>.annotation.json``
        (``cadgen snapshot --annotation`` reads it); ``{"name", "kind": "measurement", "data":
        {start, end, label, color}}`` writes ``<name>-<n>.measurement.json``, the list of that one
        (``--measurements`` reads it). Nothing renders.
        """
        try:
            request = json.loads(body or b"null")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"a chip's file is requested as JSON: {error}") from None
        if type(request) is not dict or not set(request) <= {"name", "kind", "data"}:
            raise ValueError("a chip's file is requested as {name, kind, data}")
        kind, data = request.get("kind"), request.get("data")
        if kind == "annotation":
            if type(data) is not dict or not set(data) <= _ANNOTATION_KEYS or type(data.get("marks")) is not list:
                raise ValueError("an annotation is an object of units, parts and marks (a list)")
            content, suffix = data, "annotation"
        elif kind == "measurement":
            from cadgen.snapshot_cli import normalize_measurements
            from cadgen.snapshot_core import SnapshotError

            try:
                content = normalize_measurements([data])
            except SnapshotError as error:
                raise ValueError(str(error)) from None
            suffix = "measurement"
        else:
            raise ValueError("kind is annotation or measurement")
        name = request.get("name")
        directory = self.directory
        with self._lock:
            self._count += 1
            path = directory / f"{_stem(name if type(name) is str and name else kind)}-{self._count}.{suffix}.json"
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return 200, {"ok": True, "path": str(path)}

    def create(self, body: bytes) -> tuple[int, dict]:
        """Validate one snapshot packet, then return inline JSON or its saved path with ``200``."""
        try:
            request = json.loads(body or b"null")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"a prompt's files are requested as JSON: {error}") from None
        name, input_path, views, annotation, measurements = _checked(request)
        directory = self.directory
        with self._lock:
            self._count += 1
            prefix = f"{_stem(name or input_path)}-{self._count}"
        labels: set[str] = set()
        jobs = []
        # A drawing's view is its plan view, framed as the pane framed it (its camera); it has no
        # 3D framing to pin and no view name to carry (`check_drawing_render_job`).
        drawing = str(input_path).lower().endswith(".dxf")
        for index, view in enumerate(views):
            slug = _slug(view["label"].lower(), f"view-{index + 1}")
            while slug in labels:
                slug = f"{slug}-{index + 1}"
            labels.add(slug)
            image = directory / f"{prefix}-{slug}.png"
            output = {"path": str(image)} if drawing else {"path": str(image), "label": view["label"]}
            for key in ("width", "height"):
                if key in view:
                    output[key] = view[key]
            job: dict[str, object] = {}
            job["camera"] = view["camera"]
            for key in ("display", "kinematics", "jointValues", "animation", "selection"):
                if view.get(key) is not None:
                    job[key] = view[key]
            if not drawing:
                job["output"] = {"padding": 0, "tightFrame": False}
            job["outputs"] = [output]
            jobs.append(job)
        packet: dict[str, object] = {"input": input_path, "jobs": jobs}
        if annotation is not None:
            packet["annotation"] = annotation
        if measurements:
            packet["measurements"] = measurements
        _accepted(packet, cwd=directory)
        compact = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        # Already-open clients expect a path. Only clients advertising inline support get JSON.
        if request.get("acceptInline", False) and len(compact.encode("utf-8")) <= INLINE_SNAPSHOT_BYTES:
            return 200, {"ok": True, "inline": compact}
        snapshot_path = directory / f"{prefix}.snapshot.json"
        write_bytes_atomic(snapshot_path, (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return 200, {"ok": True, "snapshot": str(snapshot_path)}

    def file(self, name: str) -> tuple[bytes, str] | None:
        """A file of this directory, by its bare name, and its content type; ``None`` for any other."""
        if not _FILE_NAME.fullmatch(name or ""):
            return None
        with self._lock:
            directory = self._directory
        if directory is None:
            return None
        path = directory / name
        try:
            if path.is_symlink() or not path.is_file():
                return None
            data = path.read_bytes()
        except OSError:
            return None
        return data, "application/json; charset=utf-8"


def _checked(request) -> tuple[str, str, list[dict], dict | None, list | None]:
    """The request's fields, each checked; ``ValueError`` names what is wrong."""
    if type(request) is not dict:
        raise ValueError("a prompt's files are requested as an object: {name, input, views, annotation, measurements}")
    unknown = sorted(set(request) - _REQUEST_KEYS)
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(unknown)}; a request has {', '.join(sorted(_REQUEST_KEYS))}")
    if type(request.get("acceptInline", False)) is not bool:
        raise ValueError("acceptInline is a boolean")
    name = request.get("name")
    if name is not None and type(name) is not str:
        raise ValueError("name is the file's name, a string")
    input_path = request.get("input")
    if type(input_path) is not str or not os.path.isabs(input_path):
        raise ValueError("input is the absolute path of the file the views show")
    if not os.path.isfile(input_path):
        raise ValueError(f"no file at {input_path}")
    views = request.get("views")
    if type(views) is not list or not views:
        raise ValueError("views lists the views to save, at least one")
    if len(views) > MAX_VIEWS:
        raise ValueError(f"a prompt saves at most {MAX_VIEWS} views")
    for index, view in enumerate(views):
        at = f"views[{index}]"
        if type(view) is not dict:
            raise ValueError(f"{at} is an object: {{label, camera, ...}}")
        unknown = sorted(set(view) - _VIEW_KEYS)
        if unknown:
            raise ValueError(f"{at} has unknown field(s): {', '.join(unknown)}; a view has {', '.join(sorted(_VIEW_KEYS))}")
        if type(view.get("label")) is not str or not view["label"].strip():
            raise ValueError(f"{at}.label names the view")
        if type(view.get("camera")) not in (dict, str):
            raise ValueError(f"{at}.camera is the view's camera")
        for key in ("width", "height"):
            if key in view and (type(view[key]) is not int or not 1 <= view[key] <= 8192):
                raise ValueError(f"{at}.{key} is a number of pixels, 1 to 8192")
    annotation = request.get("annotation")
    if annotation is not None:
        if type(annotation) is not dict or not set(annotation) <= _ANNOTATION_KEYS or type(annotation.get("marks")) is not list:
            raise ValueError("annotation is null or an object of units, parts and marks (a list)")
        if not all(type(mark) is dict for mark in annotation["marks"]):
            raise ValueError("annotation.marks lists objects")
    # Measure's results: their shape is snapshot's to check, with the job (`_accepted`).
    measurements = request.get("measurements")
    if measurements is not None and type(measurements) is not list:
        raise ValueError("measurements is null or a list of {start, end, label, color}")
    return name or "", input_path, views, annotation, measurements


def _accepted(packet: dict, *, cwd: Path) -> None:
    """The job file as ``cadgen snapshot --job`` accepts it, before anything renders.

    Snapshot's own preparation (``prepare_render_job_packet``): it refuses what a request
    can be refused for and builds nothing. Its refusal is this request's 400.
    """
    from cadgen._internal.snapshot_door import ALL_KINDS
    from cadgen.snapshot_cli import enabled_kinds, prepare_render_job_packet
    from cadgen.snapshot_core import SnapshotError

    try:
        prepare_render_job_packet(
            packet, cwd=cwd, kinds=enabled_kinds(ALL_KINDS)
        )
    except SnapshotError as error:
        raise ValueError(str(error)) from None
