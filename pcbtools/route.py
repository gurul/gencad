#!/usr/bin/env python3
"""Legalising grid autorouter over a dumped board geometry.

A rasterised multi-layer A* with a hard acceptance gate: every candidate
path is re-verified by :mod:`clearance` (independent geometry math) before
it is accepted, and every accepted route becomes an obstacle for the nets
that follow. Random-restart ordering keeps one greedy pass from wedging
the board. The output JSON is applied by :mod:`write_board`.

Design notes carried from hard experience:
  * Obstacle masks sample cell centres, so every margin carries half a
    cell diagonal of slop — without it, tracks drawn between centres pass
    closer to copper than the mask implied.
  * Drilled holes block every layer (and vias); SMD pads block only their
    own faces. Forgetting the first is how inner-layer routes end up
    through connector mounting holes.
  * Layer changes are refused wherever a via is illegal, including at the
    goal — "the destination excuses the via" is how shorts are born.

    python route.py geometry.json airwires.json -o routes.json \
        [--layers F.Cu,In2.Cu,B.Cu] [--cell 0.05] [--restarts 3] \
        [--classes 0.2:0.5,0.15:0.45,0.127:0.4] [--exempt-gfx-nets NETA,NETB]

``airwires.json`` is a list of {"net", "a": {x, y, desc}, "b": {...}}
pairs, e.g. from :mod:`drc`'s unconnected report.
"""
import argparse
import heapq
import json
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clearance import Board, _pt_seg, _seg_seg, _seg_box

VIA_COST = 12.0


