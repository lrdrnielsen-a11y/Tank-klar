#!/usr/bin/env python3
"""
Tank klar – opdateringsscript.

Kører hver aften via GitHub Actions og:
  1. henter dagens priser for alle kæder fra BenzinSignals åbne data
  2. henter benzin-/dieselfutures og dollarkursen og beregner morgendagens prognose
  3. henter morgendagens elpriser (spotpris) fra Energi Data Service
  4. gemmer det hele i data/latest.json og data/history.json

Bruger kun Pythons standardbibliotek, så intet skal installeres.
"""
import html
import json
import re
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROD = Path(__file__).resolve().parent.parent
DATA = ROD / "data"
DK = ZoneInfo("Europe/Copenhagen")
NY = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
LITER_PR_GALLON = 3.78541
MOMS = 1.25
TAERSKEL = 0.03  # kr/l: mindre ændringer end dette regnes som "uændret"

STANDARD_ORD = {
    "benzin": ["Blyfri 95", "Benzin 95", "Oktan 95", "95 E10", "Blyfri"],
    "diesel": ["Diesel"],
}
PRIS = re.compile(r"(?<!\d)(\d{1,2})[,.](\d{2})(?!\d)")


# ---------- hjælpefunktioner ----------

def hent(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "da-DK,da;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def lad_json(sti, standard):
    try:
        return json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return standard


def gem_json(sti, data):
    sti.parent.mkdir(parents=True, exist_ok=True)
    sti.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ren_tekst(kilde):
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", kilde)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def find_pris(tekst, noegleord):
    """Finder den første pris (8–30 kr) lige efter et af nøgleordene."""
    for ord_ in noegleord:
        for m in re.finditer(re.escape(ord_), tekst, re.I):
            for p in PRIS.finditer(tekst[m.end(): m.end() + 160]):
                v = float(f"{p.group(1)}.{p.group(2)}")
                if 8 <= v <= 30:
                    return v
    return None


def r2(v):
    return None if v is None else round(v, 2)


# ---------- 1. selskabernes priser ----------

BENZINSIGNAL = "https://benzinsignal.dk/data/priser.json"


def hent_benzinsignal(advarsler):
    """Åbne data fra BenzinSignal (benzinsignal.dk/data). Priser i øre pr. liter."""
    try:
        data = json.loads(hent(BENZINSIGNAL))
    except Exception as e:
        print(f"  ! BenzinSignal: {e}")
        advarsler.append("Priserne fra BenzinSignal kunne ikke hentes")
        return []
    ud = []
    for k in data.get("by_brand", []):
        b, d = k.get("avg_benzin95"), k.get("avg_diesel")
        if not k.get("reporting_currently", True) or (b is None and d is None):
            continue
        ud.append({"navn": k["brand"],
                   "benzin": round(b / 100, 2) if b else None,
                   "diesel": round(d / 100, 2) if d else None})
        print(f"  {k['brand']}: benzin {ud[-1]['benzin']}, diesel {ud[-1]['diesel']}")
    if not ud:
        advarsler.append("BenzinSignal leverede ingen priser")
    return ud


# ---------- 2. markedet ----------

def lukkekurser(symbol):
    fejl = None
    for vaert in ("query1", "query2", "query1"):
        url = (f"https://{vaert}.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?range=1mo&interval=1d")
        try:
            res = json.loads(hent(url))["chart"]["result"][0]
            break
        except Exception as e:
            fejl = e
            time.sleep(3)
    else:
        raise fejl
    par = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
    (_, p0), (t1, p1) = par[-2], par[-1]
    dato = datetime.fromtimestamp(t1, tz=timezone.utc).astimezone(NY).date()
    return p0, p1, dato


def markedsdata(idag, advarsler):
    try:
        fx0, fx1, _ = lukkekurser("DKK=X")
        ud = {"usd_dkk": round(fx1, 4), "handlet_i_dag": True}
        for brændstof, symbol in (("benzin", "RB=F"), ("diesel", "HO=F")):
            p0, p1, dato = lukkekurser(symbol)
            aendring = (p1 * fx1 - p0 * fx0) / LITER_PR_GALLON * MOMS
            ud[brændstof + "_pct"] = round((p1 - p0) / p0 * 100, 2)
            if dato != idag:  # markedet har ikke handlet i dag (weekend/helligdag)
                aendring = 0.0
                ud["handlet_i_dag"] = False
            ud[brændstof] = round(aendring, 3)
    except Exception as e:
        print(f"  ! markedsdata: {e}")
        advarsler.append("Markedsdata kunne ikke hentes, så prognosen viser uændret pris")
        return None
    try:
        b0, b1, _ = lukkekurser("BZ=F")
        ud["brent_usd"] = round(b1, 2)
        ud["brent_pct"] = round((b1 - b0) / b0 * 100, 2)
    except Exception:
        pass
    return ud


# ---------- 3. elpris ----------

def elpriser(dag, advarsler):
    q = urllib.parse.urlencode({
        "start": dag.isoformat(),
        "end": (dag + timedelta(days=1)).isoformat(),
        "filter": json.dumps({"PriceArea": ["DK1", "DK2"]}),
        "sort": "TimeDK asc",
        "limit": 0,
    })
    try:
        poster = json.loads(hent("https://api.energidataservice.dk/dataset/DayAheadPrices?" + q)).get("records", [])
    except Exception as e:
        print(f"  ! elpris: {e}")
        advarsler.append("Elpriser kunne ikke hentes")
        return None
    if not poster:
        advarsler.append("Morgendagens elpriser er ikke offentliggjort endnu")
        return None
    ud = {"dato": dag.isoformat()}
    for omraade in ("DK1", "DK2"):
        timer = {}
        for p in poster:
            if p.get("PriceArea") != omraade or p.get("DayAheadPriceDKK") is None:
                continue
            timer.setdefault(int(p["TimeDK"][11:13]), []).append(p["DayAheadPriceDKK"] / 1000)
        if len(timer) < 20:
            continue
        pr_time = [round(statistics.mean(timer[h]), 3) if h in timer else None for h in range(24)]
        gyldige = [v for v in pr_time if v is not None]
        vinduer = [(h, statistics.mean(pr_time[h:h + 3])) for h in range(22)
                   if None not in pr_time[h:h + 3]]
        start, gns = min(vinduer, key=lambda x: x[1])
        ud[omraade] = {
            "gennemsnit": round(statistics.mean(gyldige), 3),
            "billigst_start": start,
            "billigst_gennemsnit": round(gns, 3),
            "timer": pr_time,
        }
    return ud if len(ud) > 1 else None


# ---------- 4. saml det hele ----------

def anbefaling(aendring):
    if aendring is None:
        return "ukendt"
    if aendring <= -TAERSKEL:
        return "vent"
    if aendring >= TAERSKEL:
        return "tank_i_dag"
    return "lige_meget"


def main():
    nu = datetime.now(DK)
    idag = nu.date()
    imorgen = idag + timedelta(days=1)
    advarsler = []

    override = lad_json(ROD / "override.json", {})
    historik = lad_json(DATA / "history.json", [])
    historik = [h for h in historik if not h.get("demo")]

    print("Henter selskabernes priser fra BenzinSignal ...")
    selskaber = hent_benzinsignal(advarsler)
    print("Henter markedsdata ...")
    marked = markedsdata(idag, advarsler)
    print("Henter elpriser ...")
    el = elpriser(imorgen, advarsler)

    braendstof = {}
    for b in ("benzin", "diesel"):
        priser = [s[b] for s in selskaber if s[b] is not None]
        if priser:
            pris_idag, kilde = statistics.median(priser), "selskaberne"
        else:
            tidligere = [h[b] for h in historik if h.get(b) is not None]
            pris_idag, kilde = (tidligere[-1], "sidst kendte pris") if tidligere else (None, "ingen data")
        aendring = marked[b] if marked else 0.0
        metode = "marked" if marked else "uændret"
        if override.get("dato") == imorgen.isoformat() and override.get(b) is not None:
            if pris_idag is not None:
                aendring = float(override[b]) - pris_idag
            pris_idag = pris_idag if pris_idag is not None else float(override[b])
            metode = "manuel"
        braendstof[b] = {
            "idag": r2(pris_idag),
            "imorgen": r2(pris_idag + aendring) if pris_idag is not None else None,
            "aendring": r2(aendring),
            "anbefaling": anbefaling(aendring) if pris_idag is not None else "ukendt",
            "kilde_idag": kilde,
            "metode": metode,
        }

    for s in selskaber:
        for b in ("benzin", "diesel"):
            s[f"{b}_imorgen"] = r2(s[b] + braendstof[b]["aendring"]) if s[b] is not None else None

    latest = {
        "demo": False,
        "opdateret": nu.isoformat(timespec="minutes"),
        "idag": idag.isoformat(),
        "imorgen": imorgen.isoformat(),
        "braendstof": braendstof,
        "selskaber": selskaber,
        "kilde": "BenzinSignal (benzinsignal.dk/data)",
        "marked": marked,
        "el": el,
        "advarsler": advarsler,
    }

    if braendstof["benzin"]["idag"] is not None or braendstof["diesel"]["idag"] is not None:
        historik = [h for h in historik if h["dato"] != idag.isoformat()]
        historik.append({"dato": idag.isoformat(),
                         "benzin": braendstof["benzin"]["idag"],
                         "diesel": braendstof["diesel"]["idag"],
                         # prognosen for næste dag – bruges til at måle, hvor præcis appen er
                         "prognose_benzin": braendstof["benzin"]["imorgen"],
                         "prognose_diesel": braendstof["diesel"]["imorgen"]})
        historik = sorted(historik, key=lambda h: h["dato"])[-90:]

    gem_json(DATA / "latest.json", latest)
    gem_json(DATA / "history.json", historik)
    print(json.dumps(braendstof, ensure_ascii=False, indent=2))
    for a in advarsler:
        print("Advarsel:", a)


if __name__ == "__main__":
    main()
