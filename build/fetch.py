#!/usr/bin/env python3
# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Download the OpenStreetMap data the map is built from, through the Overpass API.

Every query's raw JSON response is cached under build/cache/<name>.json, so a rerun only fetches what is
missing (delete a file to refetch it). Responses are parsed as JSON data and nothing else.

    python3 build/fetch.py            # fetch what is missing
    python3 build/fetch.py --force    # refetch everything
"""
import json
import subprocess
import sys
import time
from pathlib import Path

API = "https://overpass-api.de/api/interpreter"
CACHE = Path(__file__).resolve().parent / "cache"
AREA = 'area["ISO3166-1"="TR"][admin_level=2]->.tr;'
UA = "harita_ray/1.0 (static map of Turkish passenger rail; +https://github.com/remrekoc/harita_ray)"

# Route relations with their member ways and stop nodes. "out body" plus a recursion keeps each way and node once,
# where "out geom" would repeat a shared track for every service on it.
ROUTES = lambda kind: f"""[out:json][timeout:600];{AREA}
rel["type"="route"]["route"="{kind}"](area.tr)->.r;
.r out body;
way(r.r)->.w; .w out body;
(node(w.w); node(r.r);)->.n; .n out body;"""

QUERIES = {
    "routes_train": ROUTES("train"),
    "routes_subway": ROUTES("subway"),
    "routes_light_rail": ROUTES("light_rail"),
    "routes_tram": ROUTES("tram"),
    "routes_monorail": ROUTES("monorail"),
    "routes_funicular": ROUTES("funicular"),
    # aerial cableways that run as public transport (teleferik)
    "aerialways": f"""[out:json][timeout:300];{AREA}
way["aerialway"~"^(gondola|cable_car|mixed_lift)$"](area.tr); out geom;""",
    "route_masters": f"""[out:json][timeout:300];{AREA}
rel["type"="route_master"]["route_master"~"^(train|subway|light_rail|tram|monorail|funicular)$"](area.tr); out body;""",
    # the physical network: running lines, without yards, sidings and spurs
    "rail_ways": f"""[out:json][timeout:600];{AREA}
way["railway"="rail"][!"service"](area.tr); out geom qt;""",
    # urban rail track (for context where a route relation is incomplete)
    # sidings, crossovers and yards: they join the running lines at junctions and stations, for routing
    "rail_service": f"""[out:json][timeout:600];{AREA}
way["railway"="rail"]["service"~"^(siding|crossover|yard|spur)$"](area.tr); out geom qt;""",
    "urban_ways": f"""[out:json][timeout:600];{AREA}
way["railway"~"^(subway|light_rail|tram|monorail|funicular|narrow_gauge)$"][!"service"](area.tr); out geom qt;""",
    "construction_ways": f"""[out:json][timeout:600];{AREA}
way["railway"="construction"]["construction"~"^(rail|subway|light_rail|tram|monorail)$"](area.tr); out geom qt;""",
    "stations": f"""[out:json][timeout:300];{AREA}
(node["railway"~"^(station|halt|tram_stop)$"](area.tr);
 node["public_transport"="station"]["train"="yes"](area.tr););
out body qt;""",
}


def fetch(name, q, force=False):
    path = CACHE / f"{name}.json"
    if path.exists() and not force:
        print(f"cached  {name} ({path.stat().st_size / 1e6:.1f} MB)")
        return False
    for attempt in range(6):
        try:
            # curl rather than urllib: the system Python's TLS cannot talk to the Overpass servers
            r = subprocess.run(["curl", "-s", "-f", "-m", "900", "-A", UA, "--data-urlencode", "data@-", API],
                               input=q.encode(), capture_output=True)
            if r.returncode:
                raise RuntimeError(f"curl exit {r.returncode}")
            raw = r.stdout
            data = json.loads(raw)  # data only: fail here if it is not JSON
            if data.get("remark") and "error" in data["remark"].lower():
                raise RuntimeError(data["remark"])
            path.write_bytes(raw)
            print(f"fetched {name}: {len(data.get('elements', []))} elements, {len(raw) / 1e6:.1f} MB")
            return True
        except Exception as e:  # rate limits and timeouts: back off and retry
            wait = 30 * 2 ** attempt
            print(f"  {name}: {e}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"could not fetch {name}")


if __name__ == "__main__":
    CACHE.mkdir(parents=True, exist_ok=True)
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for name, q in QUERIES.items():
        if only and name not in only:
            continue
        if fetch(name, q, force):
            time.sleep(8)  # be polite between calls
