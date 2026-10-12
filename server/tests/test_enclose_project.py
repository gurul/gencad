"""tools/enclose_project.py: scaffold Enclose projects from STEP or FCStd.

No FreeCAD, build123d or Enclose checkout needed. `fake_kit` (conftest.py)
stands in for the Enclose kit, the "build python" is this interpreter running
the scaffolded model.py against that stub, and FCStd export goes through a
fake freecadcmd that runs the real generated export script against stub
FreeCAD / Import modules - with the real freecadcmd's habit of printing
"Exception while processing file" and exiting 0 when the script raises.

Run: uvx --with pytest pytest server/tests -q
"""
import json
import os
import stat
import subprocess
import sys
import textwrap

import pytest

from conftest import step_text

REPO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TOOL = os.path.join(REPO, "tools", "enclose_project.py")
sys.path.insert(0, os.path.join(REPO, "tools"))
import enclose_project as ep  # noqa: E402

FAKE_FREECADCMD = textwrap.dedent('''\
    #!{python}
    """Fake freecadcmd: stub FreeCAD + Import, then run the script."""
    import json, os, runpy, sys, types
    script = sys.argv[1]
    mode = os.environ.get("FAKE_FC_MODE", "")
    if mode == "exit1":
        print("crashed hard")
        sys.exit(1)
    if mode == "silent":
        sys.exit(0)

    spec = json.loads(os.environ.get("FAKE_DOC", "[]"))
    log = os.environ.get("FAKE_FC_LOG")

    class Placement:
        # only a translation along x, enough to see a container's offset
        def __init__(self, x=0):
            self.x = x
        def multiply(self, other):
            return Placement(self.x + other.x)
        def toMatrix(self):
            return ("matrix", self.x)

    class Shape:
        # _baked: an x offset moved into the geometry itself
        def __init__(self, n):
            self.Solids = [object()] * max(n, 0)
            self._null = n < 0
            self._baked = 0
            self.Placement = Placement()
        def isNull(self):
            return self._null
        def copy(self):
            c = Shape(len(self.Solids))
            c._null, c.Placement = self._null, Placement(self.Placement.x)
            c._baked = self._baked
            return c
        def transformShape(self, matrix, copy=False, checkScale=False):
            assert copy is True, "without copy the move stays a placement"
            self._baked += matrix[1]

    class DocumentObject:
        pass

    class Obj(DocumentObject):
        def __init__(self, d, doc):
            self.Name = d["name"]
            self.Label = d.get("label", d["name"])
            self.TypeId = d.get("type", "Part::Feature")
            self.Shape = Shape(d.get("solids", 1))
            self.Shape.Placement = Placement(d.get("x", 0))
            self.Placement = Placement(d.get("x", 0))
            self.Visibility = d.get("visible", True)
            self._in, self._doc = d.get("inlist", []), doc
            self._links = d.get("links", {{}})
            self._parent = d.get("parent")
            if "proxy" in d:  # a Python feature such as a Draft clone
                self.Proxy = types.SimpleNamespace(Type=d["proxy"])
        def isDerivedFrom(self, t):
            if t == "Part::Feature":
                return self.TypeId.startswith("Part")
            return self.TypeId == t
        @property
        def InList(self):
            return [self._doc.getObject(n) for n in self._in]
        @property
        def PropertiesList(self):
            return ["Label", "Placement"] + sorted(self._links)
        def getTypeIdOfProperty(self, prop):
            if prop in self._links:
                v = self._links[prop]
                if prop.startswith("_"):  # as PartDesign's _Body
                    return "App::PropertyLinkHidden"
                return ("App::PropertyLinkList" if isinstance(v, list)
                        else "App::PropertyLink")
            return dict(Label="App::PropertyString",
                        Placement="App::PropertyPlacement")[prop]
        def __getattr__(self, prop):
            links = self.__dict__.get("_links", {{}})
            if prop not in links:
                raise AttributeError(prop)
            v = links[prop]
            if isinstance(v, list):
                return [self._doc.getObject(n) for n in v]
            return self._doc.getObject(v)
        def getParentGeoFeatureGroup(self):
            return self._doc.getObject(self._parent) if self._parent else None

    class Feature:
        def __init__(self, name):
            self.Name, self.Label, self.Shape = name, name, None

    class Doc:
        def __init__(self, spec, name="doc"):
            self.Name = name
            self.Objects = [Obj(d, self) for d in spec]
        def getObject(self, name):
            return next((o for o in self.Objects if o.Name == name), None)
        def getObjectsByLabel(self, label):
            return [o for o in self.Objects if o.Label == label]
        def addObject(self, kind, name):
            assert kind == "Part::Feature", kind
            f = Feature(name)
            self.Objects.append(f)
            return f
        def recompute(self):
            pass

    def openDocument(path):
        assert os.path.isfile(path), path
        return Doc(spec)

    def newDocument(name):
        return Doc([], name)

    def closeDocument(name):
        pass

    def export(objs, path):
        # real Import.export (FreeCAD 1.1.3) drops the placement of a lone
        # object, so only geometry-baked offsets survive a one-body export
        def where(o):
            kept = o.Shape.Placement.x if len(objs) > 1 else 0
            return o.Shape._baked + kept
        if log:
            with open(log, "w") as f:
                json.dump([[o.Label, where(o)] for o in objs], f)
        if mode == "export_nothing":
            return
        with open(path, "w") as f:
            f.write("ISO-10303-21;\\n")
            for o in objs:
                f.write("BODY: %s\\n" % o.Label)
            f.write("END-ISO-10303-21;\\n")

    def getShape(obj, needSubElement=False, transform=True):
        # an App::Link's shape: its target's, moved by the link placement
        assert obj.TypeId == "App::Link", obj.TypeId
        target = obj.LinkedObject
        shape = target.Shape.copy()
        if transform:
            shape.Placement = obj.Placement.multiply(target.Shape.Placement)
        return shape

    fc = types.ModuleType("FreeCAD")
    fc.openDocument, fc.newDocument = openDocument, newDocument
    fc.closeDocument, fc.Placement = closeDocument, Placement
    fc.DocumentObject = DocumentObject
    imp = types.ModuleType("Import"); imp.export = export
    part = types.ModuleType("Part"); part.getShape = getShape
    sys.modules["FreeCAD"], sys.modules["Import"] = fc, imp
    sys.modules["Part"] = part
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        sys.exit(e.code if isinstance(e.code, int) else 1)
    except BaseException as e:
        # real freecadcmd 1.1.3: prints this and exits 0
        print("Exception while processing file: %s [%s]" % (script, e))
    sys.exit(0)
''')


