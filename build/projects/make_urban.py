#!/usr/bin/env python3
# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Draw the urban rail projects outside İstanbul (under construction, planned) from cached OSM data.

The records themselves (status, figures, sources) are hand-curated in build/projects/urban.json: `lines` go on the
map, `pending` are drawn here too but the map ignores them until they are decided, `rejected` lists what was left
out and why. This script draws each record's route and stations, writes build/projects/urban.geojson and fills in
each record's `osm_ways` and `approx`. Rerun it after editing a record or refreshing the OSM cache:

    python3 build/projects/make_urban.py

Geometry sources, in build/cache/:
  construction_ways.json  railway=construction (fetch.py)
  proposed_urban.json     railway=proposed/construction ways of metro, light rail and tram lines (query in URBAN_Q)
  stations.json           station and stop nodes (fetch.py)
  proposed_rail.json      construction/proposed station nodes (make_intercity.py)

A route is the shortest path over the selected ways through the given waypoints, so that a line mapped as two
tracks is drawn once. Where OSM has no geometry the record is drawn as straight segments through known points and
marked approx; a record with no known points at all is left undrawn (the build then skips it).
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent
CACHE = BUILD / "cache"
sys.path.insert(0, str(BUILD))
import geo  # noqa: E402

TOL = 5            # simplification tolerance, metres
STATION_MAX = 600  # a station node further than this from the drawn line is not placed

# Overpass query for proposed_urban.json (run with --fetch to refresh)
URBAN_Q = """[out:json][timeout:600];area["ISO3166-1"="TR"][admin_level=2]->.tr;
(way["railway"="proposed"]["proposed"~"^(subway|light_rail|tram|monorail)$"](area.tr);
 way["proposed:railway"~"^(subway|light_rail|tram|monorail)$"](area.tr);
 way["railway"="construction"]["construction"~"^(subway|light_rail|tram|monorail)$"](area.tr);
 way["construction:railway"~"^(subway|light_rail|tram|monorail)$"](area.tr);
 way["railway"="construction"][!"construction"][!"construction:railway"](area.tr););
out geom qt;"""


def fetch_urban():
    r = subprocess.run(["curl", "-s", "-f", "-m", "900", "-A", "turkiye-rail-map/1.0 (data build script)",
                        "--data-urlencode", "data@-", "https://overpass-api.de/api/interpreter"],
                       input=URBAN_Q.encode(), capture_output=True)
    if r.returncode:
        raise SystemExit(f"curl exit {r.returncode}")
    json.loads(r.stdout)
    (CACHE / "proposed_urban.json").write_bytes(r.stdout)


def load(name):
    return json.loads((CACHE / f"{name}.json").read_text())["elements"]


WAYS = {"construction": [e for e in load("construction_ways") if e["type"] == "way" and "geometry" in e],
        "proposed": [e for e in load("proposed_urban") if e["type"] == "way" and "geometry" in e]}
BY_ID = {e["id"]: e for src in WAYS.values() for e in src}
NODES = {e["id"]: e for e in load("stations") + [e for e in load("proposed_rail") if e["type"] == "node"]}
# named station platforms of proposed lines (areas): their centre stands in for a station node
for e in WAYS["proposed"]:
    t = e.get("tags", {})
    if t.get("name") and (t.get("railway") == "platform" or t.get("public_transport") == "platform"):
        c = e["geometry"]
        NODES[f"w{e['id']}"] = {"lon": sum(p["lon"] for p in c) / len(c), "lat": sum(p["lat"] for p in c) / len(c), "tags": t}


def pt(ref):
    """[lon, lat] of a station node id (or "w<platform way id>"), or the point itself."""
    if isinstance(ref, (int, str)):
        n = NODES[ref]
        return [n["lon"], n["lat"]]
    return list(ref)


def pick(sel):
    """Ways for one selector: ("ids", [way ids]) or (cache, name regex, bbox (lon0, lat0, lon1, lat1) or None)."""
    if sel[0] == "ids":
        return [BY_ID[i] for i in sel[1]]
    src, name, bbox = (tuple(sel) + (None,))[:3]
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


def dangling(ways):
    """Track ends: way end nodes that no other selected way contains."""
    count = {}
    for w in ways:
        for n in set(w["nodes"]):
            count[n] = count.get(n, 0) + 1
    ends = []
    for w in ways:
        for i in (0, -1):
            if count[w["nodes"][i]] == 1:
                ends.append([w["geometry"][i]["lon"], w["geometry"][i]["lat"]])
    return ends


