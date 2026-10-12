"""Clearance oracle: inner-layer TH pads (fix 3), keep-out width (fix 5)."""
from clearance import Board
from geo_fixtures import SQUARE_KO, board_geo, smd_pad, th_pad


def test_th_pad_obstructs_inner_layer():
    b = Board(board_geo(pads=[th_pad(net="GND")]))
    v = b.seg_clear(-5, 0, 5, 0, "In1.Cu", net="SIG", width=0.2)
    assert any(m.startswith("pad J1.1") for m in v), v


def test_th_pad_obstructs_inner_layer_short_alias():
    b = Board(board_geo(pads=[th_pad(net="GND")]))
    assert b.seg_clear(-5, 0, 5, 0, "In2", net="SIG", width=0.2)


def test_smd_pad_does_not_obstruct_inner_layer():
    b = Board(board_geo(pads=[smd_pad(net="GND")]))
    assert b.seg_clear(-5, 0, 5, 0, "In1.Cu", net="SIG", width=0.2) == []
    assert b.seg_clear(-5, 0, 5, 0, "F.Cu", net="SIG", width=0.2)


def test_pad_without_inner_copper_is_clear_on_inner():
    b = Board(board_geo(pads=[th_pad(net="GND", inner=())]))
    assert b.seg_clear(-5, 0, 5, 0, "In1.Cu", net="SIG", width=0.2) == []


def test_keepout_counts_track_width():
    # centreline 0.25 mm outside the keep-out edge x=2; never enters it.
    # half-width 0.2 + clearance 0.1 = 0.3 > 0.25 -> must be rejected
    b = Board(board_geo(keepouts=[SQUARE_KO]))
    v = b.seg_clear(2.25, -5, 2.25, 5, "F.Cu", net="SIG", width=0.4)
    assert any(m.startswith("keepout") for m in v), v


def test_keepout_clear_when_far_enough():
    # 0.35 mm away: 0.2 + 0.1 = 0.3 < 0.35 -> legal
    b = Board(board_geo(keepouts=[SQUARE_KO]))
    assert b.seg_clear(2.35, -5, 2.35, 5, "F.Cu", net="SIG",
                       width=0.4) == []


def test_keepout_short_segment_crossing_corner():
    # a segment that clips the corner between sample points still hits
    b = Board(board_geo(keepouts=[SQUARE_KO]))
    v = b.seg_clear(1.9, 2.1, 2.1, 1.9, "F.Cu", net="SIG", width=0.01)
    assert any(m.startswith("keepout") for m in v), v


def test_keepout_respects_layer_list():
    ko = dict(SQUARE_KO, layers=["F.Cu"])
    b = Board(board_geo(keepouts=[ko]))
    assert b.seg_clear(-5, 0, 5, 0, "B.Cu", net="SIG", width=0.2) == []


def test_via_keepout_counts_diameter():
    # via centre 0.3 outside the edge: radius 0.25 + clearance 0.1 > 0.3
    b = Board(board_geo(keepouts=[SQUARE_KO]))
    assert "keepout" in b.via_clear(2.3, 0, net="SIG", dia=0.5)
    assert "keepout" not in b.via_clear(2.5, 0, net="SIG", dia=0.5)
