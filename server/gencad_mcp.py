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
    path = args["script_path"]
    if not os.path.isfile(path):
        return "error: no such script: %s" % path
    code, out = run_freecad(path, args.get("timeout_s", 600))
    return "exit %d\n%s" % (code, out)


def tool_render_section(args):
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
    if code == 0 and os.path.exists(args["out_png"]):
        return "rendered: %s\n%s" % (args["out_png"], out[-2000:])
    return "render failed (exit %d)\n%s" % (code, out)


def handle(req):
    method = req.get("method")
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        try:
            if name == "freecad_run":
                text = tool_freecad_run(args)
            elif name == "freecad_render_section":
                text = tool_render_section(args)
            else:
                raise ValueError("unknown tool: %s" % name)
            return {"content": [{"type": "text", "text": text}]}
        except Exception as e:  # tool errors go back as content, not crashes
            return {"content": [{"type": "text", "text": "error: %s" % e}],
                    "isError": True}
    if method == "ping":
        return {}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:      # notification — nothing to answer
            continue
        result = handle(req)
        if result is None:
            resp = {"jsonrpc": "2.0", "id": req["id"],
                    "error": {"code": -32601,
                              "message": "method not found: %s" % req.get("method")}}
        else:
            resp = {"jsonrpc": "2.0", "id": req["id"], "result": result}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