def resolve(via, ways):
    """Waypoints: node ids or points, ("near", point) = the track end nearest that point, "far" = the track end
    furthest from the neighbouring waypoint."""
    ends = dangling(ways)
    if via == ["far", "far"]:  # the two track ends furthest apart
        return list(max(((a, b) for a in ends for b in ends), key=lambda ab: geo.dist(*ab)))
    out = [None if v == "far" else min(ends, key=lambda e: geo.dist(e, v[1])) if isinstance(v, tuple) and v[0] == "near"
           else pt(v) for v in via]
    for i, v in enumerate(via):
        if v == "far":
            ref = out[i + 1] if i == 0 else out[i - 1]
            out[i] = max(ends, key=lambda e: geo.dist(e, ref))
    return out


def join_gaps(g, d=5000):
    """Link separate pieces of the graph where they come closest, if within d metres."""
    while True:
        g.components()
        pieces = {}
        for n, c in g.comp.items():
            pieces.setdefault(c, []).append(n)
        best = None
        for c, members in sorted(pieces.items(), key=lambda kv: len(kv[1])):
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
    g.big = set(g.comp.values())


def route(ways, via):
    """Shortest path over `ways` through the waypoints. Returns (coords, ids of the ways it runs on)."""
    g = geo.RailGraph()
    for w in ways:
        g.add_way(w["nodes"], [[p["lon"], p["lat"]] for p in w["geometry"]])
    g.heal(30)
    join_gaps(g)
    node_at = {tuple(p): n for n, p in g.pos.items()}
    line = []
    for pa, pb in zip(via, via[1:]):
        r = max(geo.dist(pb, g.pos[g.nearest(pb, 30000)]), geo.dist(pa, g.pos[g.nearest(pa, 30000)])) + 300
        part = g.route_pts(pa, pb, r=r)
        if not part:
            raise SystemExit(f"no route between {pa} and {pb}")
        line += part if not line else part[1:]
    path = [node_at.get(tuple(p)) for p in line]
    pairs = {frozenset(x) for x in zip(path, path[1:])}
    used = [w["id"] for w in ways if any(frozenset(x) in pairs for x in zip(w["nodes"], w["nodes"][1:]))]
    return line, used


def cut(line, s0, s1):
    """The stretch of a line between s0 and s1 metres from its start (None: the end)."""
    cum = geo.cumul(line)
    return geo.cut(line, s0, cum[-1] if s1 is None else s1)


