# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Small geometry helpers for the build: distances, chaining ways into lines, projection, simplification."""
import heapq
import math
from collections import defaultdict

R = 6371000.0


def dist(a, b):
    """Metres between two [lon, lat] points (equirectangular, fine at these scales)."""
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(math.radians(b[0] - a[0]) * k, math.radians(b[1] - a[1])) * R


def length(c):
    return sum(dist(c[i - 1], c[i]) for i in range(1, len(c)))


def seg_project(p, a, b):
    """(distance in metres, fraction along a→b) of the point on segment a–b closest to p."""
    k = math.cos(math.radians(p[1]))
    ax, ay, bx, by, px, py = a[0] * k, a[1], b[0] * k, b[1], p[0] * k, p[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    q = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    return dist(p, q), t


def project(p, c, cum=None):
    """Distance from p to polyline c and the position (metres from the start) of the nearest point."""
    if cum is None:
        cum = cumul(c)
    best = (float("inf"), 0)
    for i in range(1, len(c)):
        d, t = seg_project(p, c[i - 1], c[i])
        if d < best[0]:
            best = (d, cum[i - 1] + t * (cum[i] - cum[i - 1]))
    return best


def cumul(c):
    out = [0.0]
    for i in range(1, len(c)):
        out.append(out[-1] + dist(c[i - 1], c[i]))
    return out


def cut(c, s0, s1):
    """The part of polyline c between positions s0 < s1 (metres from the start)."""
    cum = cumul(c)
    out = []

    def at(s):
        for i in range(1, len(c)):
            if cum[i] >= s:
                f = (s - cum[i - 1]) / ((cum[i] - cum[i - 1]) or 1)
                return [c[i - 1][0] + (c[i][0] - c[i - 1][0]) * f, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * f]
        return c[-1]
    out.append(at(s0))
    for i in range(len(c)):
        if s0 < cum[i] < s1:
            out.append(c[i])
    out.append(at(s1))
    return out


def simplify(c, tol):
    """Douglas–Peucker with a tolerance in metres."""
    if len(c) < 3:
        return c
    keep = [False] * len(c)
    keep[0] = keep[-1] = True
    stack = [(0, len(c) - 1)]
    while stack:
        i, j = stack.pop()
        best, bi = 0, -1
        for k in range(i + 1, j):
            d, _ = seg_project(c[k], c[i], c[j])
            if d > best:
                best, bi = d, k
        if best > tol and bi > 0:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(c, keep) if k]


def chain_ways(ways):
    """Join ways (lists of (node id, [lon, lat])) into as few polylines as possible, each way used once.

    Walks the graph of way ends: a chain runs on through nodes where exactly two ways meet."""
    ends = defaultdict(list)
    for i, w in enumerate(ways):
        if len(w) < 2:
            continue
        ends[w[0][0]].append(i)
        ends[w[-1][0]].append(i)
    used = [False] * len(ways)
    lines = []

    def walk(start_node, i):
        w = ways[i]
        seq = w if w[0][0] == start_node else w[::-1]
        out = list(seq)
        used[i] = True
        node = seq[-1][0]
        while len(ends[node]) == 2:
            nxt = [j for j in ends[node] if not used[j]]
            if not nxt:
                break
            j = nxt[0]
            wj = ways[j]
            seqj = wj if wj[0][0] == node else wj[::-1]
            out += seqj[1:]
            used[j] = True
            node = seqj[-1][0]
        return out
    # start from chain ends (nodes that are not simple pass-throughs), then whatever loops remain
    for node, ws in list(ends.items()):
        if len(ws) != 2:
            for i in ws:
                if not used[i]:
                    lines.append(walk(node, i))
    for i, w in enumerate(ways):
        if not used[i] and len(w) >= 2:
            lines.append(walk(w[0][0], i))
    return [[p for _, p in ln] for ln in lines]


