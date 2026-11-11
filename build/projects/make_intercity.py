#!/usr/bin/env python3
# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Draw the intercity railway projects (under construction, planned, newly opened) from cached OSM data.

The records themselves (status, figures, sources) are hand-curated in build/projects/intercity.json. This script
draws each record's route and stations, writes build/projects/intercity.geojson and fills in each record's
`osm_ways` and `approx`. Rerun it after editing a record or refreshing the OSM cache:

    python3 build/projects/make_intercity.py

Geometry sources, in build/cache/:
  construction_ways.json  railway=construction (fetch.py)
  rail_ways.json          railway=rail (fetch.py): finished track, also where OSM already maps an unopened line
  proposed_rail.json      railway=proposed rail ways and construction/proposed station nodes (query in PROPOSED_Q)
  stations.json           station nodes (fetch.py)

A route is the shortest path over the selected ways through the given waypoints. Where OSM has no geometry the
record is drawn as straight segments through the waypoints and marked approx.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent
CACHE = BUILD / "cache"
sys.path.insert(0, str(BUILD))
import geo  # noqa: E402

TOL = 30          # simplification tolerance, metres
STATION_MAX = 1500  # a station node further than this from the drawn line is not placed

# Overpass query for proposed_rail.json (run with --fetch to refresh; curl because Python's TLS fails there)
PROPOSED_Q = """[out:json][timeout:600];area["ISO3166-1"="TR"][admin_level=2]->.tr;
(way["railway"="proposed"]["proposed"="rail"](area.tr);
 way["railway"="proposed"]["proposed:railway"="rail"](area.tr);
 way["railway"="proposed"][!"proposed"][!"proposed:railway"](area.tr);
 way["proposed:railway"="rail"](area.tr);
 node["railway"~"^(construction|proposed)$"]["construction"~"^(station|halt)$"](area.tr);
 node["railway"~"^(construction|proposed)$"]["proposed"~"^(station|halt)$"](area.tr);
 node["construction:railway"~"^(station|halt)$"](area.tr);
 node["proposed:railway"~"^(station|halt)$"](area.tr);
 node["construction:public_transport"="station"](area.tr);
 node["railway"="station"]["construction"="yes"](area.tr););
out geom qt;"""


def fetch_proposed():
    r = subprocess.run(["curl", "-s", "-f", "-m", "900", "-A", "turkiye-rail-map/1.0 (data build script)",
                        "--data-urlencode", "data@-", "https://overpass-api.de/api/interpreter"],
                       input=PROPOSED_Q.encode(), capture_output=True)
    if r.returncode:
        raise SystemExit(f"curl exit {r.returncode}")
    json.loads(r.stdout)  # data only: fail here if it is not JSON
    (CACHE / "proposed_rail.json").write_bytes(r.stdout)


def load(name):
    return json.loads((CACHE / f"{name}.json").read_text())["elements"]


WAYS = {"construction": [e for e in load("construction_ways") if e["type"] == "way"],
        "rail": [e for e in load("rail_ways") if e["type"] == "way"],
        "proposed": [e for e in load("proposed_rail") if e["type"] == "way"]}
NODES = {e["id"]: e for e in load("stations") + [e for e in load("proposed_rail") if e["type"] == "node"]}


def pt(ref):
    """[lon, lat] of a station node id, or the point itself."""
    if isinstance(ref, int):
        n = NODES[ref]
        return [n["lon"], n["lat"]]
    return list(ref)


def pick(src, name, bbox=None):
    """Ways of one cache whose name matches the regex, optionally inside bbox (lon0, lat0, lon1, lat1)."""
    rx = re.compile(name)
    out = []
    for e in WAYS[src]:
        if not rx.search(e.get("tags", {}).get("name") or ""):
            continue
        if bbox:
            b = e["bounds"]
            if b["maxlon"] < bbox[0] or b["minlon"] > bbox[2] or b["maxlat"] < bbox[1] or b["minlat"] > bbox[3]:
                continue
        out.append(e)
    return out