# ---------------------------------------------------------------- the routes
# parts: drawn separately (a branch is its own part); each part is a list of segments joined into one line:
#   {"ways": [selectors], "via": [waypoints], "cut": (from m, to m)?}  routed over OSM ways
#   {"all": [selectors]}                                               every way of the selection, chained
#   {"straight": [waypoints]}                                          straight segments (approximate)
# stations: name -> node id, point, "start"/"end" (a route end) or None (not placed). Names not listed are looked
# up among the station nodes near the line by name.
KONYA_ST = [("construction", r"^Adliye - Şehir Hastanesi - Stadyum")]
KONYA_ST_VIA = [14167354221, "far"]  # Şehir Hastanesi tram stop to the far end of the line (Stadyum)
KONYA_SPLIT = 10 / 19.7              # Şehir Hastanesi – Yeni Sanayi 10 km, Yeni Sanayi – Stadyum 9,7 km (official)
BURSA_M4 = [("proposed", r"^M4 Çalı-Demirtaş")]
GEOM = {
    # ---- Ankara
    "ankara-a1-natoyolu": dict(parts=[[{"ways": [("construction", r"^Ankaray Natoyolu")], "via": [2722447843, 9828505218]}]]),
    # YHT Gar – Pursaklar is mapped as tunnel under construction; past Pursaklar only the station platforms are mapped
    "ankara-esenboga": dict(
        parts=[[{"ways": [("ids", [1456465925, 1456465926])], "via": [13246774221, 13810839498]},
                {"straight": [13810839498, 13810875107, 13810875112, 13810875117, 13810875132]}]],
        stations={"YHT Gar": 13246774221, "Hastane": 13368141522, "Yıldırım Beyazit Üniversite": 13810875132},
        approxNote="YHT Gar – Pursaklar arası OSM'deki yapım hâlindeki tünelden çizildi. Pursaklar'dan sonrası için yalnızca "
                   "istasyon konumları haritalı; Pursaklar, Sarayköy, Fuar, Esenboğa ve Üniversite istasyonları arasında düz "
                   "çizgiyle yaklaşık gösterildi."),
    "ankara-baskentray-yenikent": dict(
        parts=[[{"ways": [("construction", r"^Başkentray Sincan - Akçaören")], "via": [8004018090, "far"]}]],
        stations={"Yenikent-2": "end"}),
    "ankara-m2-koru-baglica": dict(
        parts=[[{"ways": [("proposed", r"^M2 Bağlıca - Yaşamkent")], "via": [2715588478, 9838414554, 9838414556]}],
               [{"ways": [("proposed", r"^M2 Bağlıca - Yaşamkent")], "via": [9838414554, 9838414568, 9838414569]}]],
        stations={"Koru": 2715588478}),
    "ankara-m5-dikmen": dict(parts=[[{"ways": [("proposed", r"^M5 Dikmen")], "via": [6554580491, 9834000956]}]],
                             stations={"Dikmen Vadisi": 9834000950, "Dikmen": 9834000952, "Oran Şehri": None}),
    # OSM's "M2-M3 Bağlantı Hattı" does not pass the stations ABB named, so the line is drawn through their mapped nodes
    "ankara-m6-cayyolu-sincan": dict(parts=[[{"straight": [12453188242, 12453188237, 12453188232, 12453188227]}]],
                                     stations={"Ahimesut": None},
                                     approxNote="Güzergâh yayımlanmadı; OSM'deki Alsancak, Ahi Evran, Eryaman YHT ve Şapka Devrimi "
                                                "istasyon noktaları arasında düz çizgiyle yaklaşık gösterildi. Uçlar çizilmedi."),
    "ankara-m4-forum": dict(parts=[[{"ways": [("proposed", r"^M4 Keçiören Uzatması")], "via": [9261381509, 9834000470]}]],
                            stations={"Ovacık": 9834000472, "Forum": 9834000470}),
    "ankara-gar-sehir-hastanesi": dict(
        parts=[[{"ways": [("proposed", r"^YHT Gar-Etlik")], "via": [13246774221, 13246774224]}]],
        stations={"YHT Gar": 13246774221, "Şehir Hastanesi": 13246774224},
        approx=True, approxNote="OSM'deki daha uzun YHT Gar – Etlik Şehir Hastanesi – Ovacık önerisinin YHT Gar – Etlik Şehir "
                                "Hastanesi kesiminden çizildi; Bakanlık güzergâh yayımlamadı."),
    # ---- Konya
    "konya-sehir-hastanesi-yeni-sanayi": dict(
        parts=[[{"ways": KONYA_ST, "via": KONYA_ST_VIA, "cutf": (0, KONYA_SPLIT)}]],
        stations={"Şehir Hastanesi": 14167354221, "Yeni Sanayi": "end"}, approx=True,
        approxNote="Hat OSM'deki yapım hâlindeki güzergâhtan çizildi; Yeni Sanayi'deki etap sınırı, resmi uzunluklara göre yaklaşık konmuştur."),
    "konya-yeni-sanayi-stadyum": dict(
        parts=[[{"ways": KONYA_ST, "via": KONYA_ST_VIA, "cutf": (KONYA_SPLIT, 1)}]],
        stations={"Yeni Sanayi": "start", "Stadyum": "end"}, approx=True,
        approxNote="Hat OSM'deki yapım hâlindeki güzergâhtan çizildi; Yeni Sanayi'deki etap sınırı, resmi uzunluklara göre yaklaşık konmuştur."),
    # OSM maps a piece south of Konya station too; the first stage ends at the station
    "konya-konyaray": dict(parts=[[{"ways": [("construction", r"^KonyaRay")], "via": [13154813552, (32.4762, 37.8687)]}]],
                           stations={"Meram Gar": "end"}),
    "konya-baris-caddesi-lot1": dict(parts=[[{"ways": [("proposed", r"^Barış Caddesi Tramvay")], "via": ["far", "far"]}]],
                                     stations={"Beyhekim": None, "Kent Plaza": None}),
    "konya-fetih-ahmet-ozcan": dict(parts=[[{"all": [("proposed", r"^Konya Ring Tramvay")]}]]),
    # ---- İzmir
    "izmir-buca-metro": dict(
        parts=[[{"ways": [("construction", r"^Üçyol-Fuar İzmir Metro Hattı")], "via": [11470597370, 8119505129, 8119505130, 13062345273]}]],
        stations={"Üçyol": 11470597370, "Şirinyer": 8119562132, "Dokuz Eylül Üniversitesi": 8119505128, "Gaziemir Yeni Fuar Alanı": 13062345273}),
    "izmir-halkapinar-otogar-metro": dict(parts=[[{"ways": [("proposed", r"^Halkapınar-Otogar")], "via": [5388472394, "far"]}]],
                                          stations={"Halkapınar": 5388472394, "Otogar": "end"}),
    "izmir-karabaglar-gaziemir-metro": dict(
        parts=[[{"ways": [("proposed", r"^M3 Menderes - Gaziemir")], "via": ["far", 14125754251]}]],
        stations={"Halkapınar": None, "Gıda Çarşısı": None, "Sanayi": 14125754249, "Adnan Menderes Havaalanı": None,
                  "Menderes": 14125754251, "Konak": None}),
    # ---- Bursa
    "bursa-b1-sehir-hastanesi": dict(parts=[[{"ways": [("construction", r"^BursaRay (Emek-Şehir|Şehir Hastanesi-Emek)")],
                                              "via": [11773405295, 12065100846]}]]),
    "bursa-b2-gorukle": dict(parts=[[{"ways": [("construction", r"^BursaRay$")], "via": [5317020169, "far"]}]],
                             stations={"Üniversite": 5317020169, "Görükle": "end"}),
    # OSM maps the wider Çalı – Demirtaş corridor of the transport master plan; it is split at the T2 Terminal stop
    "bursa-ucevler-terminal": dict(
        parts=[[{"ways": BURSA_M4, "via": [("near", (28.8, 40.2)), 9862773655]}]],
        stations={"Üçevler": "start", "Terminal": 9862773655}, approx=True,
        approxNote="OSM'deki daha uzun Çalı – Demirtaş önerisinin Terminal'e kadar olan kısmından çizildi; Üçevler ucunun yeri kesin değil."),
    "bursa-terminal-demirtas-tram": dict(
        parts=[[{"ways": BURSA_M4, "via": [9862773655, ("near", (29.2, 40.3))]}]],
        stations={"Terminal": 9862773655, "Demirtaş": "end"}, approx=True,
        approxNote="OSM'deki Çalı – Demirtaş önerisinin Terminal – Demirtaş kesiminden çizildi; meclis kararı güzergâh vermiyor."),
    # ---- Antalya
    "antalya-konyaalti-varsak-tram": dict(parts=[[{"ways": [("proposed", r"^4\. Etap Varsak")], "via": [7170489775, "far"]}]],
                                          stations={"Varsak": "start", "Sarısu": "end"}),
    # ---- Kocaeli, Sakarya
    "kocaeli-gebze-darica": dict(parts=[[{"ways": [("ids", [901614217, 1300075909])], "via": [11591633641, ("near", (29.5, 40.85))]}]],
                                 stations={"Darıca Sahil": 11591633641, "Gebze Gar": 11591633644, "Gebze OSB": "end"}),
    "kocaeli-korfezray": dict(parts=[[{"ways": [("construction", r"^Kocaeli Kuzey HRS Hattı 1\. Aşama")],
                                       "via": [13532261026, ("near", (30.2, 40.75))]}]],
                              stations={"Tüpraş-Petkim": 13532261026, "Özdilek": "end"}),
    "kocaeli-guney-hrs": dict(parts=[[{"ways": [("proposed", r"^Kocaeli Güney HRS Hattı \(M4 İzmit-Başiskele-Gölcük\)")],
                                       "via": [("near", (29.92, 40.76)), "far"]}]],
                              stations={"İzmit": "start", "Gölcük": "end"}),
    "sakarya-adapazari-serdivan": dict(parts=[[{"all": [("proposed", r"^Adapazarı-Serdivan Tramvayı|^Sakarya Tramvayı")]}]],
                                       stations={"15 Temmuz Demokrasi Meydanı (Gar Meydanı)": None, "Serdivan": None}),
    # ---- Karadeniz
    "samsun-sehir-hastanesi": dict(
        parts=[[{"ways": [("proposed", r"^Samsun Şehir Hastanesi Tramvay")], "via": [4895965864, "far"]}],
               [{"ways": [("proposed", r"^Samsun Kamu Kampüs Tramvay")], "via": ["far", "far"]}]],
        stations={"Kılıçdede": 4895965864, "Şehir Hastanesi": "end"}),
    # OSM maps only the western 8 km, as two tracks; the rest is not drawn
    "trabzon-1-etap": dict(parts=[[{"ways": [("proposed", r"^Trabzon Raylı Sistem")], "via": [("near", (39.55, 41.03)), ("near", (39.67, 40.99))]}]],
                           stations={n: None for n in ("Karayolları", "Şehir Hastanesi", "Trabzonspor Stadyumu", "Bayındırlık İskân", "Beşirli",
                                                       "Trabzon Orman İşletme Bölge Müdürlüğü", "Tanjant", "İnönü", "Atapark", "Pazarkapı",
                                                       "Trabzon Meydan Parkı", "Terminal", "Sanayi", "Forum AVM",
                                                       "Karadeniz Teknik Üniversitesi", "Havalimanı")},
                           approx=True, approxNote="OSM'de hattın yalnızca batıdaki yaklaşık 8 km'lik kesimi haritalı ve yalnız o kesim "
                                                   "çizildi; Havalimanı'na kadar olan kalan kısım ve istasyonlar gösterilmedi."),
    # ---- güney ve doğu
    "adana-m1-uzatma": dict(parts=[[{"ways": [("proposed", r"^Adana Metrosu 2\. Etap")], "via": [5303110898, "far"]}]],
                            stations={"Akıncılar": 5303110898, "Stadyum": "end"}),
    # the first stage ends at 3 Ocak, 9,9 km from Mezitli; OSM maps the whole Mezitli – Gar line
    "mersin-metro": dict(parts=[[{"ways": [("proposed", r"^Mersin Mezitli - Gar")], "via": [("near", (34.3, 36.7)), ("near", (34.8, 36.85))],
                                  "cut": (0, 9900)}]],
                         stations={"Mezitli": "start", "3 Ocak": "end"}, approx=True,
                         approxNote="OSM'deki Mezitli – Gar güzergâhının Mezitli ucundan 9,9 km'lik kısmı çizildi; 3 Ocak istasyonunun yeri yaklaşıktır."),
    "gaziantep-metro": dict(parts=[[{"straight": [10160022343, 3471273399]}]],
                            stations={"Gar": 10160022343, "Akkent Parkı": 3471273399},
                            approxNote="Güzergâh yayımlanmadı; Gar ile Akkent Parkı tramvay durağı arasında düz çizgiyle yaklaşık "
                                       "gösterildi. Şehir Hastanesi ucunun yeri bilinmediğinden çizilmedi."),
    "diyarbakir-tramvay": dict(parts=[[{"ways": [("proposed", r"^Dağkapı-Gazi Yaşargil")], "via": [("near", (40.25, 37.91)), "far"]}]],
                               stations={"Dağkapı": "start", "Gazi Yaşargil Eğitim ve Araştırma Hastanesi": "end"}),
}


