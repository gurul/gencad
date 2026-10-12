#!/usr/bin/env python3
"""gencad — a zero-dependency MCP server that gives agents hands for FreeCAD.

Exposes headless FreeCAD (freecadcmd) over the Model Context Protocol so a
coding agent can build parametric solids from Python, then *look at what it
made* through section renders — the tight build/render/inspect loop that makes
generative CAD actually converge.

Transport: stdio, one JSON-RPC 2.0 message per line (MCP stdio framing).
No pip installs — stdlib only. FreeCAD provides the geometry kernel.

Config (env):
  GENCAD_FREECADCMD  path to freecadcmd
                     (default: /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd,
                      falls back to `freecadcmd` on PATH)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "gencad", "version": "0.1.0"}


def freecadcmd():
    cand = os.environ.get("GENCAD_FREECADCMD")
    if cand and os.path.exists(cand):
        return cand
    default = "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
    if os.path.exists(default):
        return default
    found = shutil.which("freecadcmd")
    if found:
        return found
    raise RuntimeError(
        "freecadcmd not found — install FreeCAD or set GENCAD_FREECADCMD")


TOOLS = [
    {
        "name": "freecad_run",
        "description": (
            "Run a Python build script inside headless FreeCAD (freecadcmd). "
            "The script has the full FreeCAD API (Part, Draft, Mesh, ...) and "
            "typically constructs solids and exports FCStd/STEP/STL. Returns "
            "the script's stdout/stderr. Print progress and assertions from "
            "the script — that output is your feedback channel."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "script_path": {
                    "type": "string",
                    "description": "Absolute path to the .py build script"},
                "timeout_s": {
                    "type": "number",
                    "description": "Kill the build after this many seconds (default 600)"},
            },
            "required": ["script_path"],
        },
    },
    {
        "name": "freecad_render_section",
        "description": (
            "Render a planar cross-section of an object in a .FCStd document "
            "to a PNG so you can visually verify geometry (hole patterns, "
            "wall thickness, clearances, debossed text). Sections through a "
            "face show exactly what that face looks like. Returns the PNG "
            "path — read the image to inspect it."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fcstd_path": {"type": "string",
                               "description": "Absolute path to the .FCStd document"},
                "object_name": {"type": "string",
                                "description": "Name of the Part object (e.g. 'Base')"},
                "axis": {"type": "string", "enum": ["x", "y", "z"],
                         "description": "Section plane normal"},
                "offset": {"type": "number",
                           "description": "Plane position along the axis (mm)"},
                "out_png": {"type": "string",
                            "description": "Absolute output PNG path"},
                "filled": {"type": "boolean",
                           "description": "Fill material regions (default) vs outline only"},
                "window": {"type": "array", "items": {"type": "number"},
                           "minItems": 4, "maxItems": 4,
                           "description": "Optional zoom [min_u, max_u, min_v, max_v] in the section plane"},
            },
            "required": ["fcstd_path", "object_name", "axis", "offset", "out_png"],
        },
    },
]


# freecadcmd catches a script's uncaught exception, prints this line and still
# exits 0 — so the exit code alone cannot tell success from a crashed script.
FREECAD_EXCEPTION = "Exception while processing file"
# printed by tools/render_section.py as its last action, after savefig
RENDER_SENTINEL = "gencad-render-ok:"
AXES = ("x", "y", "z")


def run_freecad(script_path, timeout_s=600, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [freecadcmd(), script_path],
        capture_output=True, text=True, timeout=timeout_s, env=env)
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    # freecadcmd is chatty; keep the tail, which is where builds print results
    if len(out) > 20000:
        out = "...(truncated)...\n" + out[-20000:]
    return proc.returncode, out


def tool_freecad_run(args):
    """Returns (text, is_error)."""
    path = args.get("script_path")
    if not isinstance(path, str) or not os.path.isfile(path):
        return "error: no such script: %s" % path, True
    code, out = run_freecad(path, args.get("timeout_s", 600))
    if code != 0 or FREECAD_EXCEPTION in out:
        return "script failed (exit %d)\n%s" % (code, out), True
    return "exit %d\n%s" % (code, out), False


def tool_render_section(args):
    """Returns (text, is_error)."""
    for key in ("fcstd_path", "object_name", "out_png"):
        if not isinstance(args.get(key), str) or not args[key]:
            return "error: %s must be a non-empty string" % key, True
    if args.get("axis") not in AXES:
        return ("error: axis must be one of %s, got %r"
                % (", ".join(AXES), args.get("axis"))), True
    offset = args.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        return "error: offset must be a number, got %r" % (offset,), True
    out_png = args["out_png"]
    # a PNG left by an earlier render must never pass as this render's output
    if os.path.lexists(out_png):
        os.unlink(out_png)
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "tools", "render_section.py")
    helper = os.path.normpath(helper)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(args, f)
        cfg = f.name
    try:
        code, out = run_freecad(helper, 300, {"GENCAD_SECTION_ARGS": cfg})
    finally:
        os.unlink(cfg)
    ok = (code == 0 and FREECAD_EXCEPTION not in out
          and (RENDER_SENTINEL + " " + out_png) in out
          and os.path.isfile(out_png))
    if ok:
        return "rendered: %s\n%s" % (out_png, out[-2000:]), False
    return "render failed (exit %d)\n%s" % (code, out), True


TOOL_FUNCS = {
    "freecad_run": tool_freecad_run,
    "freecad_render_section": tool_render_section,
}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def handle(req):
    method = req.get("method")
    if not isinstance(method, str):
        raise RpcError(-32600, "invalid request: method must be a string")
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = req.get("params")
        if not isinstance(params, dict):
            raise RpcError(-32602, "invalid params: params must be an object")
        name = params.get("name")
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise RpcError(-32602, "invalid params: arguments must be an object")
        try:
            func = TOOL_FUNCS.get(name)
            if func is None:
                raise ValueError("unknown tool: %s" % name)
            text, is_error = func(args)
            result = {"content": [{"type": "text", "text": text}]}
            if is_error:
                result["isError"] = True
            return result
        except Exception as e:  # tool errors go back as content, not crashes
            return {"content": [{"type": "text", "text": "error: %s" % e}],
                    "isError": True}
    if method == "ping":
        return {}
    raise RpcError(-32601, "method not found: %s" % method)


def respond(req_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            print("gencad: skipped unparseable line", file=sys.stderr)
            continue
        if not isinstance(req, dict):
            # no recoverable id, so there is nobody to answer — skip it
            print("gencad: skipped non-object message", file=sys.stderr)
            continue
        if "id" not in req:      # notification — nothing to answer
            continue
        req_id = req["id"]
        try:
            respond(req_id, result=handle(req))
        except RpcError as e:
            respond(req_id, error={"code": e.code, "message": e.message})
        except Exception as e:  # never let one request take the server down
            respond(req_id, error={"code": -32603,
                                   "message": "internal error: %s" % e})


if __name__ == "__main__":
    main()