class Grid:
    def __init__(self, board, layers, cell):
        self.b = board
        self.layers = layers
        self.cell = cell
        self.slop = cell * math.sqrt(2) / 2
        if board.outline["type"] == "circle":
            r = board.outline["r"] + 0.1
            self.lo_x = self.lo_y = -r
            n = int(round(2 * r / cell)) + 1
            self.nx = self.ny = n
        else:
            l, t, r, bt = board.outline["box"]
            self.lo_x, self.lo_y = l - 0.1, t - 0.1
            self.nx = int(round((r - l + 0.2) / cell)) + 1
            self.ny = int(round((bt - t + 0.2) / cell)) + 1
        xs = np.linspace(self.lo_x, self.lo_x + cell * (self.nx - 1), self.nx)
        ys = np.linspace(self.lo_y, self.lo_y + cell * (self.ny - 1), self.ny)
        self.GX, self.GY = np.meshgrid(xs, ys, indexing="ij")
        if board.outline["type"] == "circle":
            self.off = np.hypot(self.GX, self.GY) > \
                board.outline["r"] - board.edge_clearance
        else:
            l, t, r, bt = board.outline["box"]
            m = board.edge_clearance
            self.off = ~((self.GX >= l + m) & (self.GX <= r - m) &
                         (self.GY >= t + m) & (self.GY <= bt - m))
        self.ko_track = {lay: self._keepout_mask(lay, "no_tracks")
                         for lay in layers}
        self.ko_via = self._keepout_mask(None, "no_vias")

    def _keepout_mask(self, layer, kind):
        m = np.zeros_like(self.off)
        for ko in self.b.g.get("keepouts", []):
            if not ko.get(kind) or not ko["poly"]:
                continue
            if layer is not None and layer not in ko["layers"]:
                continue
            poly = ko["poly"]
            px = np.array([p[0] for p in poly])
            py = np.array([p[1] for p in poly])
            inside = np.zeros_like(self.off)
            j = len(poly) - 1
            for i in range(len(poly)):
                cond = ((py[i] > self.GY) != (py[j] > self.GY))
                with np.errstate(divide="ignore", invalid="ignore"):
                    xin = px[i] + (self.GY - py[i]) / (py[j] - py[i]) * \
                        (px[j] - px[i])
                inside ^= cond & (self.GX < xin)
                j = i
            m |= inside
        return m

    def idx(self, x, y):
        return (int(round((x - self.lo_x) / self.cell)),
                int(round((y - self.lo_y) / self.cell)))

    def xy(self, i, j):
        return (self.lo_x + i * self.cell, self.lo_y + j * self.cell)

    def mask_box(self, box, grow):
        l, t, r, bt = box
        return ((self.GX >= l - grow) & (self.GX <= r + grow) &
                (self.GY >= t - grow) & (self.GY <= bt + grow))

    def mask_seg(self, x1, y1, x2, y2, grow):
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        if l2 == 0:
            d = np.hypot(self.GX - x1, self.GY - y1)
        else:
            t = np.clip(((self.GX - x1) * dx + (self.GY - y1) * dy) / l2,
                        0.0, 1.0)
            d = np.hypot(self.GX - (x1 + t * dx), self.GY - (y1 + t * dy))
        return d <= grow

    def build_masks(self, net, tw, vd, exempt_gfx_nets=()):
        b = self.b
        tb = tw / 2 + b.clearance + self.slop
        vb = vd / 2 + b.clearance + self.slop
        blk = {lay: (self.off | self.ko_track[lay]).copy()
               for lay in self.layers}
        vblk = (self.off | self.ko_via).copy()
        for p in b.g["pads"]:
            if p["net"] == net:
                continue
            box = b.pad_box(p)
            for lay in self.layers:
                if b._pad_on_layer(p, lay):
                    blk[lay] |= self.mask_box(box, tb)
            if any(b._pad_on_layer(p, lay) for lay in self.layers):
                vblk |= self.mask_box(box, vb)
        for t in b.g["tracks"]:
            if t["net"] == net or t["layer"] not in blk:
                continue
            g = self.mask_seg(t["x1"], t["y1"], t["x2"], t["y2"],
                              tb + t["w"] / 2)
            blk[t["layer"]] |= g
            vblk |= self.mask_seg(t["x1"], t["y1"], t["x2"], t["y2"],
                                  vb + t["w"] / 2)
        for v in b.g["vias"]:
            if v["net"] == net:
                continue
            g = self.mask_seg(v["x"], v["y"], v["x"], v["y"], tb + v["dia"] / 2)
            for lay in blk:
                blk[lay] |= g
            vblk |= self.mask_seg(v["x"], v["y"], v["x"], v["y"],
                                  vb + v["dia"] / 2)
        for h in b.g.get("holes", []):
            if h["net"] == net:
                continue
            rr = h["r"] + b.hole_margin
            g = self.mask_seg(h["x"], h["y"], h["x"], h["y"], tb + rr)
            for lay in blk:
                blk[lay] |= g
            vblk |= self.mask_seg(h["x"], h["y"], h["x"], h["y"], vb + rr)
        for gfx in b.g.get("copper_gfx", []):
            if net in exempt_gfx_nets or gfx["layer"] not in blk:
                continue
            g = self.mask_seg(gfx["x1"], gfx["y1"], gfx["x2"], gfx["y2"],
                              tb + gfx.get("w", 0.2) / 2)
            blk[gfx["layer"]] |= g
            vblk |= self.mask_seg(gfx["x1"], gfx["y1"], gfx["x2"], gfx["y2"],
                                  vb + gfx.get("w", 0.2) / 2)
        return blk, vblk


