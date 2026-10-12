"""Router: --layers validation (fix 1), inner-layer pads (fix 3),
keep-out mask growth (fix 5), no silent airwire drop (fix 4)."""
import pytest

np = pytest.importorskip("numpy")
import route  # noqa: E402
from clearance import Board  # noqa: E402
from geo_fixtures import SQUARE_KO, board_geo, th_pad  # noqa: E402

LAYERS = ["F.Cu", "B.Cu", "In1.Cu", "In2.Cu"]


def test_select_layers_default_is_outer():
    assert route.select_layers(None, LAYERS) == ["F.Cu", "B.Cu"]


def test_select_layers_accepts_board_layers():
    assert route.select_layers("F.Cu,In2.Cu", LAYERS) == ["F.Cu", "In2.Cu"]


def test_select_layers_rejects_unknown():
    with pytest.raises(ValueError, match="In3.Cu"):
        route.select_layers("F.Cu,In3.Cu", LAYERS)


def test_select_layers_rejects_inner_on_two_layer_board():
    with pytest.raises(ValueError):
        route.select_layers("In2.Cu", ["F.Cu", "B.Cu"])


def test_main_exits_on_unknown_layer(tmp_path, monkeypatch):
    geo = tmp_path / "g.json"
    air = tmp_path / "a.json"
    geo.write_text(__import__("json").dumps(board_geo()))
    air.write_text("[]")
    monkeypatch.setattr("sys.argv", ["route.py", str(geo), str(air),
                                     "-o", str(tmp_path / "r.json"),
                                     "--layers", "F.Cu,In7.Cu"])
    with pytest.raises(SystemExit) as ei:
        route.main()
    assert "In7.Cu" in str(ei.value)
    assert not (tmp_path / "r.json").exists()


def _cell(grid, x, y):
    return grid.idx(x, y)


def test_th_pad_blocks_inner_layer_mask():
    b = Board(board_geo(pads=[th_pad(net="GND")]))
    g = route.Grid(b, ["F.Cu", "In1.Cu"], 0.1)
    blk, _ = g.build_masks("SIG", 0.2, 0.5)
    assert blk["In1.Cu"][_cell(g, 0, 0)]
    assert blk["F.Cu"][_cell(g, 0, 0)]


def test_keepout_mask_grows_by_track_width():
    # cell 0.3 mm outside the keep-out edge x=2. Track 0.4 + clearance 0.1
    # needs 0.3 + slop, so the cell must be blocked for tracks
    b = Board(board_geo(keepouts=[SQUARE_KO]))
    g = route.Grid(b, ["F.Cu"], 0.1)
    blk, vblk = g.build_masks("SIG", 0.4, 0.5)
    assert blk["F.Cu"][_cell(g, 2.3, 0)]
    assert vblk[_cell(g, 2.3, 0)]
    assert not blk["F.Cu"][_cell(g, 3.0, 0)]


def test_airwire_with_no_components_is_reported_failed():
    b = Board(board_geo())
    g = route.Grid(b, ["F.Cu", "B.Cu"], 0.2)
    air = [{"net": "/DATA", "a": {"x": -5, "y": 0}, "b": {"x": 5, "y": 0}}]
    routes, failed = route.route_all(b, g, ["F.Cu", "B.Cu"], air,
                                     [(0.2, 0.5)], seed=0)
    assert routes == []
    assert [f["net"] for f in failed] == ["/DATA"]
