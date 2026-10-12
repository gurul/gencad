#!/usr/bin/env python3
"""Scaffold an Enclose project folder from gencad output.

Enclose (https://github.com/enclosedev/enclose, AGPL-3.0, pinned as the
`enclose/` git submodule) is an Electron app for inspecting a code-built CAD
model part by part and asking Claude to change it. One of its project folders
holds a build123d `model.py`, the kit exporter that script imports, an
`enclose.json` naming the build command, and the `build/` output.

This bridge turns STEP files, or a FreeCAD .FCStd document, into such a folder:

    OUT_DIR/
      source/<input>.step      the STEP inputs (or the FCStd export) copied in
      enclose.py, screws.py    copied at run time from <enclose_root>/kit/
      model.py                 reads every body of this call's STEP files
                               (older files in source/ are not listed)
      enclose.json             {"model": "build/enclose.model.json", "build": ...}
      .gitignore               build/ and .venv/  (only if absent)
      .mcp.json                registers gencad's MCP server   (with_mcp)
      .claude/settings.json    pre-approves that server        (with_mcp)

Given a build Python (one with build123d), it also runs `model.py` and reports
the parts in the manifest the build wrote.

Stdlib only, Python 3.9+. Importable (make_project) and a CLI:

    python3 tools/enclose_project.py OUT_DIR --step a.step [--step b.step]
    python3 tools/enclose_project.py OUT_DIR --fcstd model.FCStd [--object Base]
        [--name N] [--build-python PY] [--no-mcp] [--overwrite]
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PATH = os.path.join(REPO, "server", "gencad_mcp.py")
DEFAULT_FREECADCMD = "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"

KIT_FILES = ("enclose.py", "screws.py")
MANIFEST_REL = "build/enclose.model.json"
STEP_EXTS = (".step", ".stp")
MCP_SERVER_NAME = "gencad"

# freecadcmd catches a script's uncaught exception, prints this line and still
# exits 0, so the exit code alone cannot tell success from a crashed script.
FREECAD_EXCEPTION = "Exception while processing file"
# printed by the generated export script as its last action
EXPORT_SENTINEL = "gencad-enclose-export-ok:"
EXPORT_LABELS = "gencad-enclose-exported:"
EXPORT_CONSUMED = "gencad-enclose-consumed:"

FREECAD_TIMEOUT_S = 600
BUILD_TIMEOUT_S = 600


class EncloseProjectError(RuntimeError):
    """Raised for every input, setup, export or build failure."""


# --- resolution ------------------------------------------------------------

def resolve_enclose_root(enclose_root=None):
    root = (enclose_root or os.environ.get("GENCAD_ENCLOSE_ROOT")
            or os.path.join(REPO, "enclose"))
    root = os.path.abspath(root)
    missing = [f for f in KIT_FILES
               if not os.path.isfile(os.path.join(root, "kit", f))]
    if missing:
        raise EncloseProjectError(
            "Enclose kit not found: %s is missing %s. The enclose/ submodule is "
            "probably not checked out; run: git submodule update --init enclose "
            "(or set GENCAD_ENCLOSE_ROOT to an Enclose checkout)"
            % (root, ", ".join("kit/" + f for f in missing)))
    return root


def find_freecadcmd():
    """Same order as gencad_mcp.freecadcmd(); None when nothing is found."""
    cand = os.environ.get("GENCAD_FREECADCMD")
    if cand and os.path.exists(cand):
        return cand
    if os.path.exists(DEFAULT_FREECADCMD):
        return DEFAULT_FREECADCMD
    return shutil.which("freecadcmd")


# --- small helpers -----------------------------------------------------------

def _title_from_stem(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    words = stem.replace("_", " ").replace("-", " ").split()
    title = " ".join(w[:1].upper() + w[1:] for w in words)
    return title or "Model"


def _is_inside(path, directory):
    """True when `path` lies under `directory`, symlinked dirs resolved."""
    real_dir = os.path.realpath(directory)
    real_parent = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    try:
        return os.path.commonpath([real_dir, real_parent]) == real_dir
    except ValueError:  # different drives
        return False


def _build_command(build_python, out_dir):
    """(enclose.json `build` value, absolute interpreter path or None).
    Enclose runs the build through a shell in the project folder, so the
    interpreter path is shell-quoted."""
    if not build_python:
        return "python3 model.py", None
    py = build_python
    if os.sep not in py and not os.path.isabs(py):
        found = shutil.which(py)
        if found is None:
            raise EncloseProjectError("build python not found on PATH: %s" % py)
        py = found
    py = os.path.abspath(py)
    if not os.path.isfile(py):
        raise EncloseProjectError("no such build python: %s" % py)
    if _is_inside(py, out_dir):
        # relative to the project, computed on resolved dirs so /tmp vs
        # /private/tmp cannot produce a ../../ path; the interpreter itself
        # stays unresolved (a venv python is a symlink that must stay one)
        real_parent = os.path.realpath(os.path.dirname(py))
        rel = os.path.relpath(os.path.join(real_parent, os.path.basename(py)),
                              os.path.realpath(out_dir))
        if os.sep not in rel:
            rel = "." + os.sep + rel  # a bare name would be looked up on PATH
        return "%s model.py" % shlex.quote(rel), py
    return "%s model.py" % shlex.quote(py), py


def _load_json_object(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise EncloseProjectError(
            "cannot merge into %s: it is not valid JSON (%s)" % (path, e))
    if not isinstance(data, dict):
        raise EncloseProjectError(
            "cannot merge into %s: top level is not a JSON object" % path)
    return data


def _write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    _write_text(path, json.dumps(data, indent=2) + "\n")


def _tail(text, n=4000):
    text = text or ""
    return text if len(text) <= n else "...(truncated)...\n" + text[-n:]


def _py_str(text):
    """A Python string literal for `text`."""
    return repr(str(text))


def _comment_safe(text):
    return str(text).replace("\r", " ").replace("\n", " ")


# --- FreeCAD export ------------------------------------------------------------

EXPORT_SCRIPT = r'''# Generated by gencad tools/enclose_project.py: export FCStd objects to STEP.
import json
import os

import FreeCAD as App
import Import
import Part

CFG = json.loads(%(cfg)s)


def is_link(obj):
    # App::Link: an instance of another object (the usual way an assembly
    # places a repeated part). It is not a Part::Feature but shows a shape.
    return obj.isDerivedFrom("App::Link")


def local_shape(obj):
    # The object's shape in its parent container's coordinates. A link's
    # shape comes from Part.getShape, which applies the link's own placement.
    if obj.isDerivedFrom("Part::Feature"):
        return obj.Shape
    if is_link(obj):
        return Part.getShape(obj, needSubElement=False, transform=True)
    return None


def shape_kind(obj):
    return obj.isDerivedFrom("Part::Feature") or is_link(obj)


def solid_bearing(obj):
    if not shape_kind(obj):
        return False
    try:
        shape = local_shape(obj)
    except Exception:
        return False
    return shape is not None and (not shape.isNull()) and len(shape.Solids) > 0


def collect_objects(value, names):
    if isinstance(value, (list, tuple)):
        for item in value:
            collect_objects(item, names)
    elif isinstance(value, App.DocumentObject):
        names.add(value.Name)


# Link properties that point at another object without putting it inside
# this one: an attachment reference (a Boss attached to a face of a plate
# leaves the plate a body of its own), and the source of a copy-type object
# (a mirror or a Draft clone is a second body; the original stays).
REFERENCE_PROPS = ("AttachmentSupport", "Support")
COPY_SOURCE_PROPS = {"Part::Mirroring": ("Source",)}
# Draft objects are Part::FeaturePython; their kind is the proxy's Type.
COPY_SOURCE_PROXY_PROPS = {"Clone": ("Objects",)}


def copy_source_props(obj):
    proxy_type = getattr(getattr(obj, "Proxy", None), "Type", None)
    return (COPY_SOURCE_PROPS.get(getattr(obj, "TypeId", ""), ())
            + COPY_SOURCE_PROXY_PROPS.get(proxy_type, ()))


def linked_names(obj):
    # Names of the objects `obj` consumes through a link property (a
    # boolean's Base/Tool, a compound's Links, a Body's Group). An expression
    # that only reads another object's value is not a link property and does
    # not count, and neither does a hidden link (a PartDesign feature's link
    # back to its own Body), a reference in REFERENCE_PROPS, or a copy's
    # source. An App::Link consumes nothing: it shows another instance of
    # its target, and the target stays where it is.
    names = set()
    if is_link(obj):
        return names
    skip = REFERENCE_PROPS + copy_source_props(obj)
    for prop in obj.PropertiesList:
        if prop in skip:
            continue
        try:
            kind = obj.getTypeIdOfProperty(prop)
        except Exception:
            continue
        if (kind.startswith(("App::PropertyLink", "App::PropertyXLink"))
                and "Hidden" not in kind):
            try:
                collect_objects(getattr(obj, prop), names)
            except Exception:
                pass
    return names


def global_shape(obj):
    # The object's shape where the document shows it: the placements of the
    # App::Part containers it sits in are applied, which a plain export of the
    # object alone would drop. The placement is baked into the geometry and
    # the returned shape's own placement is identity: Import.export of a
    # single object does not write the object's placement (FreeCAD 1.1.3), so
    # a placed lone body would land at the origin. transformShape with
    # copy=True keeps planes and cylinders analytic.
    outer = App.Placement()
    group = obj.getParentGeoFeatureGroup()
    while group is not None:
        if group.isDerivedFrom("App::Part"):
            outer = group.Placement.multiply(outer)
        group = group.getParentGeoFeatureGroup()
    base = local_shape(obj)
    placement = outer.multiply(base.Placement)
    shape = base.copy()
    shape.Placement = App.Placement()
    shape.transformShape(placement.toMatrix(), True)
    return shape


def shown(obj):
    # visible where the document shows it: the object and every container
    # above it (a hidden PartDesign Body leaves its tip feature's own
    # Visibility on, and a hidden App::Part hides everything inside it)
    while obj is not None:
        if not getattr(obj, "Visibility", True):
            return False
        obj = obj.getParentGeoFeatureGroup()
    return True


def own_body(obj):
    group = obj.getParentGeoFeatureGroup()
    if group is not None and group.isDerivedFrom("PartDesign::Body"):
        return group
    return None


doc = App.openDocument(CFG["fcstd"])
consumed = []  # [label, [labels of the visible solids holding it]]
if CFG["objects"]:
    chosen = []
    for want in CFG["objects"]:
        obj = doc.getObject(want)
        if obj is None:
            by_label = doc.getObjectsByLabel(want)
            obj = by_label[0] if by_label else None
        if obj is None:
            raise ValueError("no object named %%r in %%s" %% (want, CFG["fcstd"]))
        if not shape_kind(obj):
            raise ValueError("object %%r has type %%s; only Part features and "
                             "App::Link instances can be exported"
                             %% (want, obj.TypeId))
        if not solid_bearing(obj):
            raise ValueError("object %%r has no solids to export" %% want)
        if obj not in chosen:
            chosen.append(obj)
else:
    candidates = [o for o in doc.Objects if solid_bearing(o) and shown(o)]
    links = dict((o.Name, linked_names(o)) for o in candidates)
    # an object another candidate links (a boolean's operand, a Body's
    # feature) is already inside that candidate's shape
    chosen = []
    for o in candidates:
        holders = [c for c in candidates if o.Name in links[c.Name]]
        if not holders:
            chosen.append(o)
        elif holders != [own_body(o)]:
            # a Body's own features (its visible tip) are the Body, so only
            # a solid held by something else is worth reporting
            consumed.append([o.Label, [c.Label for c in holders]])
if not chosen:
    raise ValueError("nothing to export: no visible solid-bearing Part "
                     "objects or links in %%s" %% CFG["fcstd"])
out = CFG["out"]
# export copies placed in document coordinates, from a scratch document so
# each keeps its object's Label as the STEP body name
scratch = App.newDocument("gencad_enclose_export")
copies = []
for i, obj in enumerate(chosen):
    feat = scratch.addObject("Part::Feature", "Export%%d" %% i)
    feat.Shape = global_shape(obj)
    feat.Label = obj.Label
    copies.append(feat)
scratch.recompute()
renamed = [(o.Label, c.Label) for o, c in zip(chosen, copies) if o.Label != c.Label]
if renamed:
    raise RuntimeError("labels changed in the export copy: %%r" %% renamed)
Import.export(copies, out)
App.closeDocument(scratch.Name)
if not os.path.isfile(out) or os.path.getsize(out) == 0:
    raise RuntimeError("STEP export wrote nothing to %%s" %% out)
print(%(labels_tag)r + " " + json.dumps([o.Label for o in chosen]))
print(%(consumed_tag)r + " " + json.dumps(consumed))
print(%(sentinel)r + " " + json.dumps(out))
'''


def export_fcstd(fcstd_path, out_step, objects=None, freecadcmd=None,
                 timeout_s=FREECAD_TIMEOUT_S):
    """Export the solid-bearing objects of an FCStd document into one STEP
    file, one named body per object. Returns (labels, consumed): the
    exported object labels, and for a default selection the visible solids
    left out because another visible solid holds them, as {"label",
    "inside"} dicts.

    FreeCAD writes to a fresh temporary file beside `out_step`, which is
    moved onto `out_step` only once the export is proven good. A failed
    export leaves a STEP already at `out_step` untouched."""
    cmd = freecadcmd or find_freecadcmd()
    if not cmd:
        raise EncloseProjectError(
            "freecadcmd not found - install FreeCAD or set GENCAD_FREECADCMD")
    out_step = os.path.abspath(out_step)
    # .step suffix: FreeCAD picks the export format from the extension
    fd, tmp_step = tempfile.mkstemp(prefix=".gencad-export-", suffix=".step",
                                    dir=os.path.dirname(out_step))
    os.close(fd)
    os.unlink(tmp_step)  # only a file FreeCAD writes now may pass the check
    try:
        labels, consumed = _run_export(cmd, fcstd_path, tmp_step, objects,
                                       timeout_s)
        os.replace(tmp_step, out_step)
    finally:
        if os.path.lexists(tmp_step):
            os.unlink(tmp_step)
    return labels, consumed


def _run_export(cmd, fcstd_path, out_path, objects, timeout_s):
    cfg = {"fcstd": os.path.abspath(fcstd_path),
           "out": out_path,
           "objects": list(objects or [])}
    script = EXPORT_SCRIPT % {"cfg": repr(json.dumps(cfg)),
                              "labels_tag": EXPORT_LABELS,
                              "consumed_tag": EXPORT_CONSUMED,
                              "sentinel": EXPORT_SENTINEL}
    tmpdir = tempfile.mkdtemp(prefix="gencad-enclose-")
    try:
        path = os.path.join(tmpdir, "export_step.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        try:
            proc = subprocess.run([cmd, path], capture_output=True, text=True, errors="replace",
                                  timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise EncloseProjectError(
                "freecadcmd export timed out after %ds" % timeout_s)
        except OSError as e:
            raise EncloseProjectError("cannot run freecadcmd %s: %s" % (cmd, e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    ok_line = EXPORT_SENTINEL + " " + json.dumps(cfg["out"])
    lines = out.splitlines()
    if (proc.returncode != 0 or FREECAD_EXCEPTION in out
            or ok_line not in lines or not os.path.isfile(cfg["out"])):
        raise EncloseProjectError(
            "FreeCAD STEP export of %s failed (exit %d)\n%s"
            % (fcstd_path, proc.returncode, _tail(out)))
    found = {EXPORT_LABELS: [], EXPORT_CONSUMED: []}
    for line in lines:
        for tag in found:
            if line.startswith(tag + " "):
                try:
                    found[tag] = json.loads(line[len(tag) + 1:])
                except ValueError:
                    pass
    consumed = [{"label": c[0], "inside": list(c[1])}
                for c in found[EXPORT_CONSUMED]
                if isinstance(c, list) and len(c) == 2]
    return found[EXPORT_LABELS], consumed


# --- project files -------------------------------------------------------------

def _replace_file(dst, write):
    """Write `dst` through a temp file in its folder and os.replace it into
    place, so a symlink already at `dst` is replaced, never written through."""
    d = os.path.dirname(dst) or "."
    fd, tmp = tempfile.mkstemp(prefix=".gencad-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def _write_text(path, text):
    _replace_file(path, lambda f: f.write(text.encode("utf-8")))


def _copy_file(src, dst):
    def write(f):
        with open(src, "rb") as s:
            shutil.copyfileobj(s, f)
    _replace_file(dst, write)


def _copy_steps(step_paths, source_dir):
    """Copy STEP inputs into source/, keeping basenames; a basename already
    taken by another input of this call gets -2, -3, ... before the suffix.

    Every destination is planned before anything is copied. An input that
    already sits in source/ keeps its own name and is never a destination for
    another input, so no input is overwritten before it is read."""
    real_source = os.path.realpath(source_dir)
    names = [None] * len(step_paths)
    taken = set()
    for i, src in enumerate(step_paths):
        base = os.path.basename(src)
        if (os.path.realpath(os.path.dirname(src)) == real_source
                and base.lower() not in taken):
            names[i] = base
            taken.add(base.lower())
    for i, src in enumerate(step_paths):
        if names[i] is not None:
            continue
        base = os.path.basename(src)
        stem, ext = os.path.splitext(base)
        name, n = base, 1
        while name.lower() in taken:
            n += 1
            name = "%s-%d%s" % (stem, n, ext)
        taken.add(name.lower())
        names[i] = name
    copied = []
    for src, name in zip(step_paths, names):
        dst = os.path.join(source_dir, name)
        in_place = (not os.path.islink(dst) and os.path.exists(dst)
                    and os.path.samefile(src, dst))
        if not in_place:
            _copy_file(src, dst)
        copied.append(dst)
    return copied


def render_model_py(title, source_rel, inputs):
    lines = ["# Scaffolded by gencad (tools/enclose_project.py) from:"]
    lines += ["#   %s" % _comment_safe(i) for i in inputs]
    lines += [
        "#",
        "# Every body in the STEP files below becomes one part, grouped the way",
        "# the files group them. This file is the project's own from here on:",
        "# edit it, then rebuild with the build command in enclose.json.",
        "import re",
        "",
        "from enclose import Model, read_step",
        "",
        "SOURCES = [",
    ]
    lines += ["    %s," % _py_str(s) for s in source_rel]
    lines += [
        "]",
        "",
        "model = Model(%s)" % _py_str(title),
        "groups = {}  # group label -> group id",
        "",
        "",
        "def new_group(label):",
        "    # Group ids must be unique, and labels such as 'parts' and 'Parts'",
        "    # would reduce to the same one: number the repeats.",
        "    base = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_') or 'group'",
        "    gid, n = base, 1",
        "    while gid in groups.values():",
        "        n += 1",
        "        gid = '%s_%d' % (base, n)",
        "    return model.group(label, id=gid)",
        "",
        "",
        "for found in read_step(*SOURCES):",
        "    if found.group not in groups:",
        "        groups[found.group] = new_group(found.group)",
        "    model.part(found.id, found.shape, label=found.label,",
        "               group=groups[found.group], color=found.color)",
        "model.write()",
        "",
    ]
    return "\n".join(lines)


def mcp_server_entry():
    entry = {"command": "python3", "args": [SERVER_PATH]}
    fc = find_freecadcmd()
    if fc:
        entry["env"] = {"GENCAD_FREECADCMD": os.path.abspath(fc)}
    return entry


def _write_mcp_files(out_dir, written):
    mcp_path = os.path.join(out_dir, ".mcp.json")
    mcp = _load_json_object(mcp_path)
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[MCP_SERVER_NAME] = mcp_server_entry()
    mcp["mcpServers"] = servers
    _write_json(mcp_path, mcp)
    written.append(mcp_path)

    settings_path = os.path.join(out_dir, ".claude", "settings.json")
    settings = _load_json_object(settings_path)
    enabled = settings.get("enabledMcpjsonServers")
    if not isinstance(enabled, list):
        enabled = []
    if MCP_SERVER_NAME not in enabled:
        enabled.append(MCP_SERVER_NAME)
    settings["enabledMcpjsonServers"] = enabled
    _write_json(settings_path, settings)
    written.append(settings_path)


def _run_build(build_python, out_dir):
    manifest = os.path.join(out_dir, MANIFEST_REL)
    if os.path.lexists(manifest):
        os.unlink(manifest)  # an old build's manifest must not pass as this one
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        proc = subprocess.run([build_python, "model.py"], cwd=out_dir,
                              capture_output=True, text=True, errors="replace",
                              timeout=BUILD_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        raise EncloseProjectError(
            "build timed out after %ds: %s model.py in %s"
            % (BUILD_TIMEOUT_S, build_python, out_dir))
    except OSError as e:
        raise EncloseProjectError(
            "cannot run build python %s: %s" % (build_python, e))
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise EncloseProjectError(
            "project files were written to %s but the build failed (exit %d): "
            "%s model.py\n%s" % (out_dir, proc.returncode, build_python,
                                 _tail(out)))
    if not os.path.isfile(manifest):
        raise EncloseProjectError(
            "build exited 0 but wrote no manifest at %s\n%s"
            % (manifest, _tail(out)))
    try:
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        parts = data["parts"]
        labels = [p.get("label") or p.get("id") for p in parts]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise EncloseProjectError("unreadable manifest %s: %s" % (manifest, e))
    return manifest, labels


# --- entry point -----------------------------------------------------------------

def make_project(out_dir, step_paths=None, fcstd_path=None, objects=None,
                 name=None, build_python=None, with_mcp=True, overwrite=False,
                 enclose_root=None, freecadcmd=None):
    """Scaffold (and optionally build) an Enclose project in `out_dir`.

    Exactly one of `step_paths` (list of .step/.stp files) or `fcstd_path`
    (a FreeCAD document; `objects` limits the export to those object names or
    labels) is required. Returns a dict with out_dir, source_files,
    files_written, built, parts, manifest, removed_manifest,
    unread_source_files and consumed_objects. Raises EncloseProjectError."""
    if not out_dir:
        raise EncloseProjectError("out_dir is required")
    if isinstance(step_paths, str):
        step_paths = [step_paths]
    step_paths = list(step_paths or [])
    if bool(step_paths) == bool(fcstd_path):
        raise EncloseProjectError(
            "give exactly one input: step_paths or fcstd_path")
    if objects and not fcstd_path:
        raise EncloseProjectError("objects only applies to fcstd_path input")

    out_dir = os.path.abspath(out_dir)
    if step_paths:
        step_paths = [os.path.abspath(p) for p in step_paths]
        for p in step_paths:
            if not os.path.isfile(p):
                raise EncloseProjectError("no such STEP file: %s" % p)
            if not p.lower().endswith(STEP_EXTS):
                raise EncloseProjectError(
                    "not a STEP file (.step/.stp): %s" % p)
        inputs = step_paths
    else:
        fcstd_path = os.path.abspath(fcstd_path)
        if not os.path.isfile(fcstd_path):
            raise EncloseProjectError("no such FreeCAD document: %s" % fcstd_path)
        if not fcstd_path.lower().endswith(".fcstd"):
            raise EncloseProjectError("not a .FCStd document: %s" % fcstd_path)
        inputs = [fcstd_path]

    kit_root = resolve_enclose_root(enclose_root)
    build_cmd, build_exe = _build_command(build_python, out_dir)

    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise EncloseProjectError("out_dir exists and is not a directory: %s"
                                  % out_dir)
    if not overwrite:
        existing = [f for f in ("model.py", "enclose.json")
                    if os.path.lexists(os.path.join(out_dir, f))]
        if existing:
            raise EncloseProjectError(
                "%s already holds an Enclose project (%s); pass overwrite to "
                "replace it" % (out_dir, ", ".join(existing)))
    if with_mcp:  # refuse unmergeable config before writing anything
        _load_json_object(os.path.join(out_dir, ".mcp.json"))
        _load_json_object(os.path.join(out_dir, ".claude", "settings.json"))

    created = not os.path.exists(out_dir)
    consumed = []
    source_dir = os.path.join(out_dir, "source")
    written = []
    try:
        os.makedirs(source_dir, exist_ok=True)
        if fcstd_path:
            stem = os.path.splitext(os.path.basename(fcstd_path))[0]
            step = os.path.join(source_dir, stem + ".step")
            _, consumed = export_fcstd(fcstd_path, step, objects, freecadcmd)
            source_files = [step]
        else:
            source_files = _copy_steps(step_paths, source_dir)
        written.extend(source_files)

        for f in KIT_FILES:
            dst = os.path.join(out_dir, f)
            _copy_file(os.path.join(kit_root, "kit", f), dst)
            written.append(dst)

        title = name or _title_from_stem(inputs[0])
        source_rel = ["source/" + os.path.basename(p) for p in source_files]
        model_path = os.path.join(out_dir, "model.py")
        _write_text(model_path, render_model_py(title, source_rel, inputs))
        written.append(model_path)
        # a manifest already in build/ was built from some other model.py;
        # Enclose would show its parts as this project's, so drop it
        old_manifest = os.path.join(out_dir, MANIFEST_REL)
        removed_manifest = None
        if os.path.lexists(old_manifest):
            os.unlink(old_manifest)
            removed_manifest = old_manifest

        cfg_path = os.path.join(out_dir, "enclose.json")
        _write_json(cfg_path, {"model": MANIFEST_REL, "build": build_cmd})
        written.append(cfg_path)

        gitignore = os.path.join(out_dir, ".gitignore")
        if not os.path.lexists(gitignore):
            _write_text(gitignore, "build/\n.venv/\n")
            written.append(gitignore)

        if with_mcp:
            _write_mcp_files(out_dir, written)
    except BaseException:
        # half a project is no project: drop a folder this call created
        if created:
            shutil.rmtree(out_dir, ignore_errors=True)
        raise

    listed = set(os.path.normcase(os.path.abspath(p)) for p in source_files)
    unread = sorted(
        os.path.join(source_dir, f) for f in os.listdir(source_dir)
        if f.lower().endswith(STEP_EXTS) and not f.startswith(".")
        and os.path.normcase(os.path.join(source_dir, f)) not in listed)
    result = {"out_dir": out_dir, "source_files": source_files,
              "files_written": written, "built": False, "parts": None,
              "manifest": None, "removed_manifest": removed_manifest,
              "unread_source_files": unread,
              "consumed_objects": consumed}
    if build_python:
        manifest, labels = _run_build(build_exe, out_dir)
        result.update(built=True, parts=labels, manifest=manifest)
    return result


def summarize(result):
    lines = ["Enclose project: %s" % result["out_dir"]]
    lines.append("source: %s" % ", ".join(result["source_files"]))
    lines.append("wrote %d files" % len(result["files_written"]))
    if result["built"]:
        lines.append("built %d parts: %s" % (
            len(result["parts"]), ", ".join(str(p) for p in result["parts"])))
        lines.append("manifest: %s" % result["manifest"])
    else:
        lines.append("not built (no build python given): run the build "
                     "command in enclose.json with a Python that has "
                     "build123d, or ask Claude in Enclose to build it. "
                     "Enclose does not build a folder it did not create.")
        if result.get("removed_manifest"):
            lines.append("removed the old manifest %s: it was built from a "
                         "different model.py" % result["removed_manifest"])
    if result.get("consumed_objects"):
        lines.append("left out of the FCStd export because another visible "
                     "solid holds them (pass objects to choose): %s" % "; ".join(
                         "%s (inside %s)" % (c["label"], ", ".join(c["inside"]))
                         for c in result["consumed_objects"]))
    if result.get("unread_source_files"):
        lines.append("model.py does not read these older files in source/: "
                     "%s" % ", ".join(result["unread_source_files"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Scaffold an Enclose project from STEP files or a "
                    "FreeCAD document.")
    ap.add_argument("out_dir", help="project folder to create or fill")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--step", action="append", metavar="F",
                     help="STEP file to bring in (repeatable)")
    src.add_argument("--fcstd", metavar="F",
                     help="FreeCAD document whose solids are exported to STEP")
    ap.add_argument("--object", action="append", metavar="NAME",
                    help="with --fcstd: export only this object (repeatable)")
    ap.add_argument("--name", help="model title (default: input stem)")
    ap.add_argument("--build-python", metavar="PY",
                    help="Python with build123d: run model.py now and "
                         "write it into enclose.json")
    ap.add_argument("--no-mcp", action="store_true",
                    help="do not write .mcp.json / .claude/settings.json")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace an existing model.py / enclose.json")
    a = ap.parse_args(argv)
    if a.object and not a.fcstd:
        ap.error("--object needs --fcstd")
    try:
        result = make_project(
            a.out_dir, step_paths=a.step, fcstd_path=a.fcstd,
            objects=a.object, name=a.name, build_python=a.build_python,
            with_mcp=not a.no_mcp, overwrite=a.overwrite)
    except (EncloseProjectError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    print(summarize(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
