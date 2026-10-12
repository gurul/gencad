"""drc net-name parsing (fix 4): bracketed net names must survive."""
import drc


def test_net_with_brackets():
    assert drc.net_from_desc("Pad 1 [/DATA[0]] of R1 on F.Cu") == "/DATA[0]"


def test_plain_net():
    assert drc.net_from_desc("Pad 2 [GND] of R1 on F.Cu") == "GND"


def test_net_at_end_of_description():
    assert drc.net_from_desc("Via [/BUS[3]]") == "/BUS[3]"


def test_no_net():
    assert drc.net_from_desc("Board edge") == "?"


def test_summarize_keeps_full_net_name():
    rep = {"violations": [], "unconnected_items": [{"items": [
        {"description": "Pad 1 [/DATA[0]] of R1 on F.Cu",
         "pos": {"x": 110.0, "y": 110.0}},
        {"description": "Pad 1 [/DATA[0]] of R2 on B.Cu",
         "pos": {"x": 130.0, "y": 110.0}}]}]}
    s = drc.summarize(rep, origin=(120.0, 115.0))
    assert [a["net"] for a in s["airwires"]] == ["/DATA[0]"]
    assert s["airwires"][0]["a"] == {
        "x": -10.0, "y": -5.0, "desc": "Pad 1 [/DATA[0]] of R1 on F.Cu"}