# stations already in service on an open line (a transfer point or the line being extended)
EXISTING = {
    "ankara-a1-natoyolu": ["Dikimevi"],
    "ankara-esenboga": ["YHT Gar", "Kuyubaşı"],
    "ankara-baskentray-yenikent": ["Sincan"],
    "ankara-m2-koru-baglica": ["Koru"],
    "ankara-m5-dikmen": ["Kızılay"],
    "ankara-m4-forum": ["Şehitler"],
    "konya-sehir-hastanesi-yeni-sanayi": ["Şehir Hastanesi"],
    "izmir-buca-metro": ["Üçyol", "Şirinyer"],
    "izmir-halkapinar-otogar-metro": ["Halkapınar"],
    "izmir-karabaglar-gaziemir-metro": ["Halkapınar"],
    "bursa-b1-sehir-hastanesi": ["Geçit/Balat"],
    "bursa-b2-gorukle": ["Üniversite"],
    "bursa-ucevler-terminal": ["Terminal"],
    "bursa-terminal-demirtas-tram": ["Terminal"],
    "kocaeli-gebze-darica": ["Gebze Gar"],
    "samsun-sehir-hastanesi": ["Kılıçdede"],
    "adana-m1-uzatma": ["Akıncılar"],
    "gaziantep-metro": ["Gar"],
}


