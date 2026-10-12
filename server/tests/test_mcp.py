"""Drive gencad_mcp.py over stdio, the way an MCP client does.

FreeCAD is not needed: GENCAD_FREECADCMD points at a fake freecadcmd that
mimics the real one's behaviour on an uncaught script exception (it prints
"Exception while processing file: ..." and still exits 0).

Run: uvx --with pytest pytest server/tests -q
"""
import json
import os
import stat
import subprocess
import sys
import textwrap

import pytest

SERVER = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "gencad_mcp.py"))

FAKE_FREECADCMD = textwrap.dedent('''\
    #!{python}
    """Fake freecadcmd: runs the script with this Python, like freecadcmd."""
    import os, runpy, sys
    script = sys.argv[1]
    mode = os.environ.get("FAKE_FC_MODE", "")
    if "GENCAD_SECTION_ARGS" in os.environ and mode:
        import json
        args = json.load(open(os.environ["GENCAD_SECTION_ARGS"]))
        if mode in ("render_ok", "render_no_sentinel"):
            with open(args["out_png"], "wb") as f:
                f.write(b"\\x89PNG fresh")
            print("gencad: wrote", args["out_png"])
            if mode == "render_ok":
                print("gencad-render-ok: " + args["out_png"])
        sys.exit(0)
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
def fake_env(tmp_path):
    fake = tmp_path / "freecadcmd"
    fake.write_text(FAKE_FREECADCMD.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ)
    env["GENCAD_FREECADCMD"] = str(fake)
    env.pop("FAKE_FC_MODE", None)
    return env


def serve(lines, env=None, timeout=60):
    """Feed raw lines to one server process; return (responses_by_id, rc)."""
    data = "".join(l if l.endswith("\n") else l + "\n" for l in lines)
    proc = subprocess.run([sys.executable, SERVER], input=data,
                          capture_output=True, text=True, timeout=timeout,
                          env=env)
    out = {}
    for line in proc.stdout.splitlines():
        msg = json.loads(line)
        out[msg["id"]] = msg
    return out, proc.returncode, proc.stderr


def rpc(id_, method, params=None):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def call(id_, name, arguments):
    return rpc(id_, "tools/call", {"name": name, "arguments": arguments})


PING = rpc(999, "ping")


# --- fix 3: malformed requests must not kill the server -------------------

@pytest.mark.parametrize("bad", [
    "5",
    "null",
    '"idx"',
    "[1, 2]",
    "{not json",
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}),
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": []}),
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "freecad_run", "arguments": "x"}}),
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": 42}),
    json.dumps({"jsonrpc": "2.0", "id": 1}),
])
def test_malformed_line_then_ping_still_answered(bad):
    resp, rc, err = serve([bad, PING])
    assert rc == 0, err
    assert resp.get(999) == {"jsonrpc": "2.0", "id": 999, "result": {}}, err


@pytest.mark.parametrize("bad,code", [
    ({"method": "tools/call"}, -32602),
    ({"method": "tools/call", "params": []}, -32602),
    ({"method": "tools/call",
      "params": {"name": "freecad_run", "arguments": "x"}}, -32602),
    ({"method": 42}, -32600),
    ({}, -32600),
    ({"method": "no/such/method"}, -32601),
])
def test_malformed_request_with_id_gets_jsonrpc_error(bad, code):
    msg = dict(bad, jsonrpc="2.0", id=7)
    resp, rc, err = serve([json.dumps(msg), PING])
    assert rc == 0, err
    assert resp[7]["error"]["code"] == code
    assert "result" not in resp[7]
    assert 999 in resp


def test_unknown_tool_is_error_and_server_continues():
    resp, rc, _ = serve([call(3, "no_such_tool", {}), PING])
    assert rc == 0
    assert resp[3]["result"]["isError"] is True
    assert 999 in resp


def test_initialize_and_tools_list():
    resp, rc, _ = serve([rpc(1, "initialize", {}), rpc(2, "tools/list")])
    assert rc == 0
    assert resp[1]["result"]["serverInfo"]["name"] == "gencad"
    names = {t["name"] for t in resp[2]["result"]["tools"]}
    assert names == {"freecad_run", "freecad_render_section"}


# --- fix 2: freecad_run error paths ----------------------------------------

def test_freecad_run_script_exception_is_error(tmp_path, fake_env):
    script = tmp_path / "boom.py"
    script.write_text('print("before")\nraise RuntimeError("boom")\n')
    resp, rc, _ = serve([call(1, "freecad_run",
                              {"script_path": str(script)})], fake_env)
    res = resp[1]["result"]
    assert res.get("isError") is True
    assert "Exception while processing file" in res["content"][0]["text"]
    assert "boom" in res["content"][0]["text"]


def test_freecad_run_nonzero_exit_is_error(tmp_path, fake_env):
    script = tmp_path / "exit3.py"
    script.write_text("import sys\nsys.exit(3)\n")
    resp, _, _ = serve([call(1, "freecad_run",
                             {"script_path": str(script)})], fake_env)
    res = resp[1]["result"]
    assert res.get("isError") is True
    assert "exit 3" in res["content"][0]["text"]


def test_freecad_run_success_is_not_error(tmp_path, fake_env):
    script = tmp_path / "ok.py"
    script.write_text('print("built ok")\n')
    resp, _, _ = serve([call(1, "freecad_run",
                             {"script_path": str(script)})], fake_env)
    res = resp[1]["result"]
    assert not res.get("isError")
    assert res["content"][0]["text"].startswith("exit 0")
    assert "built ok" in res["content"][0]["text"]


def test_freecad_run_missing_script_is_error(tmp_path, fake_env):
    resp, _, _ = serve([call(1, "freecad_run",
                             {"script_path": str(tmp_path / "nope.py")})],
                       fake_env)
    res = resp[1]["result"]
    assert res.get("isError") is True
    assert "no such script" in res["content"][0]["text"]


# --- fix 2: freecad_render_section must never report a stale PNG -----------

def render_args(tmp_path, **over):
    args = {"fcstd_path": str(tmp_path / "m.FCStd"), "object_name": "Ring",
            "axis": "z", "offset": 0, "out_png": str(tmp_path / "out.png")}
    args.update(over)
    return args


@pytest.fixture
def stale_png(tmp_path):
    png = tmp_path / "out.png"
    png.write_bytes(b"\x89PNG stale")
    return png


def test_render_helper_exception_is_error_and_stale_png_removed(
        tmp_path, fake_env, stale_png):
    # no FAKE_FC_MODE: the fake runs the real helper, whose `import FreeCAD`
    # raises — freecadcmd's "Exception while processing file", exit 0
    resp, _, _ = serve([call(1, "freecad_render_section",
                             render_args(tmp_path))], fake_env)
    res = resp[1]["result"]
    text = res["content"][0]["text"]
    assert res.get("isError") is True
    assert not text.startswith("rendered:")
    assert "Exception while processing file" in text
    assert not stale_png.exists()


def test_render_without_sentinel_is_error(tmp_path, fake_env, stale_png):
    fake_env["FAKE_FC_MODE"] = "render_no_sentinel"
    resp, _, _ = serve([call(1, "freecad_render_section",
                             render_args(tmp_path))], fake_env)
    assert resp[1]["result"].get("isError") is True


def test_render_ok_reports_fresh_png(tmp_path, fake_env, stale_png):
    fake_env["FAKE_FC_MODE"] = "render_ok"
    resp, _, _ = serve([call(1, "freecad_render_section",
                             render_args(tmp_path))], fake_env)
    res = resp[1]["result"]
    assert not res.get("isError")
    assert res["content"][0]["text"].startswith("rendered: %s" % stale_png)
    assert stale_png.read_bytes() == b"\x89PNG fresh"


@pytest.mark.parametrize("over", [
    {"axis": "q"}, {"axis": None}, {"offset": "zero"}, {"offset": True},
    {"object_name": ""}, {"out_png": 5},
])
def test_render_bad_args_rejected_before_freecad(tmp_path, fake_env,
                                                 stale_png, over):
    # render_ok would succeed if FreeCAD were reached; it must not be
    fake_env["FAKE_FC_MODE"] = "render_ok"
    resp, _, _ = serve([call(1, "freecad_render_section",
                             render_args(tmp_path, **over))], fake_env)
    res = resp[1]["result"]
    assert res.get("isError") is True
    assert res["content"][0]["text"].startswith("error:")