@pytest.fixture
def fake_fc(tmp_path, monkeypatch):
    fake = tmp_path / "freecadcmd"
    fake.write_text(FAKE_FREECADCMD.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("FAKE_FC_MODE", raising=False)
    return str(fake)


def set_doc(monkeypatch, objs):
    monkeypatch.setenv("FAKE_DOC", json.dumps(objs))


@pytest.fixture
def fcstd(tmp_path):
    p = tmp_path / "pair.FCStd"
    p.write_bytes(b"PK fake fcstd")
    return str(p)


@pytest.fixture
def step(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    p = d / "widget_box.step"
    p.write_text(step_text("Base plate", "Post"))
    return str(p)


def make(out, kit, **kw):
    return ep.make_project(str(out), enclose_root=str(kit), **kw)


# --- STEP input ------------------------------------------------------------

def test_step_scaffold_without_build(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=[step])
    assert res["out_dir"] == str(out)
    assert res["built"] is False and res["parts"] is None
    assert res["manifest"] is None
    assert res["source_files"] == [str(out / "source" / "widget_box.step")]
    assert (out / "source" / "widget_box.step").read_text() == open(step).read()
    for f in ("enclose.py", "screws.py", "model.py", "enclose.json",
              ".gitignore", ".mcp.json", ".claude/settings.json"):
        assert (out / f).is_file(), f
        assert str(out / f) in res["files_written"], f
    assert (out / "enclose.py").read_text() == \
        (fake_kit / "kit" / "enclose.py").read_text()
    cfg = json.loads((out / "enclose.json").read_text())
    assert cfg == {"model": "build/enclose.model.json",
                   "build": "python3 model.py"}
    gi = (out / ".gitignore").read_text().split()
    assert "build/" in gi and ".venv/" in gi
    model = (out / "model.py").read_text()
    compile(model, "model.py", "exec")
    assert model.startswith("# Scaffolded by gencad")
    assert step in model
    assert "'source/widget_box.step'" in model
    assert "Model('Widget Box')" in model
    assert "read_step" in model


def test_step_build_returns_parts(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=[step], name="Pair",
               build_python=sys.executable)
    assert res["built"] is True
    assert res["parts"] == ["Base plate", "Post"]
    assert res["manifest"] == str(out / "build" / "enclose.model.json")
    man = json.loads(open(res["manifest"]).read())
    assert man["title"] == "Pair"
    cfg = json.loads((out / "enclose.json").read_text())
    assert cfg["build"] == "%s model.py" % ep.shlex.quote(sys.executable)


def test_build_python_inside_out_dir_written_relative(tmp_path, fake_kit,
                                                      step):
    out = tmp_path / "proj"
    venv_bin = out / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    py = venv_bin / "python"
    py.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
    py.chmod(0o755)
    res = make(out, fake_kit, step_paths=[step], build_python=str(py))
    assert res["built"] and res["parts"] == ["Base plate", "Post"]
    cfg = json.loads((out / "enclose.json").read_text())
    assert cfg["build"] == ".venv/bin/python model.py"


def test_build_python_outside_with_space_is_absolute_and_quoted(
        tmp_path, fake_kit, step):
    d = tmp_path / "my envs" / "bin"
    d.mkdir(parents=True)
    py = d / "python"
    py.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
    py.chmod(0o755)
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=[step], build_python=str(py))
    assert res["built"]
    cfg = json.loads((out / "enclose.json").read_text())
    assert cfg["build"] == "'%s' model.py" % py
    assert os.path.isabs(str(py))


def test_missing_build_python_is_error_and_writes_nothing(tmp_path, fake_kit,
                                                          step):
    out = tmp_path / "proj"
    with pytest.raises(ep.EncloseProjectError, match="no such build python"):
        make(out, fake_kit, step_paths=[step],
             build_python=str(tmp_path / "nope" / "python"))
    assert not out.exists()


def test_build_failure_reports_tail_and_keeps_files(tmp_path, fake_kit):
    bad = tmp_path / "bad.step"
    bad.write_text(step_text("X", broken=True))
    out = tmp_path / "proj"
    with pytest.raises(ep.EncloseProjectError) as e:
        make(out, fake_kit, step_paths=[str(bad)],
             build_python=sys.executable)
    assert "build failed" in str(e.value)
    assert "could not be read as a STEP file" in str(e.value)
    assert (out / "model.py").is_file()


def test_build_without_manifest_is_error_even_with_stale_one(
        tmp_path, fake_kit, step, monkeypatch):
    out = tmp_path / "proj"
    make(out, fake_kit, step_paths=[step], build_python=sys.executable)
    assert (out / "build" / "enclose.model.json").is_file()
    monkeypatch.setenv("STUB_BUILD_NO_MANIFEST", "1")
    with pytest.raises(ep.EncloseProjectError, match="no manifest"):
        make(out, fake_kit, step_paths=[step], build_python=sys.executable,
             overwrite=True)


# --- refuse / overwrite ------------------------------------------------------

def test_overwrite_without_build_drops_old_manifest(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    make(out, fake_kit, step_paths=[step], build_python=sys.executable)
    manifest = out / "build" / "enclose.model.json"
    assert manifest.is_file()
    other = tmp_path / "other.step"
    other.write_text(step_text("Lid"))
    res = make(out, fake_kit, step_paths=[str(other)], overwrite=True)
    assert not res["built"]
    assert not manifest.exists()
    assert res["removed_manifest"] == str(manifest)
    assert "removed the old manifest" in ep.summarize(res)


def test_fresh_project_reports_no_removed_manifest(tmp_path, fake_kit, step):
    res = make(tmp_path / "proj", fake_kit, step_paths=[step])
    assert res["removed_manifest"] is None
    assert res["unread_source_files"] == []
    assert "older files" not in ep.summarize(res)


def test_older_source_files_are_reported_not_read(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    (out / "source").mkdir(parents=True)
    old = out / "source" / "old.step"
    old.write_text(step_text("Old"))
    res = make(out, fake_kit, step_paths=[step], build_python=sys.executable)
    assert res["unread_source_files"] == [str(old)]
    assert "source/old.step" not in (out / "model.py").read_text()
    assert res["parts"] == ["Base plate", "Post"]
    assert "does not read these older files" in ep.summarize(res)
    assert str(old) in ep.summarize(res)

@pytest.mark.parametrize("existing", ["model.py", "enclose.json"])
def test_refuses_existing_project_unless_overwrite(tmp_path, fake_kit, step,
                                                   existing):
    out = tmp_path / "proj"
    out.mkdir()
    (out / existing).write_text("mine\n")
    with pytest.raises(ep.EncloseProjectError, match="overwrite"):
        make(out, fake_kit, step_paths=[step])
    assert (out / existing).read_text() == "mine\n"
    assert not (out / "source").exists()
    res = make(out, fake_kit, step_paths=[step], overwrite=True)
    assert (out / existing).read_text() != "mine\n"
    assert res["source_files"]


def test_existing_folder_without_project_is_filled(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    out.mkdir()
    (out / "notes.txt").write_text("keep")
    make(out, fake_kit, step_paths=[step])
    assert (out / "notes.txt").read_text() == "keep"
    assert (out / "model.py").is_file()


def test_existing_gitignore_left_alone(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    out.mkdir()
    (out / ".gitignore").write_text("custom\n")
    res = make(out, fake_kit, step_paths=[step])
    assert (out / ".gitignore").read_text() == "custom\n"
    assert str(out / ".gitignore") not in res["files_written"]


# --- collisions ----------------------------------------------------------------

def test_basename_collisions_are_deduped(tmp_path, fake_kit):
    paths = []
    for sub, label in (("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")):
        d = tmp_path / sub
        d.mkdir()
        p = d / ("part.STEP" if sub == "c" else "part.step")
        p.write_text(step_text(label))
        paths.append(str(p))
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=paths, build_python=sys.executable)
    names = [os.path.basename(p) for p in res["source_files"]]
    assert names == ["part.step", "part-2.step", "part-3.STEP"]
    for p, src in zip(res["source_files"], paths):
        assert open(p).read() == open(src).read()
    model = (out / "model.py").read_text()
    for n in names:
        assert "'source/%s'" % n in model
    assert res["parts"] == ["Alpha", "Beta", "Gamma"]


def test_group_labels_that_slug_alike_get_unique_ids(tmp_path, fake_kit):
    # 'parts' (a multi-body file's stem) and 'Parts' (the kit's default) and
    # two labels that differ only in punctuation all reduce to one slug
    d = tmp_path / "in"
    d.mkdir()
    a = d / "parts.step"
    a.write_text(step_text("Alpha @ parts", "Beta @ Parts", "Gamma @ Parts!",
                           "Delta @ üü", "Eps @ ïï"))
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=[str(a)], build_python=sys.executable)
    man = json.loads(open(res["manifest"]).read())
    ids = [g["id"] for g in man["groups"]]
    assert ids == ["parts", "parts_2", "parts_3", "group", "group_2"]
    assert [g["label"] for g in man["groups"]] == [
        "parts", "Parts", "Parts!", "üü", "ïï"]
    assert [p["group"] for p in man["parts"]] == ids


def test_stub_kit_rejects_duplicate_group_ids(tmp_path, fake_kit):
    # positive control: the stub fails the way the real kit does
    script = tmp_path / "dup.py"
    script.write_text("import sys; sys.path.insert(0, %r)\n"
                      "from enclose import Model\n"
                      "m = Model('x'); m.group('parts'); m.group('Parts')\n"
                      % str(fake_kit / "kit"))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True)
    assert proc.returncode != 0
    assert 'two groups share the id "parts"' in proc.stderr


def test_input_already_in_source_is_not_overwritten(tmp_path, fake_kit):
    out = tmp_path / "proj"
    (out / "source").mkdir(parents=True)
    inside = out / "source" / "a.step"
    inside.write_text(step_text("Original"))
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.step").write_text(step_text("Other"))
    res = make(out, fake_kit, step_paths=[str(other / "a.step"), str(inside)],
               build_python=sys.executable)
    names = [os.path.basename(p) for p in res["source_files"]]
    assert names == ["a-2.step", "a.step"]
    assert inside.read_text() == step_text("Original")
    assert (out / "source" / "a-2.step").read_text() == step_text("Other")
    assert res["parts"] == ["Other", "Original"]


def test_symlinks_in_out_dir_are_replaced_not_followed(tmp_path, fake_kit):
    keep = tmp_path / "keep"
    keep.mkdir()
    for f in ("a.step", "model.py", "enclose.py", "gitignore"):
        (keep / f).write_text("KEEP-ME")
    out = tmp_path / "proj"
    (out / "source").mkdir(parents=True)
    os.symlink(str(keep / "a.step"), str(out / "source" / "a.step"))
    os.symlink(str(keep / "model.py"), str(out / "model.py"))
    os.symlink(str(keep / "enclose.py"), str(out / "enclose.py"))
    new = tmp_path / "new"
    new.mkdir()
    (new / "a.step").write_text(step_text("New"))
    res = make(out, fake_kit, step_paths=[str(new / "a.step")],
               overwrite=True, build_python=sys.executable)
    for f in ("a.step", "model.py", "enclose.py"):
        assert (keep / f).read_text() == "KEEP-ME", f
    for p in (out / "source" / "a.step", out / "model.py", out / "enclose.py"):
        assert not os.path.islink(str(p)), p
    assert (out / "source" / "a.step").read_text() == step_text("New")
    assert res["parts"] == ["New"]


def test_unbuilt_summary_does_not_promise_an_automatic_build(tmp_path,
                                                            fake_kit, step):
    res = make(tmp_path / "proj", fake_kit, step_paths=[step])
    text = ep.summarize(res)
    assert "not built" in text
    assert "run the build command in enclose.json" in text
    assert "when it opens the folder" not in text


# --- MCP config files -------------------------------------------------------

def test_mcp_files_merge_with_existing(tmp_path, fake_kit, step,
                                       monkeypatch):
    monkeypatch.setenv("GENCAD_FREECADCMD", sys.executable)
    out = tmp_path / "proj"
    (out / ".claude").mkdir(parents=True)
    (out / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"other": {"command": "x"},
                        "gencad": {"command": "stale"}},
         "extra": 1}))
    (out / ".claude" / "settings.json").write_text(json.dumps(
        {"model": "opus", "enabledMcpjsonServers": ["other"]}))
    make(out, fake_kit, step_paths=[step])
    mcp = json.loads((out / ".mcp.json").read_text())
    assert mcp["extra"] == 1
    assert mcp["mcpServers"]["other"] == {"command": "x"}
    g = mcp["mcpServers"]["gencad"]
    assert g["command"] == "python3"
    assert g["args"] == [os.path.join(REPO, "server", "gencad_mcp.py")]
    assert os.path.isabs(g["args"][0])
    assert g["env"] == {"GENCAD_FREECADCMD": sys.executable}
    settings = json.loads((out / ".claude" / "settings.json").read_text())
    assert settings["model"] == "opus"
    assert settings["enabledMcpjsonServers"] == ["other", "gencad"]
    # a second scaffold does not duplicate the entry
    make(out, fake_kit, step_paths=[step], overwrite=True)
    settings = json.loads((out / ".claude" / "settings.json").read_text())
    assert settings["enabledMcpjsonServers"] == ["other", "gencad"]