def norm(s):
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = re.sub(r"\b(istasyonu|durağı)\b", "", s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9ı]+", " ", s).strip()


def find_station(name, line, cum):
    """The station node of this name nearest the line, within STATION_MAX: exact name first, then partial."""
    n = norm(name)
    best = {}
    for nid, e in NODES.items():
        m = norm(e.get("tags", {}).get("name") or "")
        if not m:
            continue
        kind = 0 if m == n else 1 if len(n) > 3 and len(m) > 3 and (n in m or m in n) else None
        if kind is None:
            continue
        d, s = geo.project([e["lon"], e["lat"]], line, cum)
        if d <= STATION_MAX and (kind not in best or d < best[kind][0]):
            best[kind] = (d, nid)
    for kind in (0, 1):
        if kind in best:
            return best[kind][1]
    return None


def build(lid, spec):
    parts, used, approx = [], [], bool(spec.get("approx"))
    for segs in spec["parts"]:
        line = []
        for seg in segs:
            if "straight" in seg:
                part = [pt(p) for p in seg["straight"]]
                approx = True
            elif "all" in seg:
                ways = [w for sel in seg["all"] for w in pick(sel)]
                chains = geo.chain_ways([[(n, [p["lon"], p["lat"]]) for n, p in zip(w["nodes"], w["geometry"])] for w in ways])
                parts += [c for c in chains if len(c) >= 2]
                used += [w["id"] for w in ways]
                continue
            else:
                ways = []
                for sel in seg["ways"]:
                    ways += [w for w in pick(sel) if all(w is not x for x in ways)]
                if not ways:
                    raise SystemExit(f"{lid}: no ways for {seg['ways']}")
                part, ids = route(ways, resolve(seg["via"], ways))
                if "cut" in seg:
                    part = cut(part, *seg["cut"])
                if "cutf" in seg:
                    total = geo.length(part)
                    part = cut(part, seg["cutf"][0] * total, seg["cutf"][1] * total)
                used += [i for i in ids if i not in used]
            line += part if not line else part[1:]
        if line:
            parts.append(line)
    return parts, used, approx


