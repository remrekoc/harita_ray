# Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
"""Attach the sourced ridership figures in build/ridership/*.json to the lines and cities.

Rules: a figure is shown only with its year and source. An average daily figure is either the one the source
states ("reported") or the annual total divided by the days it covers ("derived", shown as "ortalama günlük").
Where only a network or corridor total exists, it is attached as a group figure and labelled as such."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent / "ridership"
IST = json.loads((HERE / "istanbul.json").read_text())
URB = json.loads((HERE / "urban.json").read_text())
INT = json.loads((HERE / "intercity.json").read_text())

PREC = {"exact": "exact", "approx": "approx", "lower bound": "lower", None: "exact"}


def find(recs, **kw):
    for r in recs:
        if all((r.get(k) == v) if not callable(v) else v(r.get(k)) for k, v in kw.items()):
            return r
    return None


def days(r):
    if r.get("days"):
        return r["days"]
    y = r.get("year")
    return 366 if y and y % 4 == 0 else 365


def derived_tr(d):
    """The research notes are in English; the page shows a short Turkish description of how a total was formed."""
    import re
    m = re.search(r"sum of (\d+) (daily|monthly)", d or "")
    if m:
        return f"{m.group(1)} {'günlük' if m.group(2) == 'daily' else 'aylık'} değerin toplamı"
    return "kaynaktaki değerlerin toplamı" if d else None


def src(r):
    out = {"url": r.get("source"), "title": r.get("sourceTitle"), "publisher": r.get("publisher")}
    if r.get("sourceOriginal"):
        out["original"] = r["sourceOriginal"]
    if r.get("unit"):
        out["unit"] = r["unit"]
    if r.get("derived"):
        out["derived"] = derived_tr(r["derived"])
    return {k: v for k, v in out.items() if v}


def figure(r, daily_rec=None, label=None, season=False):
    """One ridership block: annual (with year), average daily, and where both came from."""
    if not r and not daily_rec:
        return None
    out = {}
    if r and r.get("annual"):
        out["annual"] = r["annual"]
        out["year"] = r.get("year")
        out["period"] = r.get("period") or str(r.get("year"))
        out["precision"] = PREC.get(r.get("precision"), "exact")
        out["src"] = src(r)
        if r.get("partial"):
            out["partial"] = True
        if season:
            out["season"] = True
        elif r.get("daily"):
            out["daily"], out["dailyKind"] = r["daily"], "reported"
        else:
            out["daily"], out["dailyKind"] = round(r["annual"] / days(r)), "derived"
    # a stated daily average wins over one derived from a rounded annual figure, if it is itself exact
    exact_daily = daily_rec and daily_rec.get("daily") and PREC.get(daily_rec.get("precision"), "exact") == "exact"
    if exact_daily and out.get("dailyKind") == "derived" and out.get("precision") != "exact":
        out.pop("daily")
    if daily_rec and daily_rec.get("daily") and "daily" not in out and not out.get("season"):
        out["daily"], out["dailyKind"] = daily_rec["daily"], "reported"
        out["dailyYear"] = daily_rec.get("year")
        out["dailyPrecision"] = PREC.get(daily_rec.get("precision"), "exact")
        out["dailySrc"] = src(daily_rec)
    if label:
        out["label"] = label
    return out


def ist(code):
    return find(IST, line=code) if code else None


def urb(city, line):
    return find(URB, city=city, line=line)


def urb_sys(city):
    return find(URB, city=city, scope="system")


def icy(line, year=None, **kw):
    return find(INT, line=line, **({"year": year} if year else {}), **kw)


def icy_daily(line):
    return find(INT, line=line, annual=None, daily=lambda v: bool(v))


def line_figure(l):
    """(own figure, group figure) for a line."""
    lid, city = l["id"], l.get("city")
    if city == "istanbul":
        code = l.get("src") or l["code"]
        if l.get("status") != "open":
            return None, None
        if code in ("M1A", "M1B"):
            return None, figure(ist("M1"), label="M1A ve M1B hatlarının toplamı")
        if code == "m2-seyrantepe":
            return None, figure(ist("M2"), label="M2 hattının toplamı (Seyrantepe kolu dahil)")
        if code == "B1":
            return figure(icy("Marmaray", 2024), icy_daily("Marmaray")), None
        if code == "U3":
            return figure(icy("Kazlıçeşme–Sirkeci", 2024)), None
        if code == "M11":
            return figure(icy("Gayrettepe–İstanbul Havalimanı metrosu", 2024)), None
        r = ist(code) or ist(l["code"])
        return (figure(r) if r and r.get("annual") else None), None
    if city == "ankara":
        if lid == "ankara-baskentray":
            return figure(icy("Başkentray", 2024), icy_daily("Başkentray")), None
        code = {"ankara-a1": "A1"}.get(lid, l["code"])
        r = urb("Ankara", code)
        return (figure(r) if r else None), None
    if city == "izmir":
        if lid == "izmir-izban":
            return figure(icy("İZBAN", 2024), icy_daily("İZBAN")), None
        r = urb("İzmir", l["code"])
        return (figure(r) if r else None), None
    if city == "bursa":
        if l["code"] in ("B1", "B2"):
            return None, figure(urb("Bursa", "BursaRay"), label="BursaRay toplamı (iki kol birlikte)")
        r = urb("Bursa", l["code"])
        return (figure(r) if r else None), None
    if city == "adana":
        return figure(urb("Adana", "M1")), None
    if city == "gaziantep" and lid == "gaziantep-gaziray":
        g = find(URB, city="Gaziantep", scope="system")
        # the municipality's 2025 report tabulates Gaziray beside the trams; its note carries the figure
        return None, None
    if city == "sakarya":
        return figure(None, icy_daily("Adaray")), None
    if city == "antalya" and "nostalji" in (l.get("alias", "") + l["name"]).lower():
        return figure(urb("Antalya", "Nostalji")), None
    labels = {"konya": "Konya tramvay hatları toplamı", "kayseri": "Kayseray (T1–T4) toplamı", "eskisehir": "Estram hatları toplamı",
              "antalya": "AntRay hatları toplamı", "gaziantep": "Gaziantep tramvay hatları toplamı", "samsun": "Samsun tramvayı toplamı",
              "kocaeli": "Akçaray hatları toplamı"}
    if city in labels and l["type"] == "tram":
        cname = {"konya": "Konya", "kayseri": "Kayseri", "eskisehir": "Eskişehir", "antalya": "Antalya", "gaziantep": "Gaziantep",
                 "samsun": "Samsun", "kocaeli": "Kocaeli"}[city]
        return None, figure(urb_sys(cname), label=labels[city])
    if city is None:  # intercity
        ride = l.get("ride")
        if l["type"] == "hst":
            annual = {"Ankara–İstanbul YHT": icy("Ankara–İstanbul YHT", 2025), "Konya–İstanbul YHT": icy("Konya–İstanbul YHT", 2025)}.get(ride)
            own = figure(annual, icy_daily(ride))
            grp = None
            if ride in ("Ankara–Konya YHT", "Ankara–Karaman YHT"):
                grp = figure(icy("Ankara–Konya–Karaman YHT"), label="Ankara–Konya–Karaman YHT koridoru toplamı")
            elif ride == "İstanbul–Karaman YHT":
                grp = figure(icy("İstanbul–Konya–Karaman YHT"), label="İstanbul–Konya–Karaman YHT koridoru toplamı")
            return own, grp
        if ride == "Turistik Doğu Ekspresi":
            return figure(icy("Turistik Doğu Ekspresi"), season=True), None
        return None, figure(icy("Ana hat + bölgesel toplam", 2024), label="Tüm ana hat ve bölgesel trenlerin toplamı")
    return None, None


def attach(lines, cities):
    for l in lines:
        own, grp = line_figure(l)
        if own:
            l["ride"] = own
        if grp:
            l["rideGroup"] = grp
    # Gaziray: the Gaziantep report tabulates it next to the trams (see the record's note)
    g = find(URB, city="Gaziantep", scope="system")
    for l in lines:
        if l["id"] == "gaziantep-gaziray" and g and "3.089.193" in (g.get("note") or ""):
            r = dict(g, annual=3089193, scope="line", note="Gaziantep Büyükşehir Belediyesi 2025 Faaliyet Raporu, Tablo 28: Gaziray satırı.", derived=None)
            l["ride"] = figure(r, icy_daily("Gaziray"))


CITY_NAME = {"istanbul": "İstanbul", "ankara": "Ankara", "izmir": "İzmir", "bursa": "Bursa", "konya": "Konya", "kayseri": "Kayseri",
             "eskisehir": "Eskişehir", "antalya": "Antalya", "gaziantep": "Gaziantep", "samsun": "Samsun", "kocaeli": "Kocaeli", "adana": "Adana"}
CITY_LABEL = {"istanbul": "Metro İstanbul hatları (M1–M9, T1, T3–T5, F1, F4, TF1–TF2)", "ankara": "EGO raylı sistemleri (Ankaray ve M1–M4)",
              "izmir": "İzmir Metro A.Ş. hatları (metro ve tramvaylar)", "bursa": "BURULAŞ raylı sistemleri (BursaRay ve tramvaylar)",
              "konya": "Konya tramvayı", "kayseri": "Kayseray", "eskisehir": "Estram", "antalya": "AntRay", "gaziantep": "Gaziantep tramvayı",
              "samsun": "Samsun tramvayı", "kocaeli": "Akçaray"}
CITY_SHORT = {"istanbul": "Metro İstanbul", "ankara": "EGO", "izmir": "İzmir Metro A.Ş.", "bursa": "BURULAŞ", "konya": "tramvay", "kayseri": "Kayseray",
              "eskisehir": "Estram", "antalya": "AntRay", "gaziantep": "tramvay", "samsun": "tramvay", "kocaeli": "Akçaray"}


def city_totals(key):
    """The operator's network total for a city, when the source gives one."""
    if key == "istanbul":
        r = find(IST, scope="system")
    elif key in CITY_NAME:
        r = urb_sys(CITY_NAME[key])
    else:
        r = None
    if not r or not r.get("annual"):
        return {}
    f = figure(r, label=CITY_LABEL.get(key, "Kent içi raylı sistem toplamı"))
    f["short"] = CITY_SHORT.get(key, "")
    return {"ride": f}


def groups():
    out = []
    for line, label in (("TCDD Taşımacılık toplam", "TCDD Taşımacılık, tüm yolcu trenleri"), ("YHT toplam", "Yüksek hızlı trenler (YHT)"),
                        ("Ana hat + bölgesel toplam", "Ana hat ve bölgesel trenler")):
        r = icy(line, 2024)
        if r:
            out.append(figure(r, label=label))
    return out