def test_mcp_env_omitted_when_freecadcmd_unresolvable(tmp_path, fake_kit,
                                                      step, monkeypatch):
    monkeypatch.setattr(ep, "find_freecadcmd", lambda: None)
    out = tmp_path / "proj"
    make(out, fake_kit, step_paths=[step])
    g = json.loads((out / ".mcp.json").read_text())["mcpServers"]["gencad"]
    assert "env" not in g


def test_no_mcp_writes_no_mcp_files(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    make(out, fake_kit, step_paths=[step], with_mcp=False)
    assert not (out / ".mcp.json").exists()
    assert not (out / ".claude").exists()


def test_unmergeable_mcp_json_refused_before_writing(tmp_path, fake_kit,
                                                     step):
    out = tmp_path / "proj"
    out.mkdir()
    (out / ".mcp.json").write_text("{not json")
    with pytest.raises(ep.EncloseProjectError, match="not valid JSON"):
        make(out, fake_kit, step_paths=[step])
    assert not (out / "model.py").exists()
    assert (out / ".mcp.json").read_text() == "{not json"


# --- kit resolution ------------------------------------------------------------

def test_missing_kit_says_how_to_fix(tmp_path, step):
    empty = tmp_path / "empty-enclose"
    empty.mkdir()
    out = tmp_path / "proj"
    with pytest.raises(ep.EncloseProjectError) as e:
        make(out, empty, step_paths=[step])
    assert "git submodule update --init enclose" in str(e.value)
    assert not out.exists()


def test_kit_missing_screws_is_error(tmp_path, fake_kit, step):
    (fake_kit / "kit" / "screws.py").unlink()
    with pytest.raises(ep.EncloseProjectError, match="kit/screws.py"):
        make(tmp_path / "proj", fake_kit, step_paths=[step])


def test_enclose_root_from_env(tmp_path, fake_kit, step, monkeypatch):
    monkeypatch.setenv("GENCAD_ENCLOSE_ROOT", str(fake_kit))
    out = tmp_path / "proj"
    ep.make_project(str(out), step_paths=[step])
    assert (out / "enclose.py").read_text() == \
        (fake_kit / "kit" / "enclose.py").read_text()


def test_default_enclose_root_is_repo_submodule(monkeypatch):
    monkeypatch.delenv("GENCAD_ENCLOSE_ROOT", raising=False)
    sub = os.path.join(REPO, "enclose")
    if os.path.isfile(os.path.join(sub, "kit", "enclose.py")):
        assert ep.resolve_enclose_root() == sub
    else:
        with pytest.raises(ep.EncloseProjectError, match="submodule"):
            ep.resolve_enclose_root()


# --- input validation ------------------------------------------------------------

def test_both_inputs_is_error(tmp_path, fake_kit, step, fcstd):
    with pytest.raises(ep.EncloseProjectError, match="exactly one"):
        make(tmp_path / "proj", fake_kit, step_paths=[step],
             fcstd_path=fcstd)
    assert not (tmp_path / "proj").exists()


@pytest.mark.parametrize("kw", [{}, {"step_paths": []},
                                {"step_paths": None, "fcstd_path": ""}])
def test_no_input_is_error(tmp_path, fake_kit, kw):
    with pytest.raises(ep.EncloseProjectError, match="exactly one"):
        make(tmp_path / "proj", fake_kit, **kw)


def test_objects_without_fcstd_is_error(tmp_path, fake_kit, step):
    with pytest.raises(ep.EncloseProjectError, match="objects"):
        make(tmp_path / "proj", fake_kit, step_paths=[step], objects=["A"])


def test_missing_and_non_step_inputs_are_errors(tmp_path, fake_kit):
    with pytest.raises(ep.EncloseProjectError, match="no such STEP"):
        make(tmp_path / "proj", fake_kit,
             step_paths=[str(tmp_path / "nope.step")])
    txt = tmp_path / "part.stl"
    txt.write_text("solid")
    with pytest.raises(ep.EncloseProjectError, match="not a STEP"):
        make(tmp_path / "proj", fake_kit, step_paths=[str(txt)])
    with pytest.raises(ep.EncloseProjectError, match="no such FreeCAD"):
        make(tmp_path / "proj", fake_kit,
             fcstd_path=str(tmp_path / "nope.FCStd"))
    assert not (tmp_path / "proj").exists()


# --- FCStd input via fake freecadcmd ------------------------------------------

DOC = [
    {"name": "Base", "label": "Base plate"},
    {"name": "Post", "label": "Post"},
    {"name": "Blk", "inlist": ["Cut"]},                 # boolean operand
    {"name": "Hole", "inlist": ["Cut"]},                # boolean operand
    {"name": "Cut", "label": "Drilled block",
     "links": {"Base": "Blk", "Tool": "Hole"}},
    {"name": "Hidden", "visible": False},
    {"name": "Sketch", "type": "Part::Part2DObjectPython", "solids": 0},
    {"name": "Null", "solids": -1},
    {"name": "Group", "type": "App::DocumentObjectGroup"},
]


def test_fcstd_default_selection(tmp_path, fake_kit, fake_fc, fcstd,
                                 monkeypatch):
    set_doc(monkeypatch, DOC)
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    step = out / "source" / "pair.step"
    assert res["source_files"] == [str(step)]
    assert step.read_text() == step_text("Base plate", "Post",
                                         "Drilled block")
    assert res["parts"] == ["Base plate", "Post", "Drilled block"]
    man = json.loads(open(res["manifest"]).read())
    assert man["title"] == "Pair"
    assert fcstd in (out / "model.py").read_text()


def test_fcstd_expression_dependency_is_not_consumption(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    # Driven reads Src's length through an expression: Src is in Driven's
    # InList-relationship but no link property holds it, so both export.
    set_doc(monkeypatch, [
        {"name": "Src", "label": "Boîte \"q\" ünï", "inlist": ["Driven"]},
        {"name": "Driven"},
        {"name": "C1", "inlist": ["Cut"]},
        {"name": "C2", "inlist": ["Cut"]},
        {"name": "Cut", "label": "Holed", "links": {"Base": "C1", "Tool": "C2"}},
        {"name": "Fused", "inlist": ["Comp"]},
        {"name": "Comp", "label": "Compound",
         "links": {"Links": ["Fused"]}},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Boîte \"q\" ünï", "Driven", "Holed", "Compound"]


def test_fcstd_hidden_back_link_does_not_drop_a_body(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    # a PartDesign Pad links its Body back through a hidden _Body link; the
    # Body holds the Pad in its Group. Only the Body is exported.
    set_doc(monkeypatch, [
        {"name": "Body", "label": "Bracket", "type": "PartDesign::Body",
         "links": {"Group": ["Pad"], "Tip": "Pad"}, "inlist": ["Pad"]},
        {"name": "Pad", "type": "PartDesign::Pad",
         "links": {"_Body": "Body"}, "inlist": ["Body"]},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Bracket"]


def test_fcstd_body_feature_is_not_reported_as_left_out(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    # the visible tip of an ordinary Body is the Body: no consumed entry
    set_doc(monkeypatch, [
        {"name": "Body", "label": "Bracket", "type": "PartDesign::Body",
         "links": {"Group": ["Pad"], "Tip": "Pad"}, "inlist": ["Pad"]},
        {"name": "Pad", "type": "PartDesign::Pad", "parent": "Body",
         "links": {"_Body": "Body"}, "inlist": ["Body"]},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc)
    assert res["consumed_objects"] == []


def test_fcstd_hidden_container_hides_what_is_inside(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    # a hidden Body leaves its tip's own Visibility on; a hidden App::Part
    # hides its children the same way. Neither is exported.
    set_doc(monkeypatch, [
        {"name": "Body", "label": "Old bracket", "type": "PartDesign::Body",
         "visible": False, "links": {"Group": ["Pad"], "Tip": "Pad"},
         "inlist": ["Pad"]},
        {"name": "Pad", "type": "PartDesign::Pad", "parent": "Body",
         "links": {"_Body": "Body"}, "inlist": ["Body"]},
        {"name": "Asm", "type": "App::Part", "solids": 0, "visible": False},
        {"name": "Inner", "parent": "Asm"},
        {"name": "Loose"},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Loose"]


def test_fcstd_container_placement_is_applied(tmp_path, fake_kit, fake_fc,
                                              fcstd, monkeypatch):
    log = tmp_path / "export-log.json"
    monkeypatch.setenv("FAKE_FC_LOG", str(log))
    set_doc(monkeypatch, [
        {"name": "Outer", "type": "App::Part", "x": 1000, "solids": 0},
        {"name": "Asm", "type": "App::Part", "x": 500, "solids": 0,
         "parent": "Outer"},
        {"name": "Inner", "x": 7, "parent": "Asm"},
        {"name": "Loose", "x": 3},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Inner", "Loose"]
    assert json.loads(log.read_text()) == [["Inner", 1507], ["Loose", 3]]


def test_fcstd_lone_placed_body_keeps_its_placement(tmp_path, fake_kit,
                                                   fake_fc, fcstd, monkeypatch):
    # one body in a moved App::Part: a one-object Import.export drops the
    # feature placement, so the offset must be in the geometry
    log = tmp_path / "export-log.json"
    monkeypatch.setenv("FAKE_FC_LOG", str(log))
    set_doc(monkeypatch, [
        {"name": "Asm", "type": "App::Part", "x": 200, "solids": 0},
        {"name": "Body", "x": 100, "parent": "Asm"},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc)
    assert json.loads(log.read_text()) == [["Body", 300]]
    assert res["consumed_objects"] == []


def test_fcstd_attachment_and_mirror_source_are_not_consumption(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    set_doc(monkeypatch, [
        {"name": "Box1", "label": "Base plate"},
        {"name": "Cyl", "label": "Boss",
         "links": {"AttachmentSupport": ["Box1"]}},
        {"name": "Box3", "label": "Lone"},
        {"name": "Mir", "label": "Mirrored", "type": "Part::Mirroring",
         "links": {"Source": "Box3"}},
        {"name": "Off", "label": "Offset", "type": "Part::Offset",
         "links": {"Source": "Box3b"}},
        {"name": "Box3b", "label": "Offset source"},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Base plate", "Boss", "Lone", "Mirrored",
                            "Offset"]
    # an offset's Source is consumed, and the result says so
    assert res["consumed_objects"] == [
        {"label": "Offset source", "inside": ["Offset"]}]
    assert "Offset source (inside Offset)" in ep.summarize(res)


def test_fcstd_draft_clone_source_is_not_consumption(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    # a Draft clone is a Part::FeaturePython whose Objects link names its
    # original; the original stays a body of its own beside the clone
    set_doc(monkeypatch, [
        {"name": "Orig"},
        {"name": "Clone", "label": "TheClone", "type": "Part::FeaturePython",
         "proxy": "Clone", "links": {"Objects": ["Orig"]}, "x": 30},
        {"name": "Blk", "inlist": ["Arr"]},
        {"name": "Arr", "label": "Array", "type": "Part::FeaturePython",
         "proxy": "Array", "links": {"Base": "Blk"}},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Orig", "TheClone", "Array"]
    # only the clone's source is exempt: an array's Base still counts
    assert res["consumed_objects"] == [{"label": "Blk", "inside": ["Array"]}]


def test_fcstd_app_links_are_exported_and_consume_nothing(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    log = tmp_path / "export-log.json"
    monkeypatch.setenv("FAKE_FC_LOG", str(log))
    set_doc(monkeypatch, [
        {"name": "Lone"},
        {"name": "LinkToLone", "type": "App::Link", "x": 100,
         "links": {"LinkedObject": "Lone"}},
        {"name": "Asm", "type": "App::Part", "x": 50, "solids": 0},
        {"name": "LinkInAsm", "type": "App::Link", "x": 5, "parent": "Asm",
         "links": {"LinkedObject": "Lone"}},
        {"name": "Empty", "type": "App::Link", "solids": 0,
         "links": {"LinkedObject": "Asm"}},
    ])
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               build_python=sys.executable)
    assert res["parts"] == ["Lone", "LinkToLone", "LinkInAsm"]
    assert res["consumed_objects"] == []
    # each link lands at its own placement, inside its container's
    assert json.loads(log.read_text()) == [
        ["Lone", 0], ["LinkToLone", 100], ["LinkInAsm", 55]]


def test_fcstd_explicit_link_and_unsupported_type(tmp_path, fake_kit,
                                                  fake_fc, fcstd, monkeypatch):
    set_doc(monkeypatch, [
        {"name": "Lone"},
        {"name": "LinkToLone", "type": "App::Link", "x": 100,
         "links": {"LinkedObject": "Lone"}},
        {"name": "Asm", "type": "App::Part", "solids": 0},
    ])
    res = make(tmp_path / "a", fake_kit, fcstd_path=fcstd,
               freecadcmd=fake_fc, objects=["LinkToLone"],
               build_python=sys.executable)
    assert res["parts"] == ["LinkToLone"]
    with pytest.raises(ep.EncloseProjectError,
                       match="has type App::Part; only Part features"):
        make(tmp_path / "b", fake_kit, fcstd_path=fcstd,
             freecadcmd=fake_fc, objects=["Asm"])


def test_fcstd_explicit_objects_by_name_or_label(tmp_path, fake_kit, fake_fc,
                                                 fcstd, monkeypatch):
    set_doc(monkeypatch, DOC)
    out = tmp_path / "proj"
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               objects=["Hidden", "Drilled block", "Hidden"],
               build_python=sys.executable)
    assert res["parts"] == ["Hidden", "Drilled block"]


def test_fcstd_script_exception_exit0_is_error(tmp_path, fake_kit, fake_fc,
                                               fcstd, monkeypatch):
    set_doc(monkeypatch, DOC)
    out = tmp_path / "proj"
    with pytest.raises(ep.EncloseProjectError) as e:
        make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
             objects=["NoSuchThing"])
    msg = str(e.value)
    assert "Exception while processing file" in msg
    assert "NoSuchThing" in msg
    assert not out.exists()  # a folder this call made is removed again


def test_fcstd_object_without_solids_is_error(tmp_path, fake_kit, fake_fc,
                                              fcstd, monkeypatch):
    set_doc(monkeypatch, DOC)
    with pytest.raises(ep.EncloseProjectError, match="no solids"):
        make(tmp_path / "proj", fake_kit, fcstd_path=fcstd,
             freecadcmd=fake_fc, objects=["Sketch"])


def test_fcstd_nothing_to_export_is_error(tmp_path, fake_kit, fake_fc,
                                          fcstd, monkeypatch):
    set_doc(monkeypatch, [{"name": "Sketch", "solids": 0}])
    with pytest.raises(ep.EncloseProjectError, match="nothing to export"):
        make(tmp_path / "proj", fake_kit, fcstd_path=fcstd,
             freecadcmd=fake_fc)


@pytest.mark.parametrize("mode", ["silent", "exit1", "export_nothing"])
def test_fcstd_export_without_sentinel_or_file_is_error(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch, mode):
    set_doc(monkeypatch, DOC)
    monkeypatch.setenv("FAKE_FC_MODE", mode)
    out = tmp_path / "proj"
    out.mkdir()
    (out / "source").mkdir()
    stale = out / "source" / "pair.step"
    stale.write_text(step_text("Stale"))
    with pytest.raises(ep.EncloseProjectError, match="export"):
        make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc)
    # the old export is kept as it was, never reported as a fresh one, and
    # no temporary export file is left behind
    assert stale.read_text() == step_text("Stale")
    assert os.listdir(str(out / "source")) == ["pair.step"]
    assert not (out / "model.py").exists()
    assert out.exists()            # a folder the caller had is kept


def test_fcstd_failed_overwrite_keeps_the_project(
        tmp_path, fake_kit, fake_fc, fcstd, monkeypatch):
    set_doc(monkeypatch, DOC)
    out = tmp_path / "proj"
    make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
         build_python=sys.executable)
    before = {f: (out / f).read_bytes()
              for f in ("source/pair.step", "model.py", "enclose.json",
                        "build/enclose.model.json")}
    with pytest.raises(ep.EncloseProjectError, match="Nope"):
        make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
             objects=["Nope"], overwrite=True)
    for f, data in before.items():
        assert (out / f).read_bytes() == data, f
    assert os.listdir(str(out / "source")) == ["pair.step"]


def test_fcstd_export_replaces_old_step(tmp_path, fake_kit, fake_fc, fcstd,
                                        monkeypatch):
    set_doc(monkeypatch, DOC)
    out = tmp_path / "proj"
    (out / "source").mkdir(parents=True)
    old = out / "source" / "pair.step"
    old.write_text(step_text("Stale"))
    res = make(out, fake_kit, fcstd_path=fcstd, freecadcmd=fake_fc,
               objects=["Post"])
    assert res["source_files"] == [str(old)]
    assert "BODY: Post" in old.read_text()
    assert os.listdir(str(out / "source")) == ["pair.step"]


def test_fcstd_without_freecadcmd_is_error(tmp_path, fake_kit, fcstd,
                                           monkeypatch):
    monkeypatch.setattr(ep, "find_freecadcmd", lambda: None)
    with pytest.raises(ep.EncloseProjectError, match="freecadcmd not found"):
        make(tmp_path / "proj", fake_kit, fcstd_path=fcstd)


# --- CLI ---------------------------------------------------------------------

def run_cli(args, kit, extra_env=None):
    env = dict(os.environ, GENCAD_ENCLOSE_ROOT=str(kit))
    env.update(extra_env or {})
    return subprocess.run([sys.executable, TOOL] + args, capture_output=True,
                          text=True, env=env, timeout=120)


def test_cli_step_build(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    p = run_cli([str(out), "--step", step, "--name", "CLI",
                 "--build-python", sys.executable, "--no-mcp"], fake_kit)
    assert p.returncode == 0, p.stderr
    assert "built 2 parts: Base plate, Post" in p.stdout
    assert not (out / ".mcp.json").exists()
    man = json.loads((out / "build" / "enclose.model.json").read_text())
    assert man["title"] == "CLI"


def test_cli_refuse_then_overwrite(tmp_path, fake_kit, step):
    out = tmp_path / "proj"
    assert run_cli([str(out), "--step", step], fake_kit).returncode == 0
    p = run_cli([str(out), "--step", step], fake_kit)
    assert p.returncode == 1 and "overwrite" in p.stderr
    p = run_cli([str(out), "--step", step, "--overwrite"], fake_kit)
    assert p.returncode == 0, p.stderr


def test_cli_fcstd_with_objects(tmp_path, fake_kit, fake_fc, fcstd):
    out = tmp_path / "proj"
    p = run_cli([str(out), "--fcstd", fcstd, "--object", "Post",
                 "--build-python", sys.executable], fake_kit,
                {"GENCAD_FREECADCMD": fake_fc, "FAKE_DOC": json.dumps(DOC)})
    assert p.returncode == 0, p.stderr
    assert "built 1 parts: Post" in p.stdout


@pytest.mark.parametrize("args", [
    [],                                      # no out_dir
    ["OUT"],                                 # no input
    ["OUT", "--step", "a.step", "--fcstd", "b.FCStd"],
    ["OUT", "--step", "a.step", "--object", "X"],
])
def test_cli_usage_errors(tmp_path, fake_kit, args):
    args = [str(tmp_path / a) if a == "OUT" else a for a in args]
    p = run_cli(args, fake_kit)
    assert p.returncode == 2


def test_unicode_and_quote_title_round_trips(tmp_path, fake_kit, step):
    title = 'Lid screws, M3 × 8 "it\'s"'
    out = tmp_path / "proj"
    res = make(out, fake_kit, step_paths=[step], name=title,
               build_python=sys.executable)
    man = json.loads(open(res["manifest"], encoding="utf-8").read())
    assert man["title"] == title


# --- real FreeCAD (skipped when freecadcmd is absent) --------------------------

REAL_FC = ep.find_freecadcmd()

REAL_DOC_SCRIPT = '''
import FreeCAD as App
import Part
doc = App.newDocument("real")
asm = doc.addObject("App::Part", "Asm")
asm.Placement = App.Placement(App.Vector(0, 200, 0), App.Rotation())
box = doc.addObject("Part::Box", "Box")
box.Length, box.Width, box.Height = 10, 20, 30
box.Placement = App.Placement(App.Vector(100, 0, 0),
                              App.Rotation(App.Vector(0, 0, 1), 90))
asm.addObject(box)
doc.recompute()
doc.saveAs(%r)

doc2 = App.newDocument("att")
plate = doc2.addObject("Part::Box", "Plate")
boss = doc2.addObject("Part::Cylinder", "Boss")
boss.Radius, boss.Height = 2, 5
boss.AttachmentSupport = [(plate, "Face6")]
boss.MapMode = "FlatFace"
doc2.recompute()
doc2.saveAs(%r)
print("REAL_DOCS_OK")
'''

READ_BACK_SCRIPT = '''
import json
import Part
s = Part.read(%r)
b = s.BoundBox
print("READBACK " + json.dumps([len(s.Solids), b.XMin, b.YMin, b.ZMin,
                                b.XMax, b.YMax, b.ZMax]))
'''


def _run_fc(tmp_path, name, script):
    path = tmp_path / name
    path.write_text(script)
    proc = subprocess.run([REAL_FC, str(path)], capture_output=True,
                          text=True, timeout=300)
    return proc.stdout + proc.stderr


@pytest.mark.skipif(not REAL_FC, reason="freecadcmd not installed")
def test_real_freecad_lone_placed_body_and_attachment(tmp_path, fake_kit):
    placed, att = tmp_path / "placed.FCStd", tmp_path / "att.FCStd"
    out = _run_fc(tmp_path, "mk.py", REAL_DOC_SCRIPT % (str(placed), str(att)))
    assert "REAL_DOCS_OK" in out, out

    # one body, rotated 90 deg about Z at x=100 inside an App::Part at y=200
    res = make(tmp_path / "p1", fake_kit, fcstd_path=str(placed),
               freecadcmd=REAL_FC)
    out = _run_fc(tmp_path, "rb.py", READ_BACK_SCRIPT % res["source_files"][0])
    line = [ln for ln in out.splitlines() if ln.startswith("READBACK ")]
    assert line, out
    n, *bb = json.loads(line[0][len("READBACK "):])
    assert n == 1
    assert [round(v, 6) for v in bb] == [80, 200, 0, 100, 210, 30]

    # a boss attached to the plate leaves the plate a body of its own
    res = make(tmp_path / "p2", fake_kit, fcstd_path=str(att),
               freecadcmd=REAL_FC)
    assert res["consumed_objects"] == []
    step = open(res["source_files"][0], encoding="utf-8").read()
    assert "PRODUCT('Plate'" in step and "PRODUCT('Boss'" in step


REAL_COPY_DOC_SCRIPT = '''
import FreeCAD as App
import Draft
doc = App.newDocument("copies")
orig = doc.addObject("Part::Box", "Orig")
doc.recompute()
clone = Draft.make_clone(orig)
clone.Label = "TheClone"
clone.Placement.Base = App.Vector(30, 0, 0)
asm = doc.addObject("App::Part", "Asm")
asm.Placement.Base = App.Vector(0, 0, 50)
link = doc.addObject("App::Link", "LinkInAsm")
link.LinkedObject = orig
link.Placement.Base = App.Vector(0, 0, 5)
asm.addObject(link)
doc.recompute()
doc.saveAs(%r)
print("REAL_DOCS_OK")
'''

READ_SOLIDS_SCRIPT = '''
import json
import Part
s = Part.read(%r)
print("SOLIDS " + json.dumps(sorted(
    [round(v, 6) for v in (x.BoundBox.XMin, x.BoundBox.YMin, x.BoundBox.ZMin)]
    for x in s.Solids)))
'''


@pytest.mark.skipif(not REAL_FC, reason="freecadcmd not installed")
def test_real_freecad_clone_source_and_link_are_bodies(tmp_path, fake_kit):
    doc = tmp_path / "copies.FCStd"
    out = _run_fc(tmp_path, "mk.py", REAL_COPY_DOC_SCRIPT % str(doc))
    assert "REAL_DOCS_OK" in out, out
    res = make(tmp_path / "p", fake_kit, fcstd_path=str(doc),
               freecadcmd=REAL_FC)
    assert res["consumed_objects"] == []
    step = open(res["source_files"][0], encoding="utf-8").read()
    for label in ("Orig", "TheClone", "LinkInAsm"):
        assert "PRODUCT('%s'" % label in step, label
    out = _run_fc(tmp_path, "rb.py", READ_SOLIDS_SCRIPT % res["source_files"][0])
    line = [ln for ln in out.splitlines() if ln.startswith("SOLIDS ")]
    assert line, out
    # the original at the origin, the clone at x=30, the link at z=50+5
    assert json.loads(line[0][len("SOLIDS "):]) == [
        [0, 0, 0], [0, 0, 55], [30, 0, 0]]