def join_gaps(g, d=5000):
    """Link separate pieces of the graph where they come closest, if within d metres: OSM maps a line under
    construction in pieces, with gaps where a stretch is unmapped or tagged differently."""
    while True:
        g.components()
        pieces = {}
        for n, c in g.comp.items():
            pieces.setdefault(c, []).append(n)
        best = None
        for c, members in sorted(pieces.items(), key=lambda kv: len(kv[1])):  # the smallest piece first
            for a in members:
                for dd, _, b in g.grid.near(g.pos[a], d):
                    if g.comp[b] != c:
                        if best is None or dd < best[0]:
                            best = (dd, a, b)
                        break
            if best:
                break
        if not best:
            break
        dd, a, b = best
        g.adj[a].append((b, dd * 1.5, False))
        g.adj[b].append((a, dd * 1.5, False))
    g.big = set(g.comp.values())  # every piece counts: these are small graphs of one line


def route(ways, via):
    """Shortest path over `ways` (pairs of way, cost factor) through the waypoints.

    Returns (coords, ids of the ways it runs on)."""
    g = geo.RailGraph()
    for w, cost in ways:
        g.add_way(w["nodes"], [[p["lon"], p["lat"]] for p in w["geometry"]], cost=cost)
    g.heal(30)
    join_gaps(g)
    node_at = {tuple(p): n for n, p in g.pos.items()}
    line = []
    for a, b in zip(via, via[1:]):
        pa, pb = pt(a), pt(b)
        # start and end on track near the waypoint: within 300 m of the nearest track
        r = max(geo.dist(pb, g.pos[g.nearest(pb, 30000)]), geo.dist(pa, g.pos[g.nearest(pa, 30000)])) + 300
        part = g.route_pts(pa, pb, r=r)
        if not part:
            raise SystemExit(f"no route between {a} and {b}")
        line += part if not line else part[1:]
    path = [node_at.get(tuple(p)) for p in line]
    pairs = {frozenset(x) for x in zip(path, path[1:])}
    used = [w["id"] for w, _ in ways if any(frozenset(x) in pairs for x in zip(w["nodes"], w["nodes"][1:]))]
    return line, used


