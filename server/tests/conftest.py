"""Shared fixtures for the Enclose bridge tests.

Neither build123d nor Enclose is needed: `fake_kit` is a stand-in Enclose
checkout whose kit/enclose.py implements just enough of Model / read_step for
a scaffolded model.py to run with plain Python and write a manifest. The stub
STEP files carry one `BODY: <label>` line per body, or
`BODY: <label> @ <group>` to put the body in a group other than "Parts".
"""
import textwrap

import pytest

STUB_ENCLOSE_PY = textwrap.dedent('''\
    """Test stand-in for the Enclose kit exporter (not the real one)."""
    import json
    import os
    import re
    import sys

    HERE = os.path.dirname(os.path.abspath(sys.argv[0] or "."))


    class Found:
        def __init__(self, id, label, group, color, shape):
            self.id, self.label, self.group = id, label, group
            self.color, self.shape = color, shape


    def read_step(*files):
        found = []
        for f in files:
            text = open(os.path.join(HERE, f)).read()
            if "BROKEN" in text:
                raise ValueError(f + " could not be read as a STEP file.")
            for line in text.splitlines():
                if line.startswith("BODY:"):
                    label, _, group = line[5:].partition(" @ ")
                    label = label.strip()
                    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                    found.append(Found(slug, label, group.strip() or "Parts",
                                       None, object()))
        return found


    class Model:
        def __init__(self, title=None):
            self.title, self.groups, self.parts = title, [], []

        def group(self, label, *, shell=False, id=None):
            # as the real kit: the id defaults to a slug of the label, and
            # two groups with one id are an error
            gid = id or (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                         or "part")
            if any(g["id"] == gid for g in self.groups):
                raise ValueError('two groups share the id "%s"' % gid)
            self.groups.append({"id": gid, "label": label})
            return gid

        def part(self, id, shape, *, label=None, group=None, color=None):
            self.parts.append({"id": id, "label": label, "group": group,
                               "file": id + ".glb", "edges": id + ".edges.bin"})

        def write(self):
            if os.environ.get("STUB_BUILD_NO_MANIFEST"):
                print("pretending to build, writing nothing")
                return None
            out = os.path.join(HERE, "build")
            os.makedirs(out, exist_ok=True)
            for p in self.parts:
                for key in ("file", "edges"):
                    open(os.path.join(out, p[key]), "wb").close()
            path = os.path.join(out, "enclose.model.json")
            with open(path, "w") as f:
                json.dump({"title": self.title, "groups": self.groups,
                           "parts": self.parts}, f)
            print("%d parts" % len(self.parts))
            return path
''')

STUB_SCREWS_PY = '"""Test stand-in for the Enclose screws kit."""\n'


def step_text(*labels, broken=False):
    body = "".join("BODY: %s\n" % l for l in labels)
    return "ISO-10303-21;\n%s%sEND-ISO-10303-21;\n" % (
        body, "BROKEN\n" if broken else "")


@pytest.fixture
def fake_kit(tmp_path):
    root = tmp_path / "fake-enclose"
    (root / "kit").mkdir(parents=True)
    (root / "kit" / "enclose.py").write_text(STUB_ENCLOSE_PY)
    (root / "kit" / "screws.py").write_text(STUB_SCREWS_PY)
    return root
