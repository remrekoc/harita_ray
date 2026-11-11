#!/usr/bin/env python3
# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Build data/lines.json, data/network.geojson and data/base.geojson from the cached OpenStreetMap data
(build/fetch.py), the curated İstanbul records (build/istanbul/, routes from build/istanbul_osm.py) and the
sourced ridership figures in build/ridership/*.json.

    python3 build/build.py
"""
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import geo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE = HERE / "cache"
OUT = ROOT / "data"
TODAY = "2026-11-11"


def load(name):
    p = CACHE / f"{name}.json"
    return json.loads(p.read_text())["elements"] if p.exists() else []


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").replace("İ", "i").replace("I", "ı").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("ı", "i")
    return re.sub(r"\s+", " ", s).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def r5(c, nd=5):
    return [round(c[0], nd), round(c[1], nd)]


# ---------------------------------------------------------------- OSM elements
NODES, WAYS, RELS = {}, {}, {}
for name in ["routes_train", "routes_subway", "routes_light_rail", "routes_tram", "routes_funicular", "routes_monorail"]:
    for e in load(name):
        {"node": NODES, "way": WAYS, "relation": RELS}[e["type"]][e["id"]] = e
MASTERS = load("route_masters")
STATIONS = [e for e in load("stations") if e.get("tags", {}).get("name")]
print(f"{len(RELS)} route relations, {len(WAYS)} ways, {len(NODES)} nodes, {len(STATIONS)} named stations")


def way_coords(wid):
    w = WAYS.get(wid)
    if not w:
        return None
    out = []
    for n in w["nodes"]:
        nd = NODES.get(n)
        if nd is None:
            return None
        out.append((n, [nd["lon"], nd["lat"]]))
    return out


def rel_ways(r):
    return [m["ref"] for m in r["members"] if m["type"] == "way" and m["role"] in ("", "route", "forward", "backward", "main")]


def rel_stops(r):
    """Stop names in the order the relation lists them: stop nodes first, platforms as a fallback."""
    out = []
    for roles in (("stop", "stop_entry_only", "stop_exit_only"), ("platform", "platform_entry_only", "platform_exit_only")):
        for m in r["members"]:
            if m["role"] not in roles:
                continue
            if m["type"] == "node" and m["ref"] in NODES:
                n = NODES[m["ref"]]
                out.append((n.get("tags", {}).get("name"), [n["lon"], n["lat"]]))
            elif m["type"] == "way" and m["ref"] in WAYS:
                c = way_coords(m["ref"])
                if c:
                    mid = c[len(c) // 2][1]
                    out.append((WAYS[m["ref"]].get("tags", {}).get("name"), mid))
        if out:
            break
    return out


# ---------------------------------------------------------------- rail graph (for intercity routing)
GRAPH = geo.RailGraph()
CONS_NODES = set()
for e in load("rail_ways") + load("rail_service"):
    if "geometry" not in e:
        continue
    GRAPH.add_way(e["nodes"], [[g["lon"], g["lat"]] for g in e["geometry"]], e.get("tags", {}).get("highspeed") == "yes")
for e in load("construction_ways"):  # lines being rebuilt (e.g. Mersin–Adana) still carry the services that use them
    if "geometry" in e and e.get("tags", {}).get("construction") == "rail":
        GRAPH.add_way(e["nodes"], [[g["lon"], g["lat"]] for g in e["geometry"]], False, 1.25)
        CONS_NODES.update(e["nodes"])
for w in WAYS.values():  # route members include the station tracks the running-line query leaves out
    if w.get("tags", {}).get("railway") == "rail":
        c = way_coords(w["id"])
        if c:
            GRAPH.add_way([n for n, _ in c], [p for _, p in c], w.get("tags", {}).get("highspeed") == "yes")
healed = GRAPH.heal()
GRAPH.components()
healed += GRAPH.bridge()
healed += GRAPH.bridge(5000, CONS_NODES)  # lines under reconstruction are mapped in pieces
GRAPH.components()
print(f"rail graph: {len(GRAPH.pos)} nodes, {healed} gaps joined")

STA_GRID = geo.Grid(0.01)
for s in STATIONS:
    t = s["tags"]
    kind = t.get("railway") or ("station" if t.get("public_transport") == "station" else "")
    if kind in ("station", "halt") and t.get("train") != "no" and t.get("subway") != "yes" and t.get("light_rail") != "yes" and t.get("tram") != "yes":
        STA_GRID.add([s["lon"], s["lat"]], (t["name"], kind))


SUFFIX = re.compile(r"\b(yht|tren|gari|gar|istasyonu|istasyon|durak|duragi|yht gari)\b")


def base_name(n):
    return re.sub(r"\s+", " ", SUFFIX.sub("", norm(n))).strip()


def find_station(name, hint, radius=25000):
    """The railway station called `name` closest to `hint` [lon, lat]."""
    key = base_name(name)
    best = None
    for d, p, (nm, kind) in STA_GRID.near(hint, radius):
        b = base_name(nm)
        score = (0 if b == key else 1 if b.startswith(key) or key in b.split() else 9, kind != "station", d)
        if score[0] < 9 and (best is None or score < best[0]):
            best = (score, p, nm)
    return (best[1], best[2]) if best else (hint, None)


# ---------------------------------------------------------------- cities with urban rail
CITIES = [
    # key, name, centre (for assigning OSM routes and intercity stops), radius km
    ("istanbul", "İstanbul", (28.98, 41.04), 60),
    ("ankara", "Ankara", (32.80, 39.93), 45),
    ("izmir", "İzmir", (27.14, 38.42), 75),
    ("bursa", "Bursa", (29.03, 40.20), 30),
    ("kayseri", "Kayseri", (35.49, 38.72), 25),
    ("eskisehir", "Eskişehir", (30.52, 39.77), 25),
    ("antalya", "Antalya", (30.71, 36.90), 30),
    ("konya", "Konya", (32.49, 37.90), 30),
    ("gaziantep", "Gaziantep", (37.36, 37.06), 30),
    ("samsun", "Samsun", (36.30, 41.30), 30),
    ("kocaeli", "Kocaeli", (29.93, 40.77), 22),
    ("adana", "Adana", (35.32, 37.00), 25),
    ("sakarya", "Sakarya", (30.40, 40.75), 18),
    ("bozuyuk", "Bozüyük", (30.04, 39.91), 12),
    ("aydin", "Aydın", (27.84, 37.85), 25),
]
CITY = {k: {"key": k, "name": n, "center": list(c), "radius": r} for k, n, c, r in CITIES}


def city_of(p):
    best = None
    for c in CITY.values():
        d = geo.dist(p, c["center"]) / 1000
        if d <= c["radius"] and (best is None or d < best[0]):
            best = (d, c["key"])
    return best[1] if best else None


# ---------------------------------------------------------------- line types
# Şehirlerarası (intercity): hst, main, regional. Şehir içi (urban): suburban, metro, tram, cable.
TYPE_COLOR = {"hst": "#d7192d", "main": "#24324d", "regional": "#62708a"}
NAMED = {"red": "#d6262f", "blue": "#1f63c6", "green": "#2e9a46", "orange": "#ee7b1b", "black": "#333333", "yellow": "#f1c40f",
         "deepskyblue": "#00a3e0", "purple": "#7b3fa0"}
PALETTE = ["#1f78b4", "#e8590c", "#2b8a3e", "#ae3ec9", "#c2255c", "#0c8599", "#5f3dc4", "#e67700", "#364fc7", "#087f5b"]


def too_light(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return .2126 * r + .7152 * g + .0722 * b > .8


def colour(v, fallback):
    c = _colour(v, fallback)
    return fallback if too_light(c) else c


def _colour(v, fallback):
    if not v:
        return fallback
    v = v.strip().lower()
    if v in NAMED:
        return NAMED[v]
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(ch * 2 for ch in v[1:])
    return fallback


LINES, FEATURES = [], []


def add_line(rec, parts, stations, tol):
    """Register a line: simplified geometry parts and stations as [(name, [lon, lat])] in running order."""
    parts = [geo.simplify(p, tol) for p in parts if len(p) >= 2]
    parts = [[r5(c) for c in p] for p in parts]
    if not parts:
        print("  ! no geometry for", rec["id"], file=sys.stderr)
        return
    if not rec.get("km"):
        rec["km"] = round(rec.pop("_km", None) or sum(geo.length(p) for p in parts) / 1000, 1)
    rec.pop("_km", None)
    for p in parts:
        FEATURES.append({"type": "Feature", "properties": {"line": rec["id"]}, "geometry": {"type": "LineString", "coordinates": p}})
    for name, at, *extra in stations:
        props = {"line": rec["id"], "name": name}
        if extra and extra[0]:
            props["existing"] = True
        FEATURES.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": r5(at)}})
    LINES.append(rec)


def order_stations(stations, parts, maxd=None):
    """Sort stations along the longest part, drop repeats of the same name close together."""
    main = max(parts, key=geo.length)
    cum = geo.cumul(main)
    pos = []
    for name, at in stations:
        if not name:
            continue
        d, s = geo.project(at, main, cum)
        if maxd and d > maxd:
            continue
        pos.append((s, name, at))
    pos.sort(key=lambda t: t[0])
    out = []
    for s, name, at in pos:
        if any(norm(o[0]) == norm(name) and geo.dist(o[1], at) < 1500 for o in out):
            continue
        out.append((name, at))
    return out


# ---------------------------------------------------------------- intercity services
# The 2026 state-supported (KHY) line sections from Presidential Decision 11800 (Resmî Gazete 18.09.2026) and
# the nine YHT relations the Ministry reported for 2026. `rel` takes the route from an OSM route relation;
# `cut` trims it between two stations; `via` routes it over the rail network through the named stations.
P = lambda name, lon, lat: (name, (lon, lat))
ANK, ANKC = P("Ankara", 32.8445, 39.9365), P("Ankara", 32.844, 39.936)
IST_S, IST_H = P("Söğütlüçeşme", 29.037, 40.992), P("Halkalı", 28.766, 41.019)
BAS, KON, ESK, SIV, KAR = P("Basmane", 27.143, 38.423), P("Konya", 32.475, 37.875), P("Eskişehir", 30.52, 39.78), P("Sivas", 37.01, 39.745), P("Karaman", 33.22, 37.18)
ADA, MAL, ELA, DEN = P("Adana", 35.33, 37.0), P("Malatya", 38.31, 38.36), P("Elazığ", 39.22, 38.67), P("Denizli", 29.09, 37.78)
INTERCITY = [
    dict(id="yht-ankara-istanbul", type="hst", name="Ankara – İstanbul", rel=18650922, fr=ANK, to=IST_H, via=[IST_S], ride="Ankara–İstanbul YHT", opened=2014),
    dict(id="yht-ankara-konya", type="hst", name="Ankara – Konya", rel=18652780, fr=ANK, to=KON, ride="Ankara–Konya YHT", opened=2011),
    dict(id="yht-istanbul-konya", type="hst", name="İstanbul – Konya", rel=18639068, fr=IST_H, via=[IST_S], to=KON, ride="Konya–İstanbul YHT", opened=2014),
    dict(id="yht-ankara-eskisehir", type="hst", name="Ankara – Eskişehir", rel=18652777, fr=ANK, to=ESK, ride="Ankara–Eskişehir YHT", opened=2009),
    dict(id="yht-istanbul-eskisehir", type="hst", name="İstanbul – Eskişehir", rel=18652774, fr=IST_H, via=[IST_S], to=ESK, ride="Eskişehir–İstanbul YHT", opened=2022),
    dict(id="yht-ankara-sivas", type="hst", name="Ankara – Sivas", rel=18652779, fr=ANK, to=SIV, ride="Ankara–Sivas YHT", opened=2023),
    dict(id="yht-istanbul-sivas", type="hst", name="İstanbul – Sivas", rel=18652776, fr=IST_H, via=[IST_S, ANK], to=SIV, ride="İstanbul–Sivas YHT", opened=2024),
    dict(id="yht-ankara-karaman", type="hst", name="Ankara – Karaman", rel=18652781, fr=ANK, via=[KON], to=KAR, ride="Ankara–Karaman YHT", opened=2022),
    dict(id="yht-istanbul-karaman", type="hst", name="İstanbul – Karaman", rel=18652773, fr=IST_H, via=[IST_S, KON], to=KAR, ride="İstanbul–Karaman YHT", opened=2022),
    # ana hat
    dict(id="ana-ankara-kars", type="main", name="Ankara – Kars", alias="Doğu Ekspresi", rel=18713200, fr=ANKC, via=[P("Kayseri", 35.48, 38.73), SIV, P("Erzurum", 41.27, 39.92)], to=P("Kars", 43.09, 40.61), pso="Ankara–Kars"),
    dict(id="ana-turistik-dogu", type="main", name="Ankara – Kars", alias="Turistik Doğu Ekspresi", rel=18713201, fr=ANKC, via=[P("Kayseri", 35.48, 38.73), SIV, P("Erzurum", 41.27, 39.92)], to=P("Kars", 43.09, 40.61),
         ride="Turistik Doğu Ekspresi", note="Ticari olarak işletilen turistik tren; yalnızca sezonda çalışır."),
    dict(id="ana-ankara-tatvan", type="main", name="Ankara – Tatvan", alias="Vangölü Ekspresi", rel=12158683, fr=ANKC, via=[P("Kayseri", 35.48, 38.73), SIV, MAL, ELA], to=P("Tatvan", 42.28, 38.50), pso="Ankara–Tatvan"),
    dict(id="ana-ankara-kurtalan", type="main", name="Ankara – Kurtalan", alias="Güney Kurtalan Ekspresi", rel=18430359, fr=ANKC, via=[P("Kayseri", 35.48, 38.73), SIV, MAL, P("Diyarbakır", 40.22, 37.91)], to=P("Kurtalan", 41.70, 37.93), pso="Ankara–Kurtalan"),
    dict(id="ana-ankara-malatya", type="main", name="Ankara – Malatya", alias="4 Eylül Mavi Treni", rel=18430359, fr=ANKC, via=[P("Kayseri", 35.48, 38.73), SIV], to=MAL, pso="Ankara–Malatya"),
    dict(id="ana-ankara-izmir", type="main", name="Ankara – İzmir (Basmane)", alias="İzmir Mavi Treni", rel=16121736, fr=ANKC, via=[ESK, P("Afyon", 30.55, 38.77), P("Manisa", 27.43, 38.62)], to=BAS, pso="Ankara–Basmane"),
    dict(id="ana-ankara-halkali", type="main", name="Ankara – İstanbul (Halkalı)", alias="Ankara Ekspresi", rel=1323070, fr=ANKC, via=[ESK, P("İzmit", 29.94, 40.76)], to=IST_H, pso="Ankara–Halkalı", hs=None),
    dict(id="ana-konya-izmir", type="main", name="Konya – İzmir (Basmane)", alias="Konya Mavi Treni", rel=18296571, fr=KON, via=[P("Afyon", 30.55, 38.77), P("Manisa", 27.43, 38.62)], to=BAS, pso="Konya–Basmane"),
    dict(id="ana-eskisehir-izmir", type="main", name="Eskişehir – İzmir (Basmane)", alias="Ege Ekspresi", rel=18321859, fr=ESK, via=[P("Afyon", 30.55, 38.77), P("Manisa", 27.43, 38.62)], to=BAS, pso="Basmane–Eskişehir"),
    dict(id="ana-eskisehir-denizli", type="main", name="Eskişehir – Denizli", alias="Pamukkale Ekspresi", rel=18320312, fr=ESK, via=[P("Afyon", 30.55, 38.77)], to=DEN, pso="Denizli–Eskişehir"),
    dict(id="ana-isparta-izmir", type="main", name="Isparta – İzmir (Basmane)", alias="Göller Ekspresi", rel=18319997, fr=P("Isparta", 30.55, 37.77), via=[P("Dinar", 30.16, 38.07), DEN], to=BAS, pso="Isparta–Basmane"),
    dict(id="ana-konya-adana", type="main", name="Konya – Adana", alias="Toros Ekspresi", rel=1298494, fr=KON, via=[P("Karaman", 33.22, 37.18), P("Ulukışla", 34.48, 37.55)], to=ADA, pso="Konya–Adana"),
    dict(id="ana-adana-elazig", type="main", name="Adana – Elazığ", fr=ADA, via=[P("Toprakkale", 36.15, 37.06), P("Fevzipaşa", 36.64, 37.10), MAL], to=ELA, pso="Elazığ–Adana"),
    dict(id="ana-sivas-samsun", type="main", name="Sivas – Samsun", rel=19785141, fr=SIV, via=[P("Amasya", 35.83, 40.65)], to=P("Samsun", 36.34, 41.28), pso="Sivas–Samsun"),
    # bölgesel
    dict(id="bol-adana-mersin", type="regional", name="Adana – Mersin", rel=1308730, fr=ADA, to=P("Mersin", 34.64, 36.80), pso="Adana–Mersin", hs=None),
    dict(id="bol-adana-kayseri", type="regional", name="Adana – Kayseri", alias="Erciyes Ekspresi", rel=6234723, fr=ADA, via=[P("Ulukışla", 34.48, 37.55), P("Niğde", 34.68, 37.97)], to=P("Kayseri", 35.48, 38.73), pso="Adana–Kayseri"),
    dict(id="bol-afyon-eskisehir", type="regional", name="Afyonkarahisar – Eskişehir", fr=P("Afyon", 30.55, 38.77), to=ESK, pso="Afyonkarahisar–Eskişehir"),
    dict(id="bol-ankara-polatli", type="regional", name="Ankara – Polatlı", rel=9440197, fr=ANKC, to=P("Polatlı", 32.15, 39.58), pso="Ankara–Polatlı"),
    dict(id="bol-izmir-alasehir", type="regional", name="İzmir (Basmane) – Alaşehir", rel=18321861, fr=BAS, via=[P("Manisa", 27.43, 38.62)], to=P("Alaşehir", 28.51, 38.35), pso="Basmane–Alaşehir"),
    dict(id="bol-manisa-alasehir", type="regional", name="Manisa – Alaşehir", rel=18321862, fr=P("Manisa", 27.43, 38.62), to=P("Alaşehir", 28.51, 38.35), pso="Manisa–Alaşehir"),
    dict(id="bol-izmir-usak", type="regional", name="İzmir (Basmane) – Uşak", rel=18321860, fr=BAS, via=[P("Manisa", 27.43, 38.62), P("Alaşehir", 28.51, 38.35)], to=P("Uşak", 29.40, 38.68), pso="Basmane–Uşak"),
    dict(id="bol-izmir-bandirma", type="regional", name="İzmir (Basmane) – Bandırma", alias="6 Eylül ve 17 Eylül Ekspresi", rel=18319919, fr=BAS, via=[P("Manisa", 27.43, 38.62), P("Balıkesir", 27.89, 39.65)], to=P("Bandırma", 27.97, 40.35), pso="Basmane–Bandırma"),
    dict(id="bol-izmir-denizli", type="regional", name="İzmir (Basmane) – Denizli", rel=18319992, fr=BAS, via=[P("Aydın", 27.84, 37.85), P("Nazilli", 28.32, 37.91)], to=DEN, pso="Basmane–Denizli"),
    dict(id="bol-izmir-nazilli", type="regional", name="İzmir (Basmane) – Nazilli", rel=18319995, fr=BAS, via=[P("Aydın", 27.84, 37.85)], to=P("Nazilli", 28.32, 37.91), pso="Basmane–Nazilli"),
    dict(id="bol-izmir-odemis", type="regional", name="İzmir (Basmane) – Ödemiş", rel=18319993, fr=BAS, via=[P("Torbalı", 27.36, 38.16)], to=P("Ödemiş", 27.97, 38.23), pso="Basmane–Ödemiş"),
    dict(id="bol-izmir-tire", type="regional", name="İzmir (Basmane) – Tire", rel=18319994, fr=BAS, via=[P("Torbalı", 27.36, 38.16)], to=P("Tire", 27.73, 38.09), pso="Basmane–Tire"),
    dict(id="bol-izmir-soke", type="regional", name="İzmir (Basmane) – Söke", fr=BAS, via=[P("Torbalı", 27.36, 38.16), P("Ortaklar", 27.50, 37.88)], to=P("Söke", 27.39, 37.75), pso="Basmane–Söke"),
    dict(id="bol-soke-denizli", type="regional", name="Söke – Denizli", rel=18320175, fr=P("Söke", 27.39, 37.75), via=[P("Ortaklar", 27.50, 37.88), P("Aydın", 27.84, 37.85)], to=DEN, pso="Söke–Denizli"),
    dict(id="bol-soke-nazilli", type="regional", name="Söke – Nazilli", rel=18320176, fr=P("Söke", 27.39, 37.75), via=[P("Ortaklar", 27.50, 37.88), P("Aydın", 27.84, 37.85)], to=P("Nazilli", 28.32, 37.91), pso="Söke–Nazilli"),
    dict(id="bol-sivas-divrigi", type="regional", name="Sivas – Divriği", fr=SIV, to=P("Divriği", 38.11, 39.37), pso="Divriği–Sivas"),
    dict(id="bol-divrigi-erzincan", type="regional", name="Divriği – Erzincan", fr=P("Divriği", 38.11, 39.37), to=P("Erzincan", 39.50, 39.74), pso="Divriği–Erzincan"),
    dict(id="bol-sivas-malatya", type="regional", name="Sivas – Malatya", rel=20211500, fr=SIV, to=MAL, pso="Sivas–Malatya"),
    dict(id="bol-diyarbakir-batman", type="regional", name="Diyarbakır – Batman", rel=18430359, fr=P("Diyarbakır", 40.22, 37.91), to=P("Batman", 41.13, 37.88), pso="Diyarbakır–Batman"),
    dict(id="bol-elazig-tatvan", type="regional", name="Elazığ – Tatvan", rel=12158683, fr=ELA, via=[P("Muş", 41.49, 38.75)], to=P("Tatvan", 42.28, 38.50), pso="Elazığ–Tatvan"),
    dict(id="bol-eskisehir-kutahya", type="regional", name="Eskişehir – Kütahya", fr=ESK, to=P("Kütahya", 29.97, 39.43), pso="Eskişehir–Kütahya"),
    dict(id="bol-eskisehir-tavsanli", type="regional", name="Eskişehir – Tavşanlı", fr=ESK, via=[P("Kütahya", 29.97, 39.43)], to=P("Tavşanlı", 29.49, 39.55), pso="Eskişehir–Tavşanlı"),
    dict(id="bol-kutahya-balikesir", type="regional", name="Kütahya – Balıkesir", fr=P("Kütahya", 29.97, 39.43), via=[P("Tavşanlı", 29.49, 39.55)], to=P("Balıkesir", 27.89, 39.65), pso="Kütahya–Balıkesir"),
    dict(id="bol-gaziantep-karkamis", type="regional", name="Gaziantep – Karkamış", fr=P("Gaziantep", 37.38, 37.08), to=P("Karkamış", 38.00, 36.84), pso="Gaziantep–Karkamış"),
    dict(id="bol-gebze-adapazari", type="regional", name="Gebze – Adapazarı", fr=P("Gebze", 29.41, 40.79), via=[P("İzmit", 29.94, 40.76), P("Arifiye", 30.36, 40.71)], to=P("Adapazarı", 30.40, 40.78), pso="Gebze–Adapazarı", hs=None),
    dict(id="bol-halkali-edirne", type="regional", name="İstanbul (Halkalı) – Edirne", fr=IST_H, via=[P("Çerkezköy", 28.00, 41.28), P("Pehlivanköy", 26.92, 41.35)], to=P("Edirne", 26.57, 41.65), pso="Halkalı–Edirne"),
    dict(id="bol-halkali-uzunkopru", type="regional", name="İstanbul (Halkalı) – Uzunköprü", rel=21606026, fr=IST_H, via=[P("Çerkezköy", 28.00, 41.28)], to=P("Uzunköprü", 26.69, 41.27), pso="Halkalı–Uzunköprü"),
    dict(id="bol-kars-akyaka", type="regional", name="Kars – Akyaka", fr=P("Kars", 43.09, 40.61), to=P("Akyaka", 43.62, 40.74), pso="Kars–Akyaka"),
    dict(id="bol-konya-karaman", type="regional", name="Konya – Karaman", rel=18652783, fr=KON, to=KAR, pso="Konya–Karaman", hs=None),
    dict(id="bol-mersin-iskenderun", type="regional", name="Mersin – İskenderun", fr=P("Mersin", 34.64, 36.80), via=[ADA, P("Toprakkale", 36.15, 37.06)], to=P("İskenderun", 36.17, 36.59), pso="Mersin–İskenderun", hs=None),
    dict(id="bol-mersin-islahiye", type="regional", name="Mersin – İslahiye", fr=P("Mersin", 34.64, 36.80), via=[ADA, P("Toprakkale", 36.15, 37.06), P("Fevzipaşa", 36.64, 37.10)], to=P("İslahiye", 36.63, 37.03), pso="Mersin–İslahiye", hs=None),
    dict(id="bol-samsun-amasya", type="regional", name="Samsun – Amasya", rel=19785141, fr=P("Samsun", 36.34, 41.28), to=P("Amasya", 35.83, 40.65), pso="Samsun–Amasya"),
    dict(id="bol-zonguldak-karabuk", type="regional", name="Zonguldak – Karabük", fr=P("Zonguldak", 31.79, 41.45), to=P("Karabük", 32.62, 41.20), pso="Zonguldak–Karabük"),
    dict(id="bol-zonguldak-gokcebey", type="regional", name="Zonguldak – Gökçebey", fr=P("Zonguldak", 31.79, 41.45), to=P("Gökçebey", 32.15, 41.31), pso="Zonguldak–Gökçebey"),
]
# YHT stops: services call at these stations only (the corridor also passes suburban halts)
YHT_STOPS = {"ankara", "eryaman", "polatli", "eskisehir", "bozuyuk", "bilecik", "pamukova", "arifiye", "izmit",
             "gebze", "pendik", "bostanci", "sogutlucesme", "bakirkoy", "halkali", "konya", "karaman", "kirikkale",
             "yerkoy", "yozgat", "sorgun", "akdagmadeni", "yildizeli", "sivas", "cumra"}
OPERATOR = "TCDD Taşımacılık"


TRACK_PTS = geo.Grid(0.01)
for e in load("rail_ways") + load("construction_ways"):
    if e.get("tags", {}).get("railway") == "rail" or e.get("tags", {}).get("construction") == "rail":
        for g in e.get("geometry", []):
            TRACK_PTS.add([g["lon"], g["lat"]])


def corridor_line(a, b, half=4000, step=1000):
    """A centre line through the mapped track pieces between a and b: the median of the track points in each
    kilometre along a→b. Used only where the track graph is broken."""
    L = geo.dist(a, b)
    n = max(2, int(L // step))
    out = [a]
    for i in range(1, n):
        f = i / n
        c = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
        pts = [q for d, q, _ in TRACK_PTS.near(c, half)]
        if pts:
            xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
            out.append([xs[len(xs) // 2], ys[len(ys) // 2]])
    out.append(b)
    return out


def service_geometry(s, prefer_hs):
    """Route a service over the rail network from its first to its last station through any via stations.

    Where an OSM route relation exists, its ways are preferred, so the line follows the mapped route; the router
    bridges the gaps such relations often have and never zig-zags between their pieces."""
    prefer = set()
    if s.get("rel"):
        for w in rel_ways(RELS[s["rel"]]):
            if w in WAYS:
                prefer.update(WAYS[w]["nodes"])
    pts = []
    for name, hint in [s["fr"]] + s.get("via", []) + [s["to"]]:
        at, found = find_station(name, hint)
        pts.append(at)
    out = []
    for a, b in zip(pts, pts[1:]):
        seg = GRAPH.route_pts(a, b, prefer_hs, prefer)
        if seg and geo.length(seg) > 2.2 * geo.dist(a, b) + 5000:
            # the mapped track is broken here (a line under reconstruction): follow the track pieces instead
            seg = corridor_line(a, b)
            s.setdefault("approx", True)
        if not seg:
            print(f"  ! {s['id']}: no rail route {a} → {b}", file=sys.stderr)
            return None
        # a station beyond a gap in the mapped track (Mersin, 2026): join it to the nearest mapped track
        if geo.dist(seg[0], a) > 300:
            seg = [a] + seg
        if geo.dist(seg[-1], b) > 300:
            seg = seg + [b]
        out += seg if not out else seg[1:]
    return out


def stations_along(line, kinds, maxd):
    grid = geo.densify_grid([line], step=80)
    found = []
    seen = set()
    for key, items in STA_GRID.g.items():
        for p, (name, kind) in items:
            if kind not in kinds or (name, tuple(p)) in seen:
                continue
            if grid.near(p, maxd):
                seen.add((name, tuple(p)))
                found.append((name, p))
    return order_stations(found, [line])


def build_intercity():
    for s in INTERCITY:
        hs = s["hs"] if "hs" in s else (True if s["type"] == "hst" else False)
        line = service_geometry(s, hs)
        if not line:
            continue
        if s["type"] == "hst":
            st = [x for x in stations_along(line, ("station", "halt"), 400) if base_name(x[0]) in YHT_STOPS]
            # a town with both an old station and a YHT one: the train calls at the YHT station
            yht = {base_name(n) for n, _ in st if re.search(r"\bYHT\b", n)}
            st = [x for x in st if re.search(r"\bYHT\b", x[0]) or base_name(x[0]) not in yht]
        else:
            st = stations_along(line, ("station",) if s["type"] == "main" else ("station", "halt"), 250)
        # name the service by where it actually runs: first and last station on the routed line
        rec = {"id": s["id"], "code": {"hst": "YHT", "main": "AH", "regional": "B"}[s["type"]], "name": s["name"], "type": s["type"],
               "city": None, "color": TYPE_COLOR[s["type"]], "status": "open", "operator": OPERATOR}
        if s.get("approx"):
            rec["approx"] = True
        for k in ("alias", "opened", "note", "pso", "ride"):
            if s.get(k):
                rec[k] = s[k]
        if s.get("rel"):
            rec["osm"] = [s["rel"]]
        rec["stopsKind"] = "yht" if s["type"] == "hst" else "route"
        add_line(rec, [line], st, 40 if s["type"] != "regional" else 30)
        print(f"  {s['id']:28s} {LINES[-1]['km']:7.1f} km  {len(st):3d} st  {st[0][0] if st else '-'} → {st[-1][0] if st else '-'}")


# ---------------------------------------------------------------- urban lines from OSM (outside İstanbul)
MODE_TYPE = {"subway": "metro", "light_rail": "metro", "tram": "tram", "monorail": "metro", "funicular": "cable", "train": "suburban"}
SUBURBAN = {  # TCDD / joint commuter lines, by OSM relation
    "ankara-baskentray": dict(rels=[14118633, 14118634], code="B", name="Başkentray", alias="Sincan – Kayaş", color="#00a49f", operator="TCDD Taşımacılık", opened=2018),
    "izmir-izban": dict(rels=[15423228, 16191185, 17437070, 16191186, 17294174, 363587, 17286900], code="İZ", name="İZBAN",
                        alias="Aliağa – Selçuk", color="#005399", operator="İZBAN (TCDD ve İzmir Büyükşehir Belediyesi)", opened=2010),
    "gaziantep-gaziray": dict(rels=[14785798, 14785413], code="GR", name="Gaziray", alias="Başpınar – Taşlıca", color="#e8b500", operator="TCDD Taşımacılık", opened=2022),
    "sakarya-adaray": dict(rels=[9111421, 18226425], code="AR", name="Adaray", alias="Adapazarı – Arifiye", color="#3b6fb6", operator="TCDD Taşımacılık"),
    "aydin-ayban": dict(rels=[21114490, 21114491], code="AY", name="AYBAN", alias="İncirliova – Köşk", color="#7a5195", operator="TCDD Taşımacılık", opened=2026),
}
SKIP_NAME = re.compile(r"proje|project|planlanan|insaat|construction", re.I)
SKIP_REL = {19925415, 20040971, 20140335, 19697950, 19766622, 19983333}  # Ankara M5 (yapım), Konya T4 & ring (yapım), Kocaeli 2. etap proje, ..., Konya T3 Şehir Hastanesi – Stadyum (yapım)
MERGE = {  # OSM routes that are one line on the ground: variants and short workings
    "konya-h1": ["konya-h2", "konya-h3"], "konya-h4": ["konya-h5"], "bursa-t3": ["bursa-tram-2230605"], "izmir-t3": ["izmir-tram-17289371"],
}
OVERRIDE = {  # by line id: names, codes and colours where OSM is missing or ambiguous
    "aydin-ayban": dict(km=29.5, history=[{"date": "17 Temmuz 2026", "text": "İncirliova – Aydın – Köşk arasında yolcu seferleri başladı"}],
                        sources=[{"title": "Aydın'da AYBAN Dönemi Başladı", "publisher": "Ulaştırma ve Altyapı Bakanlığı", "date": "2026-07-17",
                                  "url": "https://www.uab.gov.tr/haberler/aydinda-ayban-doenemi-basladi/"},
                                 {"title": "Bakan Uraloğlu: Aydın'da AYBAN hizmete alındı", "publisher": "DHA", "date": "2026-07-18",
                                  "url": "https://www.dha.com.tr/gundem/bakan-uraloglu-aydinda-ayban-hizmete-alindi-2911973"}]),
    "ankara-m1": dict(name="Kızılay – Batıkent", color="#d8232a"),
    "ankara-m2": dict(name="Kızılay – Koru", color="#8e3f98"),
    "ankara-m3": dict(name="Batıkent – Törekent", color="#2a6fb8"),
    "ankara-m4": dict(name="Kızılay (AKM) – Şehitler", color="#f0a51e"),
    "ankara-a": dict(id="ankara-a1", code="A1", name="AŞTİ – Dikimevi", alias="Ankaray"),
    "bursa-b1": dict(code="B1", alias="BursaRay"),
    "bursa-b2": dict(code="B2", alias="BursaRay"),
    "izmir-m1": dict(name="Narlıdere Kaymakamlık – Evka 3", alias="İzmir Metrosu", color="#1b64b6"),
    "izmir-t1": dict(alias="Karşıyaka Tramvayı", color="#e2231a"),
    "izmir-t2": dict(alias="Konak Tramvayı", color="#00a650"),
    "izmir-t3": dict(alias="Çiğli Tramvayı", color="#f39200"),
    "adana-m1": dict(alias="Adana Metrosu"),
    "antalya-t2": dict(alias="Nostalji Tramvayı"),
    "antalya-t1": dict(alias="AntRay"), "antalya-t3": dict(alias="AntRay"),
    "kocaeli-t1": dict(alias="Akçaray"), "kocaeli-t2": dict(alias="Akçaray"), "kocaeli-t3": dict(alias="Akçaray"),
    "kayseri-t1": dict(alias="Kayseray"), "kayseri-t2": dict(alias="Kayseray"), "kayseri-t3": dict(alias="Kayseray"), "kayseri-t4": dict(alias="Kayseray"),
    "konya-h1": dict(code="H1", name="Alaaddin – Selçuk Üniversitesi", alias="Kampüs hattı"),
    "konya-h4": dict(name="Alaaddin – Şehir Hastanesi", alias="Adliye hattı"),
    "bozuyuk-1": dict(code="T1", alias="Boztram"),
    "samsun-1": dict(code="T1", alias="Samsun tramvayı"), "samsun-2": dict(code="T2", alias="Samsun tramvayı"), "samsun-3": dict(code="T3", alias="Samsun tramvayı"),
    "eskisehir-7": dict(code="T7", alias="Estram"), "eskisehir-12": dict(code="T12", alias="Estram"),
    "eskisehir-t1": dict(alias="Estram"), "eskisehir-t3": dict(alias="Estram"), "eskisehir-t4": dict(alias="Estram"), "eskisehir-t8": dict(alias="Estram"),
    "eskisehir-t9": dict(alias="Estram"), "eskisehir-t10": dict(alias="Estram"),
    # Gaziantep's OSM colours are pure screen primaries; the same hues, toned to sit with the rest
    "gaziantep-t1": dict(alias="Gaziantep tramvayı", color="#e5432d"), "gaziantep-t2": dict(alias="Gaziantep tramvayı", color="#34b24a"),
    "gaziantep-t3": dict(alias="Gaziantep tramvayı", color="#2f55d4"),
    "ankara-tram-13897686": dict(id="ankara-nostalji", name="Başkent Millet Bahçesi", alias="Nostaljik tramvay"),
}


def build_urban():
    # route masters group directions and variants of one line
    master_of = {}
    for m in MASTERS:
        for mem in m["members"]:
            if mem["type"] == "relation":
                master_of[mem["ref"]] = m
    suburban_rels = {r for v in SUBURBAN.values() for r in v["rels"]}
    groups = defaultdict(list)
    for rid, r in RELS.items():
        t = r.get("tags", {})
        route = t.get("route")
        if route not in MODE_TYPE or rid in SKIP_REL or SKIP_NAME.search(t.get("name", "")) or t.get("state") in ("proposed", "construction"):
            continue
        if route == "train" and rid not in suburban_rels:
            continue
        ways = [way_coords(w) for w in rel_ways(r)]
        ways = [w for w in ways if w]
        if not ways:
            continue
        pts = [c for w in ways for _, c in w]
        cen = [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
        city = city_of(cen)
        if not city or city == "istanbul":
            continue  # İstanbul comes from the curated records
        if rid in suburban_rels:
            key = next(k for k, v in SUBURBAN.items() if rid in v["rels"])
        elif rid in master_of:
            m = master_of[rid]["tags"]
            key = f"{city}-{slug(m.get('ref') or m.get('name') or rid)}"
        else:
            ref = t.get("ref") or ""
            ref = re.sub(r"(?<=\d)[ab]$", "", ref, flags=re.I)  # Kayseri T1a → T1
            key = f"{city}-{slug(ref)}" if ref else f"{city}-{MODE_TYPE[route]}-{rid}"
        groups[key].append((r, ways, city, route))

    # merge groups that run on the same track as a longer one in the same city (service variants, H1/H2/H3 …)
    def way_set(g):
        return {w[0][0] for _, ws, _, _ in g for w in ws} | {w[-1][0] for _, ws, _, _ in g for w in ws}

    def track_len(g):
        seen, tot = set(), 0
        for _, ws, _, _ in g:
            for w in ws:
                k = (w[0][0], w[-1][0])
                if k in seen or k[::-1] in seen:
                    continue
                seen.add(k)
                tot += geo.length([c for _, c in w])
        return tot
    keys = sorted(groups, key=lambda k: -track_len(groups[k]))
    merged = {}
    for k in keys:
        g = groups[k]
        city, route = g[0][2], g[0][3]
        pts_grid_target = None
        for big in merged:
            bg = merged[big]
            if bg[0][2] != city or MODE_TYPE[bg[0][3]] != MODE_TYPE[route] or big in SUBURBAN or k in SUBURBAN:
                continue
            grid = geo.densify_grid([[c for _, c in w] for _, ws, _, _ in bg for w in ws], step=40, cell=0.003)
            sample = [c for _, ws, _, _ in g for w in ws for _, c in w[:: max(1, len(w) // 6)]]
            near = sum(1 for p in sample if grid.near(p, 35))
            if sample and near / len(sample) > 0.9:
                pts_grid_target = big
                break
        if pts_grid_target and not re.fullmatch(r"[a-z]+-(t|m|b)\d+", k):
            merged[pts_grid_target] += g
        else:
            merged[k] = list(g)

    for big, smalls in MERGE.items():
        for k in smalls:
            if big in merged and k in merged:
                merged[big] += merged.pop(k)
    pal = defaultdict(int)
    for key, g in sorted(merged.items()):
        city, route = g[0][2], g[0][3]
        typ = MODE_TYPE[route]
        # the longest single route defines the line; other routes add only track it does not cover (branches)
        g = sorted(g, key=lambda x: -sum(geo.length([c for _, c in w]) for w in x[1]))
        r0, ws0 = g[0][0], g[0][1]
        chosen = list(ws0)
        grid = geo.densify_grid([[c for _, c in w] for w in chosen], step=40, cell=0.003)
        for r, ws, _, _ in g[1:]:
            extra = [w for w in ws if sum(1 for _, c in w if grid.near(c, 30)) < 0.6 * len(w)]
            if extra and sum(geo.length([c for _, c in w]) for w in extra) > 400:
                chosen += extra
                for w in extra:
                    for _, c in w:
                        grid.add(c)
        parts = geo.chain_ways(chosen)
        rp = sorted(([c for _, c in p] for p in geo.order_ways(ws0)), key=geo.length, reverse=True)
        kgrid = geo.densify_grid(rp[:1], step=40, cell=0.003)
        main_km = (geo.length(rp[0]) + sum(geo.length(p) for p in rp[1:] if not kgrid.near(p[len(p) // 2], 80))) / 1000
        stops = rel_stops(r0)
        for r, _, _, _ in g[1:]:
            extra = [s for s in rel_stops(r) if s[0] and not any(norm(s[0]) == norm(o[0]) for o in stops if o[0])]
            stops += extra
        if not stops:  # no stop members: the named stops and stations on the track
            grid2 = geo.densify_grid(parts, step=40, cell=0.003)
            stops = [(s["tags"]["name"], [s["lon"], s["lat"]]) for s in STATIONS
                     if city_of([s["lon"], s["lat"]]) == city and grid2.near([s["lon"], s["lat"]], 40)]
        stops = [(re.sub(r"^[A-Z]\d+\s*-\s*", "", n or ""), p) for n, p in stops]
        stations = order_stations(stops, parts, maxd=600)
        t = r0["tags"]
        sub = SUBURBAN.get(key)
        ref = (sub or {}).get("code") or re.sub(r"(?<=\d)[ab]$", "", t.get("ref") or "", flags=re.I)
        name = (sub or {}).get("name")
        if not name:
            name = f"{stations[0][0]} – {stations[-1][0]}" if len(stations) >= 2 else re.sub(r"^[A-Z]?\d+[A-Z]?\s*[:\-]?\s*", "", t.get("name", "")).strip()
        rec = {"id": key, "code": ref or {"metro": "M", "tram": "T", "cable": "F", "suburban": "B"}[typ], "name": name, "type": typ, "city": city,
               "status": "open", "operator": (sub or {}).get("operator") or t.get("operator") or "", "network": t.get("network") or "",
               "osm": sorted({x[0]["id"] for x in g})}
        if sub:
            rec.update({k: v for k, v in sub.items() if k in ("alias", "opened", "color")})
            if sub.get("alias"):
                rec["name"], rec["alias"] = sub["name"], sub["alias"]
        if not rec.get("color"):
            pal[city] += 1
            rec["color"] = colour(t.get("colour") or (master_of.get(r0["id"], {}).get("tags", {}).get("colour")), PALETTE[(pal[city] - 1) % len(PALETTE)])
        ov = OVERRIDE.get(key, {})
        rec.update(ov)
        rec["_km"] = main_km
        add_line(rec, parts, stations, 4 if typ != "suburban" else 10)


# ---------------------------------------------------------------- İstanbul, from the curated records
IST_TYPE = {"metro": "metro", "tram": "tram", "funicular": "cable", "rail": "suburban"}


def build_istanbul():
    src = HERE / "istanbul"
    lines = json.loads((src / "lines.json").read_text())
    net = json.loads((src / "network.geojson").read_text())
    feats = defaultdict(list)
    for f in net["features"]:
        feats[f["properties"]["line"]].append(f)
    for l in lines:
        rec = dict(l)
        rec["id"] = "istanbul-" + slug(l["id"])
        rec["type"] = IST_TYPE[l.pop("mode", None) or rec.pop("mode")]
        rec.pop("mode", None)
        rec["city"] = "istanbul"
        rec["src"] = l["id"]
        if l["id"] == "B1":
            rec["name"], rec["alias"] = "Marmaray", "Halkalı – Gebze"
        if l["id"] == "U3":
            rec["name"], rec["alias"] = "Sirkeci – Kazlıçeşme", "Banliyö hattı"
        parts, stations = [], []
        for f in feats[l["id"]]:
            g = f["geometry"]
            if g["type"] == "Point":
                stations.append((f["properties"]["name"], g["coordinates"], f["properties"].get("existing")))
            else:
                for c in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                    parts.append(c)
                    if f["properties"].get("closed"):
                        rec.setdefault("closedParts", 0)
                        rec["closedParts"] += 1
        if any(f["properties"].get("closed") for f in feats[l["id"]] if f["geometry"]["type"] != "Point"):
            rec["partClosed"] = True
        add_line(rec, parts, stations, 3)
    # Metro İstanbul's two aerial cableways, from OSM
    for e in load("aerialways"):
        nm = e.get("tags", {}).get("name", "")
        for code, key, name, opened in (("TF1", "Maçka", "Maçka – Taşkışla", 1993), ("TF2", "Piyerloti", "Eyüp – Piyer Loti", 2006)):
            if key in nm:
                c = [[g["lon"], g["lat"]] for g in e["geometry"]]
                rec = {"id": "istanbul-" + code.lower(), "code": code, "name": name, "alias": "Teleferik", "type": "cable", "city": "istanbul",
                       "status": "open", "color": "#7c7358", "operator": "Metro İstanbul", "opened": opened, "osm_way": e["id"]}
                add_line(rec, [c], [(name.split(" – ")[0], c[0]), (name.split(" – ")[1], c[-1])], 3)


# ---------------------------------------------------------------- projects outside the curated İstanbul set
# Lines being built or planned, and openings since the OSM routes were mapped, curated from official sources
# (the ministry, municipalities, the investment programme) in build/projects/<scope>.json, with routes and stations
# in build/projects/<scope>.geojson; build/projects/make_<scope>.py rebuilds that geometry from OSM.
PROJECT_KEYS = ("code", "name", "alias", "project", "type", "status", "color", "authority", "operator", "contractor", "km", "speed", "fleet",
                "progress", "update", "target", "statusNote", "extension", "history", "approx", "approxNote", "opened", "sources")


def build_projects():
    for scope, tol in (("intercity", 20), ("urban", 3)):
        jp, gp = HERE / "projects" / f"{scope}.json", HERE / "projects" / f"{scope}.geojson"
        if not jp.exists() or not gp.exists():
            continue
        data, net = json.loads(jp.read_text()), json.loads(gp.read_text())
        for c in data.get("cities", []):
            CITY.setdefault(c["key"], {"key": c["key"], "name": c["name"], "center": list(c["center"]), "radius": c["radius"]})
        feats = defaultdict(list)
        for f in net["features"]:
            feats[f["properties"]["line"]].append(f)
        have = {l["id"] for l in LINES}
        for l in data["lines"]:
            if l["id"] in have:
                print("  ! project id already on the map:", l["id"], file=sys.stderr)
                continue
            rec = {"id": l["id"], "city": l.get("city") or None, **{k: l[k] for k in PROJECT_KEYS if l.get(k) not in (None, "", [], False)}}
            if not rec["city"]:  # intercity lines take their type's code and colour, like the services from OSM
                rec["code"], rec["color"] = {"hst": "YHT", "main": "AH", "regional": "B"}[rec["type"]], TYPE_COLOR[rec["type"]]
            if l.get("osm_ways"):
                rec["osm_way"] = l["osm_ways"][0]
            parts, stations = [], []
            for f in feats[l["id"]]:
                g = f["geometry"]
                if g["type"] == "Point":
                    stations.append((f["properties"]["name"], g["coordinates"], f["properties"].get("existing")))
                else:
                    parts += [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            add_line(rec, parts, stations, tol)


# ---------------------------------------------------------------- base network
def build_base():
    feats = []
    for name, kind, tol in (("rail_ways", "rail", 60), ("construction_ways", "cons", 60)):
        ways = []
        for e in load(name):
            if "geometry" not in e:
                continue
            t = e.get("tags", {})
            if kind == "rail" and t.get("usage") in ("industrial", "military", "tourism"):
                continue
            ways.append([(n, [g["lon"], g["lat"]]) for n, g in zip(e["nodes"], e["geometry"])])
        for c in geo.chain_ways(ways):
            c = [r5(p, 4) for p in geo.simplify(c, tol)]
            if len(c) >= 2 and geo.length(c) > 150:
                feats.append({"type": "Feature", "properties": {"k": kind}, "geometry": {"type": "LineString", "coordinates": c}})
    return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    import ridership
    build_intercity()
    build_urban()
    build_istanbul()
    build_projects()
    ridership.attach(LINES, CITY)
    __import__("durations").attach(LINES, FEATURES)  # published journey times (build/durations/)
    OUT.mkdir(exist_ok=True)
    # cities: the urban lines in each and the intercity lines that stop there
    stops_by_line = defaultdict(list)
    for f in FEATURES:
        if f["geometry"]["type"] == "Point":
            stops_by_line[f["properties"]["line"]].append(f["geometry"]["coordinates"])
    cities = []
    for c in CITY.values():
        own = [l["id"] for l in LINES if l.get("city") == c["key"]]
        if not own:
            continue
        serving = [l["id"] for l in LINES if not l.get("city") and any(geo.dist(p, c["center"]) < c["radius"] * 1000 * .6 for p in stops_by_line[l["id"]])]
        cities.append({**{k: v for k, v in c.items() if k != "radius"}, "lines": own, "serving": serving, **ridership.city_totals(c["key"])})
    data = {"built": TODAY, "cities": cities, "groups": ridership.groups(), "lines": LINES}
    (OUT / "lines.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (OUT / "network.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": FEATURES}, ensure_ascii=False, separators=(",", ":")))
    (OUT / "base.geojson").write_text(json.dumps(build_base(), separators=(",", ":")))
    for p in sorted(OUT.iterdir()):
        print(f"{p.name}: {p.stat().st_size / 1e6:.2f} MB")
    print(f"{len(LINES)} lines, {len(cities)} cities")
