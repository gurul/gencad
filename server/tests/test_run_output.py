"""Exercise output classification with real, portable Python child processes.

The child emits FreeCAD's documented zero-exit exception marker. These tests
cover subprocess output handling, not native FreeCAD geometry execution.
"""
import importlib.util
import pathlib
import sys

import pytest


@pytest.fixture
def server(monkeypatch):
    path = pathlib.Path(__file__).resolve().parents[1] / "gencad_mcp.py"
    spec = importlib.util.spec_from_file_location("gencad_output_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "freecadcmd", lambda: sys.executable)
    return module


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("failed", [False, True])
def test_long_output_preserves_script_failure(server, tmp_path, stream, failed):
    script = tmp_path / "output.py"
    marker = server.FREECAD_EXCEPTION + ": model.py [boom]"
    script.write_text(
        "import sys\n"
        + ("print(%r)\n" % marker if failed else "")
        + "print('x' * 21000, file=sys.%s)\n" % stream
        + "print('output-tail', file=sys.%s)\n" % stream,
        encoding="utf-8",
    )
    result = server.handle({
        "method": "tools/call",
        "params": {"name": "freecad_run",
                   "arguments": {"script_path": str(script)}},
    })
    assert result.get("isError", False) is failed
    text = result["content"][0]["text"]
    assert "truncated" in text
    assert "output-tail" in text
    assert len(text) < 20200
    if failed:
        assert server.FREECAD_EXCEPTION in text