def place_stations(lid, rec, spec, parts):
    main = max(parts, key=geo.length)
    cum = geo.cumul(main)
    given = spec.get("stations", {})
    existing = set(EXISTING.get(lid, []))
    pts = []
    for name in rec.get("stations", []):
        ref = given.get(name, "auto") if name in given else "auto"
        if ref is None:
            continue
        if ref == "auto":
            ref = None
            for p in parts:  # a branch station lies on its own part
                ref = ref or find_station(name, p, geo.cumul(p))
            if ref is None:
                continue
        at = main[0] if ref == "start" else main[-1] if ref == "end" else pt(ref)
        d = min(geo.project(at, p, geo.cumul(p))[0] for p in parts)
        if d > STATION_MAX * 2.5:
            print(f"  ! {lid}: {name} is {d:.0f} m from the line, not placed", file=sys.stderr)
            continue
        pts.append((geo.project(at, main, cum)[1], name, at, name in existing, not isinstance(ref, int)))
    pts.sort(key=lambda t: t[0])
    return pts


def r5(p):
    return [round(p[0], 5), round(p[1], 5)]


def main():
    if "--fetch" in sys.argv:
        fetch_urban()
    data = json.loads((HERE / "urban.json").read_text())
    feats = []
    for rec in data["lines"] + data.get("pending", []):
        spec = GEOM.get(rec["id"])
        if not spec:
            print(f"  ! no geometry for {rec['id']}", file=sys.stderr)
            rec.pop("osm_ways", None)
            continue
        parts, used, approx = build(rec["id"], spec)
        rec["osm_ways"] = used
        rec["approx"] = approx
        if approx and spec.get("approxNote"):
            rec["approxNote"] = spec["approxNote"]
        else:
            rec.pop("approxNote", None)
        pts = place_stations(rec["id"], rec, spec, parts)
        simple = [[r5(p) for p in geo.simplify(c, TOL)] for c in parts]
        geom = {"type": "LineString", "coordinates": simple[0]} if len(simple) == 1 else {"type": "MultiLineString", "coordinates": simple}
        feats.append({"type": "Feature", "properties": {"line": rec["id"]}, "geometry": geom})
        for _, name, at, ex, loose in pts:
            props = {"line": rec["id"], "name": name}
            if ex:
                props["existing"] = True
            if loose:
                props["approx"] = True  # placed at the end of the drawn route, or at a platform, not at a mapped station
            feats.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": r5(at)}})
        print(f"{rec['id']:36s} {sum(geo.length(c) for c in parts) / 1000:6.1f} km drawn ({rec.get('km', '-')} official), "
              f"{len(used):3d} ways, {len(pts)}/{len(rec.get('stations', []))} stations" + (" (approx)" if approx else ""))
    (HERE / "urban.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    (HERE / "urban.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                   ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