# ---- same-net connectivity (union-find over pads/tracks/vias) ---------------
def net_components(board, net, layers):
    items = []
    for p in board.g["pads"]:
        if p["net"] == net:
            items.append(("pad", p))
    for t in board.g["tracks"]:
        if t["net"] == net:
            items.append(("track", t))
    for v in board.g["vias"]:
        if v["net"] == net:
            items.append(("via", v))

    def lay_of(kind, it):
        if kind == "pad":
            return set(it["layers"])
        if kind == "track":
            return {it["layer"].replace(".Cu", "")} \
                if it["layer"] in ("F.Cu", "B.Cu") else {it["layer"]}
        return {l.replace(".Cu", "") for l in layers} | set(layers)

    def touch(a, b_):
        (ka, ia), (kb, ib) = a, b_
        la, lb = lay_of(ka, ia), lay_of(kb, ib)
        if ka != "via" and kb != "via" and not (la & lb):
            return False

        def as_seg(k, i):
            if k == "track":
                return (i["x1"], i["y1"], i["x2"], i["y2"])
            if k == "via":
                return (i["x"], i["y"], i["x"], i["y"])
            return None
        sa, sb = as_seg(ka, ia), as_seg(kb, ib)
        if sa and sb:
            ra = ia.get("dia", ia.get("w", 0)) / 2
            rb = ib.get("dia", ib.get("w", 0)) / 2
            return _seg_seg(sa, sb) <= ra + rb
        if ka == "pad" and sb:
            rb = ib.get("dia", ib.get("w", 0)) / 2
            return _seg_box(sb, board.pad_box(ia)) <= rb
        if kb == "pad" and sa:
            ra = ia.get("dia", ia.get("w", 0)) / 2
            return _seg_box(sa, board.pad_box(ib)) <= ra
        la_, ta, ra_, ba = board.pad_box(ia)
        lb_, tb_, rb_, bb = board.pad_box(ib)
        return not (ra_ < lb_ or rb_ < la_ or ba < tb_ or bb < ta)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if touch(items[i], items[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    comps = {}
    for i in range(len(items)):
        comps.setdefault(find(i), []).append(items[i])
    return list(comps.values())


def comp_cells(grid, board, comp, layers):
    out = set()
    for kind, it in comp:
        if kind == "pad":
            l, t, r, bt = board.pad_box(it)
            i0, j0 = grid.idx(l, t)
            i1, j1 = grid.idx(r, bt)
            plays = [lay for lay in layers if board._pad_on_layer(it, lay)]
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    for lay in plays:
                        out.add((i, j, lay))
        elif kind == "track":
            lay = it["layer"]
            if lay not in layers:
                continue
            steps = max(2, int(math.hypot(it["x2"] - it["x1"],
                                          it["y2"] - it["y1"]) / grid.cell) + 1)
            for k in range(steps + 1):
                x = it["x1"] + (it["x2"] - it["x1"]) * k / steps
                y = it["y1"] + (it["y2"] - it["y1"]) * k / steps
                out.add((*grid.idx(x, y), lay))
        else:
            i, j = grid.idx(it["x"], it["y"])
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for lay in layers:
                        out.add((i + di, j + dj, lay))
    return out


def snap_point(board, comp, x, y):
    best, bd = (x, y), 1e9
    for kind, it in comp:
        if kind == "pad":
            l, t, r, bt = board.pad_box(it)
            px, py = min(max(x, l), r), min(max(y, t), bt)
        elif kind == "track":
            dx, dy = it["x2"] - it["x1"], it["y2"] - it["y1"]
            l2 = dx * dx + dy * dy
            u = 0.0 if l2 == 0 else max(0.0, min(
                1.0, ((x - it["x1"]) * dx + (y - it["y1"]) * dy) / l2))
            px, py = it["x1"] + u * dx, it["y1"] + u * dy
        else:
            px, py = it["x"], it["y"]
        d = math.hypot(px - x, py - y)
        if d < bd:
            bd, best = d, (round(px, 3), round(py, 3))
    return best


DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


def astar(grid, layers, src, dst, blk, vblk, max_iter=1600000):
    dst_set = set(dst)
    if not dst_set or not src:
        return None
    tx = sum(c[0] for c in dst) / len(dst)
    ty = sum(c[1] for c in dst) / len(dst)
    openq, came, gsc, seen = [], {}, {}, set()
    for (i, j, lay) in src:
        if 0 <= i < grid.nx and 0 <= j < grid.ny:
            s = (i, j, lay)
            gsc[s] = 0.0
            heapq.heappush(openq, (math.hypot(i - tx, j - ty), s))
    it = 0
    while openq and it < max_iter:
        it += 1
        _, cur = heapq.heappop(openq)
        if cur in seen:
            continue
        seen.add(cur)
        if cur in dst_set:
            path = [cur]
            while path[-1] in came:
                path.append(came[path[-1]])
            path.reverse()
            return path
        ci, cj, clay = cur
        for di, dj, w in DIRS:
            ni, nj = ci + di, cj + dj
            if not (0 <= ni < grid.nx and 0 <= nj < grid.ny):
                continue
            nxt = (ni, nj, clay)
            if nxt in seen:
                continue
            if blk[clay][ni, nj] and nxt not in dst_set:
                continue
            ng = gsc[cur] + w
            if ng < gsc.get(nxt, 1e18):
                gsc[nxt] = ng
                came[nxt] = cur
                heapq.heappush(openq, (ng + math.hypot(ni - tx, nj - ty), nxt))
        if vblk[ci, cj]:
            continue                # a via here is illegal — even at the goal
        for other in layers:
            if other == clay:
                continue
            nxt = (ci, cj, other)
            if nxt in seen:
                continue
            ng = gsc[cur] + VIA_COST
            if ng < gsc.get(nxt, 1e18):
                gsc[nxt] = ng
                came[nxt] = cur
                heapq.heappush(openq, (ng + math.hypot(ci - tx, cj - ty), nxt))
    return None


def path_to_elements(grid, path, tw, vd):
    def simplify(run):
        lay = run[0][2]
        pts = [(c[0], c[1]) for c in run]
        keep = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = keep[-1]
            bx, by = pts[k]
            cx, cy = pts[k + 1]
            if (bx - ax) * (cy - by) != (by - ay) * (cx - bx):
                keep.append(pts[k])
        keep.append(pts[-1])
        out = []
        for a, b_ in zip(keep, keep[1:]):
            x1, y1 = grid.xy(*a)
            x2, y2 = grid.xy(*b_)
            out.append({"type": "track", "layer": lay,
                        "x1": round(x1, 3), "y1": round(y1, 3),
                        "x2": round(x2, 3), "y2": round(y2, 3), "w": tw})
        return out
    els, run = [], [path[0]]
    for prev, cur in zip(path, path[1:]):
        if cur[2] != prev[2]:
            if len(run) > 1:
                els += simplify(run)
            x, y = grid.xy(prev[0], prev[1])
            els.append({"type": "via", "x": round(x, 3), "y": round(y, 3),
                        "dia": vd})
            run = [cur]
        else:
            run.append(cur)
    if len(run) > 1:
        els += simplify(run)
    return els


def route_all(board, grid, layers, air, classes, seed, exempt_gfx_nets=()):
    order = list(air)
    if seed:
        random.Random(seed).shuffle(order)
    else:
        order.sort(key=lambda e: -math.hypot(e["a"]["x"] - e["b"]["x"],
                                             e["a"]["y"] - e["b"]["y"]))
    routes, failed = [], []
    base_cache = {}
    for e in order:
        net = e["net"]
        comps = net_components(board, net, layers)
        if len(comps) < 2:
            continue

        def which(x, y):
            bi, bd = 0, 1e9
            for ci, comp in enumerate(comps):
                d = math.hypot(*(a - b for a, b in
                                 zip(snap_point(board, comp, x, y), (x, y))))
                if d < bd:
                    bd, bi = d, ci
            return bi
        ca = which(e["a"]["x"], e["a"]["y"])
        cb = which(e["b"]["x"], e["b"]["y"])
        if ca == cb:
            o = sorted(range(len(comps)), key=lambda ci: -len(comps[ci]))
            ca, cb = o[0], o[1]
        src = comp_cells(grid, board, comps[ca], layers)
        dst = comp_cells(grid, board, comps[cb], layers)
        got = None
        for tw, vd in classes:
            key = (net, tw)
            if key not in base_cache:
                base_cache[key] = grid.build_masks(net, tw, vd,
                                                   exempt_gfx_nets)
            blk0, vblk0 = base_cache[key]
            blk = {k: v.copy() for k, v in blk0.items()}
            vblk = vblk0.copy()
            tb = tw / 2 + board.clearance + grid.slop
            vb = vd / 2 + board.clearance + grid.slop
            for r in routes:                     # accepted routes obstruct
                if r["net"] == net:
                    continue
                for el in r["elements"]:
                    if el["type"] == "track":
                        g = grid.mask_seg(el["x1"], el["y1"], el["x2"],
                                          el["y2"], tb + el.get("w", 0.2) / 2)
                        if el["layer"] in blk:
                            blk[el["layer"]] |= g
                        vblk |= grid.mask_seg(el["x1"], el["y1"], el["x2"],
                                              el["y2"],
                                              vb + el.get("w", 0.2) / 2)
                    else:
                        d = el.get("dia", 0.5)
                        g = grid.mask_seg(el["x"], el["y"], el["x"], el["y"],
                                          tb + d / 2)
                        for k in blk:
                            blk[k] |= g
                        vblk |= grid.mask_seg(el["x"], el["y"], el["x"],
                                              el["y"], vb + d / 2)
            path = astar(grid, layers, src, dst, blk, vblk) or \
                astar(grid, layers, dst, src, blk, vblk)
            if not path:
                continue
            els = path_to_elements(grid, path, tw, vd)
            if els and els[0]["type"] == "track":
                s0 = comps[ca] if path[0] in src else comps[cb]
                els[0]["x1"], els[0]["y1"] = snap_point(
                    board, s0, els[0]["x1"], els[0]["y1"])
            if els and els[-1]["type"] == "track":
                s1 = comps[cb] if path[0] in src else comps[ca]
                els[-1]["x2"], els[-1]["y2"] = snap_point(
                    board, s1, els[-1]["x2"], els[-1]["y2"])
            if board.check_path(net, els, exempt_gfx_nets=exempt_gfx_nets):
                continue                        # the oracle says no
            got = els
            break
        if got is None:
            failed.append({"net": net, "a": e["a"], "b": e["b"]})
            continue
        routes.append({"net": net, "elements": got})
        board.commit(net, got)
    return routes, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geometry")
    ap.add_argument("airwires")
    ap.add_argument("-o", "--out", default="routes.json")
    ap.add_argument("--layers", default=None,
                    help="comma list; default: outer copper layers")
    ap.add_argument("--cell", type=float, default=0.05)
    ap.add_argument("--restarts", type=int, default=3)
    ap.add_argument("--classes", default="0.2:0.5,0.15:0.45,0.127:0.4")
    ap.add_argument("--exempt-gfx-nets", default="")
    args = ap.parse_args()

    classes = [tuple(float(v) for v in c.split(":"))
               for c in args.classes.split(",")]
    exempt = tuple(n for n in args.exempt_gfx_nets.split(",") if n)
    geo = json.load(open(args.geometry))
    layers = args.layers.split(",") if args.layers else \
        [l for l in geo["layers"] if l in ("F.Cu", "B.Cu")]
    air = json.load(open(args.airwires))

    best = None
    for seed in range(args.restarts):
        board = Board(json.load(open(args.geometry)))
        grid = Grid(board, layers, args.cell)
        routes, failed = route_all(board, grid, layers, air, classes, seed,
                                   exempt)
        print("seed %d: routed %d, failed %d %s"
              % (seed, len(routes), len(failed),
                 sorted({f["net"] for f in failed})))
        if best is None or len(failed) < len(best[1]):
            best = (routes, failed)
        if not failed:
            break
    routes, failed = best
    json.dump({"routes": routes, "failed": failed}, open(args.out, "w"),
              indent=1)
    print("BEST: routed %d, failed %d -> %s"
          % (len(routes), len(failed), args.out))


if __name__ == "__main__":
    main()