# ---------------------------------------------------------------- the routes
# segments: drawn in order and joined into one line.
#   {"ways": [(cache, name regex, bbox?)], "via": [waypoints]}  routed over OSM ways
#   {"straight": [waypoints]}                                   straight segments (approximate)
# stations: (official name, station node id or "start"/"end", existing?) — sorted along the line afterwards.
# Station node ids come from stations.json or proposed_rail.json.
KAPIKULE = r"^İstanbul-Kapıkule [Yy]üksek [Ss]tandartlı demiryolu"
AFYON = (30.5284175, 38.8041729)
GEOM = {
    # ---- Halkalı – Kapıkule
    "yht-cerkezkoy-kapikule": dict(
        segments=[{"ways": [("rail", KAPIKULE, (26.3, 41.2, 28.05, 41.8)),
                            ("construction", r"^Pehlivanköy – Svilengrad"),
                            ("rail", r"^Pehlivanköy – Svilengrad", (26.3, 41.6, 26.6, 41.8))],
                   "via": [13140863305, 12112974486, 12112984240, 12112964591, 11132878357, 11132878356]}],
        stations=[("Çerkezköy", 13140863305, True), ("Büyükkarıştıran", 12112974486, False),
                  ("Lüleburgaz", 12112984240, False), ("Babaeski", 12112964591, False),
                  ("Edirne", 11132878357, True), ("Kapıkule", 11132878356, False)]),
    "yht-ispartakule-cerkezkoy": dict(
        # where the new line runs on the old corridor OSM still maps the old track (İstanbul – Pythion): it fills
        # the gaps, at a higher cost so that the route keeps to the new track wherever that is mapped
        segments=[{"ways": [("construction", KAPIKULE, (28.0, 41.0, 28.72, 41.3)), ("rail", KAPIKULE, (27.98, 41.25, 28.05, 41.3)),
                            ("rail", r"^İstanbul – Pythion", (27.98, 41.0, 28.72, 41.3), 1.4)],
                   "via": [9665946458, 13140863305]}],
        stations=[("Ispartakule", 9665946458, False), ("Bahçeşehir", 9665946456, False),
                  ("Çatalca", 2625916043, False), ("Çerkezköy", 13140863305, True)]),
    "yht-halkali-ispartakule": dict(
        segments=[{"ways": [("construction", KAPIKULE, (28.69, 41.0, 28.8, 41.1))], "via": [2253949587, 9665946458]}],
        stations=[("Halkalı", 2253949587, True), ("Ispartakule", 9665946458, False)]),
    # ---- İstanbul Kuzey Demir Yolu Geçişi
    "hat-cayirova-catalca": dict(
        segments=[{"ways": [("proposed", r"INRAIL")], "via": [5085864847, 2625916043]}],
        stations=[("Çayırova", 5085864847, True), ("Çatalca", 2625916043, False)]),
    # ---- Bandırma – Bursa – Yenişehir – Osmaneli
    "yht-osmaneli-bursa": dict(
        segments=[{"ways": [("rail", r"^Osmaneli – Bursa – Bandırma")],
                   "via": [11953552080, 11953552077, 13360210320, 11953547054, 12523026533]}],
        stations=[("Osmaneli", 11953552080, False), ("Yenişehir", 11953552077, False),
                  ("Yenişehir Havalimanı", 13360210320, False), ("Gürsu", 11953547054, False),
                  ("Bursa", 12523026533, False)]),
    "yht-bursa-bandirma": dict(
        segments=[{"ways": [("rail", r"^Osmaneli – Bursa – Bandırma", (28.8, 40.2, 28.95, 40.35)),
                            ("construction", r"^Osmaneli – Bursa – Bandırma"),
                            ("rail", r"^Manisa-Bandırma demiryolu", (27.9, 40.3, 28.0, 40.4))],
                   "via": [12523026533, 13968760027, 13968760026, 13968760025, 1033939388, 13066965373]}],
        stations=[("Bursa", 12523026533, False), ("Teknosab", 13968760027, False), ("Karacabey", 13968760026, False),
                  ("Dağkadı", 13968760025, False), ("Kuşcenneti", 1033939388, True), ("Bandırma", 13066965373, True)]),
    # ---- Ankara – İzmir
    # the two records meet where the new line passes Afyonkarahisar: the point of it nearest the city station
    "yht-polatli-afyonkarahisar": dict(
        segments=[{"ways": [("construction", r"^Polatlı [–-] İzmir"),
                            ("rail", r"^Ankara - İstanbul|^Polatlı - Konya|^Sakarya Viyadüğü", (31.95, 39.25, 32.25, 39.65))],
                   "via": [10134127154, AFYON]}],
        stations=[("Polatlı", 10134127154, True), ("Afyonkarahisar", AFYON, False)]),
    # west of the mapped construction the line follows the Manisa – Menemen corridor (official stations Muradiye,
    # Ayvacık, Emiralem, Menemen, Ekim 2025), drawn over the existing track there
    "yht-afyonkarahisar-izmir": dict(
        # (OSM maps a loop past the old Manisa station as well; the route keeps to the through line north of it)
        segments=[{"ways": [("construction", r"^Polatlı [–-] İzmir"), ("rail", r"^İzmir-Afyonkarahisar demiryolu", (27.05, 38.58, 27.30, 38.67))],
                   "via": [AFYON, 12344626530]}],
        stations=[("Afyonkarahisar", AFYON, False), ("Uşak", 1033324723, False), ("Salihli", 2629880622, False),
                  ("Manisa", 168129480, False), ("Menemen", 12344626530, True)]),
    # ---- Konya – Karaman – Ulukışla
    "yht-karaman-ulukisla": dict(
        segments=[{"ways": [("rail", r"^Konya – Ulukışla", (33.2, 37.1, 34.6, 37.7)),
                            ("construction", r"^Konya – Ulukışla")],
                   "via": [1861513015, 2643801218, 4929219587, 2643792763, 2711219111, 2718931904]}],
        stations=[("Karaman", 1861513015, True), ("Sudurağı", 2643801218, False), ("Ayrancı", 4929219587, False),
                  ("Ereğli", 2643792763, False), ("Çakmak", 2711219111, False), ("Ulukışla", 2718931904, True)]),
    "yht-aksaray-ulukisla-yenice": dict(
        segments=[{"ways": [("proposed", r"Aksaray"), ("construction", r"^Konya – Ulukışla"), ("rail", r"^Konya – Ulukışla", (34.0, 37.4, 34.6, 37.7))],
                   "via": [(33.9567, 38.3112), 2718931904]},
                  {"straight": [2718931904, 442532879, 2639614523]}],
        stations=[("Aksaray", "start", False), ("Yenice", 2639614523, True)]),
    # ---- Mersin – Adana – Osmaniye – Gaziantep
    "yht-mersin-adana": dict(
        segments=[{"ways": [("construction", r"^Mersin-Adana-Gaziantep", (34.5, 36.7, 35.4, 37.1)),
                            ("rail", r"^Mersin-Adana-Gaziantep", (34.5, 36.7, 35.4, 37.1))],
                   "via": [2596542075, 2639614349, 2726063373]}],
        stations=[("Mersin", 2596542075, True), ("Tarsus", 2639614349, False), ("Adana", 2726063373, True)]),
    # the airport branch leaves the Mersin – Adana line near Yenice; OSM maps both tracks, the route keeps to one
    "yht-cukurova-havalimani": dict(
        segments=[{"ways": [("proposed", r"^Çukurova Havalimanı şube")], "via": [(35.0137, 36.9610), 14138021081]}],
        stations=[("Çukurova Havalimanı", 14138021081, False)]),
    "yht-adana-gaziantep": dict(
        segments=[{"ways": [("construction", r"^Mersin-Adana-Gaziantep|^Nurdağı Tüneli", (35.25, 36.8, 37.5, 37.4)),
                            ("rail", r"^Mersin-Adana-Gaziantep", (35.25, 36.8, 37.5, 37.4)),
                            ("rail", r"", (35.30, 36.97, 35.40, 37.02), 1.2),   # through Adana on the existing line
                            ("rail", r"", (37.3, 37.05, 37.4, 37.2))],           # Başpınar – Gaziantep (Gaziray)
                   "via": [2726063373, 10159892609, 10160022343]}],
        stations=[("Adana", 2726063373, True), ("Osmaniye", 125326513, False), ("Gaziantep", 10160022343, True)]),
    "yht-toprakkale-iskenderun": dict(
        segments=[{"straight": [13142562856, 13149734633]}],
        stations=[("Toprakkale", 13142562856, False), ("İskenderun", 13149734633, False)]),
    "hat-payas-hassa": dict(
        segments=[{"ways": [("proposed", r"^Dörtyol - Hassa")], "via": [(36.2049641, 36.7170054), (36.430053, 36.6547834)]}],
        stations=[]),
    # ---- Kalkınma Yolu
    "yht-gaziantep-sanliurfa": dict(
        segments=[{"ways": [("proposed", r"^Gaziantep-Şanlıurfa"), ("rail", r"", (37.37, 37.0, 37.46, 37.12))],
                   "via": [10160022343, (38.66, 37.1296)]}],
        stations=[("Gaziantep", 10160022343, True), ("Şanlıurfa", "end", False)]),
    "yht-sanliurfa-mardin": dict(
        segments=[{"ways": [("proposed", r"^Şanlıurfa-Mardin")], "via": [(38.7581, 37.2316), (40.6929, 37.2472)]}],
        stations=[("Şanlıurfa", "start", False), ("Mardin", "end", False)]),
    "yht-malatya-narli": dict(
        segments=[{"straight": [11309220632, 2785467907]}],
        stations=[("Malatya", 11309220632, False), ("Narlı", 2785467907, False)]),
    # ---- Kayseri, Çorum, Sivas
    "yht-yerkoy-kayseri": dict(
        segments=[{"ways": [("construction", r"^Yerköy-Kayseri"),
                            ("rail", r"^Ankara-Kars demiryolu", (35.25, 38.7, 35.5, 38.8)),
                            ("rail", r"^Ankara - Sivas", (34.4, 39.6, 34.55, 39.75))],
                   "via": [9093354809, 11309230921]}],
        # Şefaatli, Yenifakılı, Himmetdede: the old stations of those towns, placed only if the new line passes them
        stations=[("Yerköy", 9093354809, True), ("Şefaatli", 2319789289, False), ("Yenifakılı", 2679017576, False),
                  ("Himmetdede", 1203605825, False), ("Kayseri", 11309230921, True)]),
    "yht-delice-corum": dict(
        segments=[{"ways": [("construction", r"^Delice-Çorum-Samsun")], "via": [(33.99, 39.88), 14159710968]}],
        stations=[("Delice", "start", False), ("Çorum", 14159710968, False)]),
    "yht-corum-havza": dict(
        # OSM's proposed line starts 4 km north of the Çorum station of the Delice – Çorum line
        segments=[{"straight": [14159710968, (34.9076, 40.5515)]},
                  {"ways": [("proposed", r"^Delice-Çorum-Samsun yüksek")], "via": [(34.9076, 40.5515), 8634566619]}],
        stations=[("Çorum", 14159710968, False), ("Havza", "end", False)]),
    "yht-sivas-zara": dict(
        segments=[{"ways": [("construction", r"^Ankara - Sivas Yüksek Hızlı Tren Hattı İnşaatı|^Sivas - Zara - Erzincan")],
                   "via": [(36.875, 39.715), (37.36, 39.84)]}],
        stations=[]),  # the mapped track starts at a junction 10 km west of Sivas station and stops short of Zara
    # ---- doğu
    "hat-kars-dilucu": dict(
        segments=[{"ways": [("construction", r"^Kars-Dilucu"),
                            ("rail", r"^Kars-Gümrü-Tiflis|^Ankara-Kars", (43.05, 40.55, 43.35, 40.72))],  # Kars – Subatan
                   "via": [2005962642, (44.80, 39.67)]}],
        stations=[("Kars", 2005962642, True), ("Dilucu", "end", False)]),
    # ---- a service on existing lines that started in 2025
    "hat-turistik-karaelmas": dict(
        segments=[{"ways": [("rail", r"^Ankara-Kars demiryolu", (32.8, 39.85, 33.45, 40.0)),
                            ("rail", r"", (32.83, 39.9, 32.97, 39.95), 1.3),
                            ("rail", r"^Irmak-Zonguldak demiryolu|^Batıbel Tüneli|^Göllüce Köprüsü")],
                   "via": [9747501490, 7933918564, 1811029435, 2627502412, 947975087, 2205115409, 13480008012]}],
        stations=[("Ankara", 9747501490, True), ("Kalecik", 1811029435, True), ("Çankırı", 2627502412, True),
                  ("Çerkeş", 947975087, True), ("Yeşilyenice", 2205115409, True), ("Zonguldak", 13480008012, True)]),
    "hat-kurtalan-siirt": dict(
        segments=[{"ways": [("proposed", r"^Siirt-Kurtalan"), ("proposed", r"^$", (41.85, 37.88, 41.92, 37.95))],
                   "via": [13092695117, 12621085718, 12621079984]}],
        stations=[("Yeni Kurtalan", 13092695117, False), ("Havalimanı-Üniversite", 12621085718, False),
                  ("Siirt", 12621079984, False)]),
}


