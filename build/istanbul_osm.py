#!/usr/bin/env python3
# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Rebuild build/istanbul/network.geojson, the İstanbul routes and stations, from OpenStreetMap.

Every route and station is read from OpenStreetMap (© OpenStreetMap contributors, ODbL). LINES maps each record
in build/istanbul/lines.json to what draws it, in running order: route relations ("-id" walks one backwards), or for a line
OSM has no relation for, its track ways and station nodes. `cut` keeps the stretch between two stations, `closed`
marks a stretch out of service, `color` draws a part in another line's colour, `add` brings in the station a line
connects to from another relation. The station an extension starts from, and any listed under `existing`, is marked
`existing`: it is counted on the line it already belongs to.

    python3 build/istanbul_osm.py                   # fetch from the OSM API, write build/istanbul/network.geojson
    python3 build/istanbul_osm.py --cache osm.json  # save the OSM response, or reuse it if the file exists

Then run build/build.py to bring the change into data/.
"""
import argparse, json, math, os, re, sys, urllib.request

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "istanbul")
API = "https://api.openstreetmap.org/api/0.6/"

# line id -> parts; a part is {"rel": [...]} or {"ways": [...], "stations": [...]}, plus add / cut / closed / existing / color
LINES = {
    "M1A": [{"rel": [305496]}], "M1B": [{"rel": [4289712]}], "M2": [{"rel": [11341406]}], "m2-seyrantepe": [{"rel": [7719796]}],
    "M3": [{"rel": [4289797]}], "M4": [{"rel": [2396287]}], "M5": [{"rel": [11344904]}], "M6": [{"rel": [7719781]}],
    "M7": [{"rel": [15085833, 11799409], "closed": ("Mecidiyeköy", "Çağlayan")}], "M8": [{"rel": [14900216]}], "M9": [{"rel": [4289800]}], "M11": [{"rel": [15083964]}],
    "T1": [{"rel": [2962729]}], "T2": [{"rel": [301617]}], "T3": [{"rel": [2409338]}], "T4": [{"rel": [11344897]}], "T5": [{"rel": [12174616]}],
    "F1": [{"rel": [300961]}], "F2": [{"rel": [301616]}], "F3": [{"rel": [9476599]}], "F4": [{"rel": [14738977]}],
    "B1": [{"rel": [9987139]}], "B2": [{"rel": [14039181]}], "U3": [{"rel": [19587363]}],
    "M12": [{"rel": [15520693], "cut": ("Kazım Karabekir", "60. Yıl Parkı")}],
    "M13": [{"rel": [15547419], "cut": ("Emek", "Yenidoğan")}],
    "M14": [{"rel": [19750962], "cut": ("Altunizade", "Bosna Bulvarı")}],
    "m14-umraniye": [{"rel": [21922137], "add": [11477051649], "cut": ("Bosna Bulvarı", "Ümraniye Spor Köyü")}],
    "m7-kabatas": [{"rel": [15547431], "add": [7897142455], "cut": ("Yıldız", "Kabataş")}],
    "m7-kss": [{"rel": [13895537], "add": [7726641182, {"way": 1148481546, "name": "Atakent Mahallesi"}], "cut": ("Mahmutbey", "Kanuni Sultan Süleyman Hastanesi")}],
    "m7-esenyurt": [{"rel": [13895537], "cut": ("Kanuni Sultan Süleyman Hastanesi", "Esenyurt Meydanı")}],
    "m1b-halkali": [{"rel": [18690036], "add": [4959708627], "cut": ("Kirazlı", "Halkalı Üniversite")}],
    "T7": [{"rel": [18085217], "cut": ("Feshane", "Bayrampaşa Meydan")}],
    "M20": [{"rel": [15547627], "cut": ("Sefaköy", "TÜYAP")}],
    "M34": [{"rel": [18690177], "cut": ("Beylikdüzü", "Sabiha Gökçen Havalimanı")}],
    "M": [{"rel": [21451270]}], "T": [{"rel": [17001642]}],
    # M10 has no route relation yet: its tunnel, and stations mapped as building sites
    "M10": [{"ways": [825953000], "stations": [{"way": 547497824, "name": "Pendik Merkez"}, {"way": 947919975, "name": "Kaynarca Merkez"}, 6312448729]},
            {"ways": [1577243641], "stations": [7706729167, {"way": 947919980, "name": "Kaynarca Merkez"}], "existing": ["Tavşantepe"], "color": "#e91e76"}],
}

# station names that differ between lines of one station complex
SAME = {"Kadıköy - İDO- Metro": "Kadıköy", "Rumeli Hisarüstü": "Boğaziçi Üniversitesi/Hisarüstü", "Alibeyköy Metro": "Alibeyköy", "İncirli": "Bakırköy-İncirli",
        # and OSM names of unbuilt stations that differ from the official ones
        "60.Yıl Parkı": "60. Yıl Parkı", "Hastane": "Kanuni Sultan Süleyman Hastanesi", "Esenyurt Meydan": "Esenyurt Meydanı", "Halkalı - Üniversite": "Halkalı Üniversite"}


def dist(a, b):
    k = math.pi / 180
    return math.hypot((b[0] - a[0]) * k * math.cos((a[1] + b[1]) / 2 * k), (b[1] - a[1]) * k) * 6371000


def fetch(cache):
    if cache and os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    get = lambda path: json.load(urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "harita_ray/1.0 (+https://github.com/remrekoc/harita_ray)"}), timeout=120))["elements"]
    parts = [p for ps in LINES.values() for p in ps]
    els = [e for r in sorted({abs(r) for p in parts for r in p.get("rel", [])}) for e in get(f"relation/{r}/full.json")]
    sites = [s for p in parts for s in p.get("stations", []) + p.get("add", [])]
    els += [e for w in sorted({w for p in parts for w in p.get("ways", [])} | {s["way"] for s in sites if isinstance(s, dict)}) for e in get(f"way/{w}/full.json")]
    nodes = sorted({s for s in sites if isinstance(s, int)})
    els += get("nodes.json?nodes=" + ",".join(map(str, nodes))) if nodes else []
    if cache:
        json.dump({"elements": els}, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return {"elements": els}


def clean(name):
    name = re.sub(r"\s*\((M|T|F|B)\d+[A-Z]?\)$|\s+(Metro|Tramvay|Füniküler)?\s*(İstasyonu|Durağı)$", "", name.strip())
    return SAME.get(name, name)


def chain(ways, ordered):
    """Join ways (lists of node ids) into runs. Ordered ways follow the route; others are joined wherever they meet."""
    runs, fresh = [], False
    if ordered:
        for w in ways:
            if runs and fresh and runs[-1][0] in (w[0], w[-1]):  # the run's first way pointed backwards
                runs[-1].reverse()
            if runs and runs[-1][-1] == w[0]:
                runs[-1] += w[1:]
            elif runs and runs[-1][-1] == w[-1]:
                runs[-1] += w[-2::-1]
            else:
                runs.append(list(w))
                fresh = True
                continue
            fresh = False
        return runs
    ways = [list(w) for w in ways]
    while ways:
        run, grown = ways.pop(0), True
        while grown:
            grown = False
            for k, w in enumerate(ways):
                if w[0] == run[-1]: run += w[1:]
                elif w[-1] == run[-1]: run += w[-2::-1]
                elif w[-1] == run[0]: run = w + run[1:]
                elif w[0] == run[0]: run = w[::-1] + run[1:]
                else: continue
                ways.pop(k)
                grown = True
                break
        runs.append(run)
    return runs


def nearest(runs, at):
    """(run, vertex) of the track point closest to a station."""
    return min(((i, j) for i, r in enumerate(runs) for j in range(len(r))), key=lambda ij: dist(runs[ij[0]][ij[1]], at))


def length(run):
    return sum(dist(run[i - 1], run[i]) for i in range(1, len(run)))


def off(p, run):
    """Distance from a point to the nearest segment of a run."""
    k = math.cos(math.radians(p[1]))
    best = math.inf
    for a, b in zip(run, run[1:]):
        ax, ay, bx, by = (a[0] - p[0]) * k, a[1] - p[1], (b[0] - p[0]) * k, b[1] - p[1]
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best * math.pi / 180 * 6371000


def tidy(runs, ordered):
    """Drop short stubs; for unordered track also drop the second bore of twin tunnels and lay the runs end to end."""
    runs = [r for r in runs if length(r) > 150] or runs
    if ordered:  # ways listed out of order still meet end to end
        return chain(runs, False)
    kept = []
    for r in sorted(runs, key=length, reverse=True):
        if sum(any(off(p, k) < 80 for k in kept) for p in r) < len(r) / 2:
            kept.append(r)
    path = [kept.pop(0)]
    while kept:  # attach the run whose end lies closest to either end of the path
        d, i, end, flip = min((dist(path[-1][-1] if end else path[0][0], r[-1 if end == flip else 0]), i, end, flip)
                              for i, r in enumerate(kept) for end in (True, False) for flip in (False, True))
        r = kept.pop(i)[::-1 if flip else 1]
        path = path + [r] if end else [r] + path
    return path


def walk(part, osm):
    """Track as coordinate runs, and stations in running order, for one part of a line."""
    N, W, R = osm
    if "rel" in part:
        members = [(m, rid < 0) for rid in part["rel"] for m in (R[abs(rid)]["members"][::-1] if rid < 0 else R[abs(rid)]["members"])]
        ordered = any(m["role"].startswith("stop") for m, _ in members)
        track = [W[m["ref"]]["nodes"][::-1 if back else 1] for m, back in members
                 if m["type"] == "way" and m["ref"] in W and W[m["ref"]]["tags"].get("railway") not in (None, "platform") and not m["role"].startswith("platform")]
        stops = [m["ref"] for m, _ in members if m["type"] == "node" and m["ref"] in N
                 and (m["role"].startswith("stop") if ordered else m["role"] in ("station", "stop", "terminal", ""))]
    else:
        ordered, track, stops = False, [W[w]["nodes"] for w in part["ways"]], list(part["stations"])
    runs = tidy([[N[n]["at"] for n in r] for r in chain(track, ordered)], ordered)
    stops += part.get("add", [])  # a station the line connects to, mapped on another line
    out = []
    for n in stops:
        if isinstance(n, dict):  # a station mapped only as its building site: {"way": id, "name": ...}
            at = [N[k]["at"] for k in W[n["way"]]["nodes"][1:]]
            name, pos = n["name"], (sum(p[0] for p in at) / len(at), sum(p[1] for p in at) / len(at))
        else:
            name, pos = N[n]["tags"].get("name"), N[n]["at"]
        if name and (not out or out[-1]["name"] != clean(name)):
            out.append({"name": clean(name), "at": pos})
    if not ordered:  # stations listed in no particular order: sort them along the track
        out.sort(key=lambda s: nearest(runs, s["at"]))
    return runs, out


def cut(runs, stops, a, b):
    """The stretch of track and the stations from station a to station b, both included, running from a to b."""
    names = [s["name"] for s in stops]
    i, j = names.index(a), names.index(b)
    stops = stops[min(i, j):max(i, j) + 1]
    (ra, va), (rb, vb) = sorted([nearest(runs, stops[0]["at"]), nearest(runs, stops[-1]["at"])])
    out = [r for r in ([runs[ra][va:vb + 1]] if ra == rb else [runs[ra][va:]] + runs[ra + 1:rb] + [runs[rb][:vb + 1]]) if len(r) > 1]
    return ([r[::-1] for r in out[::-1]], stops[::-1]) if i > j else (out, stops)


def geom(runs):
    runs = [[[round(x, 6), round(y, 6)] for x, y in r] for r in runs]
    return {"type": "LineString", "coordinates": runs[0]} if len(runs) == 1 else {"type": "MultiLineString", "coordinates": runs}


def build(data, lines):
    N = {e["id"]: {"at": (e["lon"], e["lat"]), "tags": e.get("tags", {})} for e in data["elements"] if e["type"] == "node"}
    W = {e["id"]: {"nodes": e["nodes"], "tags": e.get("tags", {})} for e in data["elements"] if e["type"] == "way"}
    R = {e["id"]: e for e in data["elements"] if e["type"] == "relation"}
    feats, built = [], {}
    for line, parts in LINES.items():
        stations = []
        for part in parts:
            runs, stops = walk(part, (N, W, R))
            if "cut" in part:
                runs, stops = cut(runs, stops, *part["cut"])
            if "closed" in part:  # draw the closed stretch on its own, and the rest of the line around it
                a, b = sorted(part["closed"], key=[s["name"] for s in stops].index)
                feats.append({"type": "Feature", "properties": {"line": line, "closed": True}, "geometry": geom(cut(runs, stops, a, b)[0])})
                runs = cut(runs, stops, stops[0]["name"], a)[0] + cut(runs, stops, b, stops[-1]["name"])[0]
            feats.append({"type": "Feature", "properties": {"line": line, **({"color": part["color"]} if "color" in part else {})}, "geometry": geom(runs)})
            stations += [s for s in stops if s["name"] not in {t["name"] for t in stations}]
        built[line] = stations
    for line, stations in built.items():
        # the station an extension starts from is counted on the line it extends
        joins = {n for p in LINES[line] for n in p.get("existing", [])} | ({stations[0]["name"]} if lines[line].get("extension") else set())
        for s in stations:
            p = {"line": line, "name": s["name"], **({"existing": True} if s["name"] in joins else {})}
            feats.append({"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [round(s["at"][0], 6), round(s["at"][1], 6)]}})
    return feats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", help="OSM response file to save or reuse")
    args = ap.parse_args()
    lines = {l["id"]: l for l in json.load(open(os.path.join(DIR, "lines.json"), encoding="utf-8"))}
    if set(lines) - set(LINES):
        sys.exit(f"no OSM source for: {', '.join(sorted(set(lines) - set(LINES)))}")
    feats = build(fetch(args.cache), lines)
    out = os.path.join(DIR, "network.geojson")
    with open(out, "w", encoding="utf-8") as f:
        f.write('{"type": "FeatureCollection", "attribution": "© OpenStreetMap contributors, ODbL", "features": [\n')
        f.write(",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in feats))
        f.write("\n]}\n")
    print(f"{out}: {sum(x['geometry']['type'] != 'Point' for x in feats)} routes, {sum(x['geometry']['type'] == 'Point' for x in feats)} stations")


if __name__ == "__main__":
    main()
