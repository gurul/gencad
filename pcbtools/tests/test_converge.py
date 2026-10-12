"""converge must not re-apply a stale routes.json after a router crash
(fix 8)."""
import json
import os
import subprocess
import types

import pytest

import converge


def test_router_crash_does_not_reuse_stale_routes(tmp_path, monkeypatch):
    writes = []
    rounds = {"n": 0}

    def fake_sh(script, *args):
        if script == "dump_board.py":
            out = args[args.index("-o") + 1]
            json.dump({"origin_abs_mm": [0, 0]}, open(out, "w"))
            return types.SimpleNamespace(stdout="DUMP_OK", stderr="",
                                         returncode=0)
        if script == "write_board.py":
            writes.append(open(args[1]).read())
            return types.SimpleNamespace(stdout="WRITE_OK", stderr="",
                                         returncode=0)
        raise AssertionError(script)

    def fake_run(cmd, **kw):
        # route.py: round 1 succeeds, round 2 crashes before writing
        rounds["n"] += 1
        out = cmd[cmd.index("-o") + 1]
        if rounds["n"] == 1:
            json.dump({"routes": [{"net": "A", "elements": []}],
                       "failed": []}, open(out, "w"))
            return subprocess.CompletedProcess(cmd, 0, "BEST: routed 1", "")
        return subprocess.CompletedProcess(cmd, 1, "", "Traceback: boom")

    unconnected = iter([3, 2, 1, 0, 0])
    monkeypatch.setattr(converge, "sh", fake_sh)
    monkeypatch.setattr(converge.subprocess, "run", fake_run)
    monkeypatch.setattr(converge.drc_mod, "run_drc", lambda b: {})
    monkeypatch.setattr(
        converge.drc_mod, "summarize",
        lambda rep, origin=(0, 0): {"errors": {}, "error_count": 0,
                                    "unconnected": next(unconnected),
                                    "airwires": []})
    monkeypatch.setattr(converge.tempfile, "mkdtemp",
                        lambda prefix="": str(tmp_path))
    monkeypatch.setattr("sys.argv", ["converge.py", "board.kicad_pcb"])

    with pytest.raises(SystemExit) as ei:
        converge.main()
    assert "router failed" in str(ei.value)
    assert len(writes) == 1          # round 2's stale file never applied
    assert not os.path.exists(tmp_path / "routes.json")
