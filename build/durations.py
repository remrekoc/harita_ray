# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Attach the published journey times in build/durations/*.json to the lines (field "dur").

Rules, as strict as the ridership data: a time is shown only as an official source published it, with its date and
source. Nothing is estimated: no times from distance or speed, no stop times interpolated from an end-to-end figure.
Per-stop minutes come only from an operator's own GTFS timetable. One value is derived: average speed = published
km ÷ published time, shown as "ortalama hız". A maximum speed is shown only as published, with what it refers to."""
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent / "durations"
RECS = [r for f in sorted(HERE.glob("*.json")) for r in json.loads(f.read_text())]

# GTFS stop names that are spelled differently from the station names on the map (keys and values normalised)
ALIAS = {"a a s s m": "ahmed adnan saygun sanat merkezi", "mustafa kemal spor salonu": "mustafa kemal ataturk spor salonu",
         "carsi duragi": "carsi", "uckuyular iskele": "uckuyular", "alsancak stadyumu": "alsancak stadyum",
         "kaymakamlik": "narlidere kaymakamlik", "guzel sanatlar": "guzel sanatlar fakultesi"}


def norm(s):
    s = re.sub(r"\(.*?\)", " ", s.replace("İ", "i").replace("I", "ı").lower())
    s = unicodedata.normalize("NFD", s).replace("ı", "i")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def src(r):
    return {k: r[k] for k in ("publisher", "title", "url", "date") if r.get(k)}


def match(name, stations, misses):
    """The line's own station name for a timetable stop name."""
    by = {norm(s): s for s in stations}
    k = norm(name)
    if k in by:
        return by[k]
    if ALIAS.get(k) in by:
        return by[ALIAS[k]]
    misses.append(name)
    return name


def figure(r, stations):
    misses = []
    dirs = []
    for d in r.get("dirs") or [{"label": r.get("label"), "min": r["min"]}]:
        out = {"min": round(d["min"], 2)}
        if d.get("stops"):
            out["stops"] = [[match(n, stations, misses), round(t, 2)] for n, t in d["stops"]]
            auto = f"{d['stops'][0][0]} → {d['stops'][-1][0]}"
            out["label"] = f"{out['stops'][0][0]} → {out['stops'][-1][0]}" if d.get("label") in (None, auto) else d["label"]
        else:
            out["label"] = d.get("label") or r.get("label")
        for k in ("dep", "arr"):
            if d.get(k):
                out[k] = d[k]
        dirs.append(out)
    dur = {"dirs": dirs, "src": src(r)}
    for k in ("bound", "approx", "train", "note", "basis", "stopsIncluded"):
        if r.get(k):
            dur[k] = r[k]
    if r.get("kind") == "gtfs":
        dur["gtfs"] = True
    # the one derived value: published length over published time, for a single stated figure
    if r.get("km") and len(dirs) == 1 and not r.get("bound"):
        dur["km"] = r["km"]
        dur["avg"] = round(r["km"] / (dirs[0]["min"] / 60))
        if r.get("round") or r.get("approx"):
            dur["avgApprox"] = True
    if r.get("vmax"):
        v = r["vmax"]
        dur["vmax"] = {"kmh": v["kmh"], "kind": v["kind"], **({"scope": v["scope"]} if v.get("scope") else {}), "src": src(v)}
    return dur, misses


def attach(lines, features):
    stations = defaultdict(list)
    for f in features:
        if f["geometry"]["type"] == "Point":
            stations[f["properties"]["line"]].append(f["properties"]["name"])
    by = {l["id"]: l for l in lines}
    for r in RECS:
        l = by.get(r["line"])
        if not l:
            print(f"durations: no line {r['line']}")
            continue
        dur, misses = figure(r, stations[l["id"]])
        if misses:
            print(f"durations: {l['id']}: stops not matched to stations: {', '.join(misses)}")
        l["dur"] = dur