def r5(p):
    return [round(p[0], 5), round(p[1], 5)]


def build(lid, spec):
    line, used, approx = [], [], False
    for seg in spec["segments"]:
        if "straight" in seg:
            part = [pt(p) for p in seg["straight"]]
            approx = True
        else:
            ways = []
            for src, name, bbox, cost in (tuple(w) + (None, 1.0)[len(w) - 2:] for w in seg["ways"]):
                ways += [(w, cost) for w in pick(src, name, bbox) if all(w is not x for x, _ in ways)]
            part, ids = route(ways, seg["via"])
            used += [i for i in ids if i not in used]
        line += part if not line else part[1:]
    cum = geo.cumul(line)
    pts = []
    for name, ref, existing in spec["stations"]:
        # "start"/"end": a route end, not a known station location; a point (lon, lat): a section boundary
        at = line[0] if ref == "start" else line[-1] if ref == "end" else pt(ref)
        d, s = geo.project(at, line, cum)
        if d > STATION_MAX:
            print(f"  ! {lid}: {name} is {d:.0f} m from the line, not placed", file=sys.stderr)
            continue
        pts.append((s, name, at, existing, not isinstance(ref, int)))
    pts.sort(key=lambda t: t[0])
    return line, used, approx, pts


def main():
    if "--fetch" in sys.argv:
        fetch_proposed()
    data = json.loads((HERE / "intercity.json").read_text())
    feats = []
    for rec in data["lines"]:
        spec = GEOM.get(rec["id"])
        if not spec:
            print(f"  ! no geometry for {rec['id']}", file=sys.stderr)
            continue
        line, used, approx, pts = build(rec["id"], spec)
        rec["osm_ways"] = used
        rec["approx"] = approx
        if not approx:
            rec.pop("approxNote", None)
        simple = [r5(p) for p in geo.simplify(line, TOL)]
        feats.append({"type": "Feature", "properties": {"line": rec["id"]},
                      "geometry": {"type": "LineString", "coordinates": simple}})
        for _, name, at, existing, loose in pts:
            props = {"line": rec["id"], "name": name}
            if existing:
                props["existing"] = True
            if loose:
                props["approx"] = True  # placed at the end of the drawn route, not at a mapped station
            feats.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": r5(at)}})
        print(f"{rec['id']:30s} {geo.length(line) / 1000:6.1f} km drawn, {len(used):3d} ways, {len(pts)} stations"
              + (" (approx)" if approx else ""))
    (HERE / "intercity.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    (HERE / "intercity.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                       ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