def order_ways(ways):
    """Chain ways in the order a route relation lists them, flipping each to meet the previous one.

    Returns a list of parts; a new part starts wherever consecutive ways do not touch."""
    parts, cur = [], []
    for w in ways:
        if len(w) < 2:
            continue
        if not cur:
            cur = list(w)
            continue
        a, b = cur[0][0], cur[-1][0]
        if w[0][0] == b:
            cur += w[1:]
        elif w[-1][0] == b:
            cur += w[::-1][1:]
        elif len(parts) == 0 and len(cur) and (w[0][0] == a or w[-1][0] == a):
            # the first way was the wrong way round
            cur = cur[::-1]
            cur += (w if w[0][0] == cur[-1][0] else w[::-1])[1:]
        else:
            parts.append(cur)
            cur = list(w)
    if cur:
        parts.append(cur)
    return parts


class Grid:
    """A coarse spatial hash of points, for 'is anything within d metres' lookups."""

    def __init__(self, cell=0.005):
        self.cell = cell
        self.g = defaultdict(list)

    def key(self, p):
        return (int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell)))

    def add(self, p, item=None):
        self.g[self.key(p)].append((p, item))

    def near(self, p, d):
        kx, ky = self.key(p)
        r = 1 + int(d / (self.cell * 111000 * 0.75))
        out = []
        for x in range(kx - r, kx + r + 1):
            for y in range(ky - r, ky + r + 1):
                for q, it in self.g.get((x, y), ()):
                    dd = dist(p, q)
                    if dd <= d:
                        out.append((dd, q, it))
        out.sort(key=lambda t: t[0])
        return out


def densify_grid(lines, step=60, cell=0.005):
    g = Grid(cell)
    for c in lines:
        for i in range(len(c)):
            g.add(c[i])
            if i:
                n = int(dist(c[i - 1], c[i]) // step)
                for k in range(1, n + 1):
                    f = k / (n + 1)
                    g.add([c[i - 1][0] + (c[i][0] - c[i - 1][0]) * f, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * f])
    return g


class RailGraph:
    """Rail network as a graph of OSM nodes, for routing a service between stations."""

    def __init__(self):
        self.adj = defaultdict(list)
        self.pos = {}
        self.grid = Grid(0.01)

    def add_way(self, nodes, coords, hs=False, cost=1.0):
        """hs: high-speed track; cost: a factor on its length (track under construction costs more)."""
        for i, (n, p) in enumerate(zip(nodes, coords)):
            if n not in self.pos:
                self.pos[n] = p
                self.grid.add(p, n)
            if i:
                a = nodes[i - 1]
                d = dist(coords[i - 1], p) * cost
                self.adj[a].append((n, d, hs))
                self.adj[n].append((a, d, hs))

    def heal(self, d=30):
        """Join dead ends to track within d metres: OSM ways that meet without sharing a node."""
        n = 0
        for a in [k for k, v in self.adj.items() if len(v) == 1]:
            nbr = {m for m, _, _ in self.adj[a]}
            for dd, _, b in self.grid.near(self.pos[a], d):
                if b != a and b not in nbr:
                    hs = self.adj[a][0][2]
                    self.adj[a].append((b, dd, hs))
                    self.adj[b].append((a, dd, hs))
                    n += 1
                    break
        return n

    def _near_in_graph(self, a, b, limit):
        """Is b within `limit` metres of a along the track?"""
        seen = {a: 0}
        pq = [(0, a)]
        while pq:
            g, n = heapq.heappop(pq)
            if n == b:
                return True
            if g > seen.get(n, 1e18):
                continue
            for m, d, _ in self.adj[n]:
                ng = g + d
                if ng <= limit and ng < seen.get(m, 1e18):
                    seen[m] = ng
                    heapq.heappush(pq, (ng, m))
        return False

    def bridge(self, d=600, only=None):
        """Join each dead end to the nearest track within d metres that it cannot reach along the rails within a
        few kilometres: a gap in the mapping (a missing piece, or a stretch tagged differently)."""
        n = 0
        for a in [k for k, v in self.adj.items() if len(v) == 1 and (only is None or k in only)]:
            for dd, _, b in self.grid.near(self.pos[a], d)[:40]:
                if b != a and not self._near_in_graph(a, b, max(3000, dd * 4)):
                    hs = self.adj[a][0][2]
                    self.adj[a].append((b, dd * 1.5, hs))
                    self.adj[b].append((a, dd * 1.5, hs))
                    n += 1
                    break
        return n

    def components(self):
        """Label connected components; nearest() then only snaps to nodes of large ones."""
        self.comp = {}
        sizes = {}
        for start in self.pos:
            if start in self.comp:
                continue
            stack, n = [start], 0
            self.comp[start] = start
            while stack:
                x = stack.pop()
                n += 1
                for y, _, _ in self.adj[x]:
                    if y not in self.comp:
                        self.comp[y] = start
                        stack.append(y)
            sizes[start] = n
        self.big = {max(sizes, key=sizes.get)}  # the national network; detached pieces are mapping gaps

    def nearest(self, p, d=4000):
        for _, _, n in self.grid.near(p, d):
            if not hasattr(self, "big") or self.comp.get(n) in self.big:
                return n
        return None

    def route(self, a, b, prefer_hs=None, prefer=()):
        """Shortest path a→b; prefer_hs True favours high-speed track, False avoids it."""
        if a is None or b is None:
            return None
        goal = self.pos[b]
        pq = [(0, 0, a)]
        best = {a: 0}
        prev = {}
        while pq:
            f, g, n = heapq.heappop(pq)
            if n == b:
                break
            if g > best.get(n, 1e18):
                continue
            for m, d, hs in self.adj[n]:
                w = d
                if prefer and n in prefer and m in prefer:
                    w *= 0.6
                if prefer_hs is True and not hs:
                    w *= 1.15
                elif prefer_hs is False and hs:
                    w *= 2.5
                ng = g + w
                if ng < best.get(m, 1e18):
                    best[m] = ng
                    prev[m] = n
                    heapq.heappush(pq, (ng + dist(self.pos[m], goal) * (0.55 if prefer else 0.9), ng, m))
        if b not in best:
            return None
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        return [self.pos[n] for n in reversed(path)]

    def route_pts(self, pa, pb, prefer_hs=None, prefer=(), r=800):
        """Shortest path between two places rather than two nodes: it may start on any track within r metres of
        pa and end on any within r of pb, so a station that sits beside parallel tracks does not force a detour
        to wherever those tracks happen to be joined."""
        src = [(d, n) for d, _, n in self.grid.near(pa, r) if self.comp.get(n) in self.big]
        dst = {n: d for d, _, n in self.grid.near(pb, r) if self.comp.get(n) in self.big}
        if not src or not dst:
            a, b = self.nearest(pa, 10000), self.nearest(pb, 10000)
            if a is None or b is None:
                return None
            src, dst = [(0, a)], {b: 0}
        pq, best, prev = [], {}, {}
        for d, n in src:
            g = d * 2
            if g < best.get(n, 1e18):
                best[n] = g
                heapq.heappush(pq, (g + max(0, dist(self.pos[n], pb) - r) * 0.55, g, n))
        end, end_cost = None, 1e18
        while pq:
            f, g, n = heapq.heappop(pq)
            if f >= end_cost:
                break
            if g > best.get(n, 1e18):
                continue
            if n in dst and g + dst[n] * 2 < end_cost:
                end, end_cost = n, g + dst[n] * 2
            for m, d, hs in self.adj[n]:
                w = d
                if prefer and n in prefer and m in prefer:
                    w *= 0.6
                if prefer_hs is True and not hs:
                    w *= 1.15
                elif prefer_hs is False and hs:
                    w *= 2.5
                ng = g + w
                if ng < best.get(m, 1e18):
                    best[m] = ng
                    prev[m] = n
                    heapq.heappush(pq, (ng + max(0, dist(self.pos[m], pb) - r) * 0.55, ng, m))
        if end is None:
            return None
        path = [end]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        return [self.pos[n] for n in reversed(path)]
