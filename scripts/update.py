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

# Prisalarm via den gratis tjeneste ntfy.sh. Skal passe med ALARM_PREFIX i index.html.
NTFY = "https://ntfy.sh/"
ALARM_PREFIX = "tankklar-q7m4"
ALARM_TIDER = ["2000", "2030", "2100", "2130", "2200"]
ALARM_NIVEAUER = ["alle", "10", "20", "30"]  # "alle" = hver aften, ellers kun ved stigning på mindst X øre
APP_URL = "https://tank-klar.pages.dev"
NAVNE = {"benzin": "Benzin 95", "diesel": "Diesel"}

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

def _tal(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


# --- kilde 1: Yahoo Finance ---
def yahoo(symbol):
    fejl = None
    for vaert in ("query2", "query1"):
        url = (f"https://{vaert}.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?range=1mo&interval=1d")
        try:
            res = json.loads(hent(url))["chart"]["result"][0]
            par = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
            (_, p0), (t1, p1) = par[-2], par[-1]
            return p0, p1, datetime.fromtimestamp(t1, tz=timezone.utc).astimezone(NY).date()
        except Exception as e:
            fejl = e
            time.sleep(2)
    raise fejl


# --- kilde 2: CNBC's offentlige kursdata ---
CNBC_SYMBOL = {"RB=F": "@RB.1", "HO=F": "@HO.1", "BZ=F": "@LCO.1"}


def cnbc(symbol):
    s = CNBC_SYMBOL[symbol]
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
           + urllib.parse.quote(s) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    q = json.loads(hent(url))["FormattedQuoteResult"]["FormattedQuote"][0]
    p1 = _tal(q.get("last"))
    p0 = _tal(q.get("previous_day_closing"))
    if p0 is None and p1 is not None and _tal(q.get("change")) is not None:
        p0 = p1 - _tal(q.get("change"))
    if p0 is None or p1 is None:
        raise ValueError(f"ingen kurs for {s}")
    dato = None
    try:
        dato = datetime.fromisoformat(str(q.get("last_time", ""))[:19]).date()
    except ValueError:
        pass
    return p0, p1, dato


# --- kilde 3: Nasdaq's offentlige kursdata ---
NASDAQ_SYMBOL = {"RB=F": "RB:NMX", "HO=F": "HO:NMX", "BZ=F": "BZ:NMX"}


def nasdaq(symbol):
    url = f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(NASDAQ_SYMBOL[symbol])}/info?assetclass=commodities"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                                               "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8"))["data"]["primaryData"]
    p1 = _tal(str(d.get("lastSalePrice", "")).replace("$", ""))
    ch = _tal(d.get("netChange"))
    if p1 is None or ch is None:
        raise ValueError("ingen kurs")
    dato = None
    try:
        dato = datetime.strptime(str(d.get("lastTradeTimestamp", ""))[:12].strip(), "%b %d, %Y").date()
    except ValueError:
        pass
    return p1 - ch, p1, dato


def lukkekurser(symbol):
    """Prøver kilderne efter tur og returnerer (forrige, seneste, handelsdato, kilde)."""
    for navn, fn in (("Yahoo", yahoo), ("CNBC", cnbc), ("Nasdaq", nasdaq)):
        try:
            p0, p1, dato = fn(symbol)
            return p0, p1, dato, navn
        except Exception as e:
            print(f"  ! {navn} {symbol}: {e}")
    raise RuntimeError(f"ingen kilde virkede for {symbol}")


# --- dollarkurs: Den Europæiske Centralbank via Frankfurter (gratis, åben) ---
def dollarkurs(idag):
    start = (idag - timedelta(days=10)).isoformat()
    for url in (f"https://api.frankfurter.dev/v1/{start}..?from=USD&to=DKK",
                f"https://api.frankfurter.app/{start}..?from=USD&to=DKK"):
        try:
            rater = json.loads(hent(url))["rates"]
            datoer = sorted(rater)
            return rater[datoer[-2]]["DKK"], rater[datoer[-1]]["DKK"]
        except Exception as e:
            print(f"  ! dollarkurs ({url.split('/')[2]}): {e}")
    p0, p1, _, _ = lukkekurser_fx()
    return p0, p1


def lukkekurser_fx():
    return yahoo("DKK=X") + ("Yahoo",)


def markedsdata(idag, advarsler):
    ud = {"handlet_i_dag": True}
    try:
        fx0, fx1 = dollarkurs(idag)
        ud["usd_dkk"] = round(fx1, 4)
        print(f"  Dollarkurs: {fx1:.4f}")
    except Exception as e:
        print(f"  ! dollarkurs: {e}")
        fx0 = fx1 = None
    try:
        b0, b1, _, kilde = lukkekurser("BZ=F")
        ud["brent_usd"] = round(b1, 2)
        ud["brent_pct"] = round((b1 - b0) / b0 * 100, 2)
        print(f"  Brent: {b1:.2f} USD ({kilde})")
    except Exception:
        pass
    if fx1 is None:
        advarsler.append("Dollarkursen kunne ikke hentes, så prognosen viser uændret pris")
        ud["fejl"] = True
        return ud
    kilder = set()
    try:
        for brændstof, symbol in (("benzin", "RB=F"), ("diesel", "HO=F")):
            p0, p1, dato, kilde = lukkekurser(symbol)
            kilder.add(kilde)
            aendring = (p1 * fx1 - p0 * fx0) / LITER_PR_GALLON * MOMS
            ud[brændstof + "_pct"] = round((p1 - p0) / p0 * 100, 2)
            if dato is not None and dato != idag:  # markedet har ikke handlet i dag (weekend/helligdag)
                aendring = 0.0
                ud["handlet_i_dag"] = False
            ud[brændstof] = round(aendring, 3)
        ud["kilde"] = " + ".join(sorted(kilder))
        print(f"  Markedsdata hentet fra {ud['kilde']}")
    except Exception as e:
        print(f"  ! markedsdata: {e}")
        advarsler.append("Benzin- og dieselkurserne kunne ikke hentes, så prognosen viser uændret pris")
        ud["fejl"] = True
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


# ---------- 4. prisalarmer ----------

def kr_tekst(v):
    return f"{v:.2f}".replace(".", ",")


def alarm_tekst(b, x):
    n, ø = NAVNE[b], round(abs(x["aendring"] or 0) * 100)
    if x["anbefaling"] == "tank_i_dag":
        return (f"Tank i dag – {n.lower()} stiger {ø} øre",
                f"{n} ventes at koste {kr_tekst(x['imorgen'])} kr. i morgen (i dag {kr_tekst(x['idag'])} kr.). Tank i aften, hvis du kan.")
    if x["anbefaling"] == "vent":
        return (f"Vent med at tanke – {n.lower()} falder {ø} øre",
                f"{n} ventes at koste {kr_tekst(x['imorgen'])} kr. i morgen (i dag {kr_tekst(x['idag'])} kr.).")
    return (f"{n} ventes uændret i morgen",
            f"Prisen ligger på ca. {kr_tekst(x['idag'])} kr. Tank, når det passer dig.")


def post_ntfy(data):
    req = urllib.request.Request(NTFY, data=json.dumps(data).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=20).read()
    time.sleep(1)


def planlæg(data, maal, nu):
    """Sender en ntfy-besked, forsinket til tidspunktet maal. Returnerer True hvis sendt."""
    if maal < nu - timedelta(minutes=15):
        return False  # tidspunktet er gået
    if maal > nu + timedelta(minutes=1):
        data["delay"] = str(int(maal.timestamp()))
    try:
        post_ntfy(data)
        return True
    except Exception as e:
        print(f"  ! besked {data['topic']}: {e}")
        return False


def send_el_alarmer(el, nu):
    if not el:
        return 0
    sendt = 0
    navne = {"DK1": "Vestdanmark", "DK2": "Østdanmark"}
    for omr in ("DK1", "DK2"):
        e = el.get(omr)
        if not e:
            continue
        s0 = e["billigst_start"]
        titel = f"Billigste strøm i morgen: kl. {s0:02d}–{s0 + 3:02d}"
        besked = (f"{navne[omr]}: {kr_tekst(e['billigst_gennemsnit'])} kr./kWh i de tre billigste timer "
                  f"(døgnets gennemsnit {kr_tekst(e['gennemsnit'])} kr.). Spotpris uden afgifter.")
        for tid in ALARM_TIDER:
            maal = nu.replace(hour=int(tid[:2]), minute=int(tid[2:]), second=0, microsecond=0)
            sendt += planlæg({"topic": f"{ALARM_PREFIX}-el-{omr}-{tid}", "title": titel, "message": besked,
                              "tags": ["electric_plug"], "click": APP_URL}, maal, nu)
    return sendt


def send_alarmer(braendstof, nu, el=None):
    import os
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        print("Prisalarmer sendes kun ved den automatiske kørsel om aftenen.")
        return
    sendt = 0
    for b, x in braendstof.items():
        if x["idag"] is None or x["metode"] == "uændret":
            continue  # ingen rigtig prognose i dag
        øre = round((x["aendring"] or 0) * 100)
        titel, besked = alarm_tekst(b, x)
        for niveau in ALARM_NIVEAUER:
            if niveau != "alle" and øre < int(niveau):
                continue
            for tid in ALARM_TIDER:
                maal = nu.replace(hour=int(tid[:2]), minute=int(tid[2:]), second=0, microsecond=0)
                sendt += planlæg({"topic": f"{ALARM_PREFIX}-{b}-{niveau}-{tid}", "title": titel, "message": besked,
                                  "tags": ["fuelpump"], "click": APP_URL}, maal, nu)
    print(f"Prisalarmer planlagt: {sendt}")
    print(f"Elbil-beskeder planlagt: {send_el_alarmer(el, nu)}")


# ---------- 5. saml det hele ----------

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
    el_idag = elpriser(idag, [])

    braendstof = {}
    for b in ("benzin", "diesel"):
        priser = [s[b] for s in selskaber if s[b] is not None]
        if priser:
            pris_idag, kilde = statistics.median(priser), "selskaberne"
        else:
            tidligere = [h[b] for h in historik if h.get(b) is not None]
            pris_idag, kilde = (tidligere[-1], "sidst kendte pris") if tidligere else (None, "ingen data")
        ok = bool(marked) and not marked.get("fejl") and marked.get(b) is not None
        aendring = marked[b] if ok else 0.0
        metode = "marked" if ok else "uændret"
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
        "el_idag": el_idag,
        "advarsler": advarsler,
    }

    if braendstof["benzin"]["idag"] is not None or braendstof["diesel"]["idag"] is not None or el_idag:
        historik = [h for h in historik if h["dato"] != idag.isoformat()]
        historik.append({"dato": idag.isoformat(),
                         # dagens gennemsnitlige elpris (spotpris) pr. område
                         "el_DK1": (el_idag or {}).get("DK1", {}).get("gennemsnit"),
                         "el_DK2": (el_idag or {}).get("DK2", {}).get("gennemsnit"),
                         "benzin": braendstof["benzin"]["idag"],
                         "diesel": braendstof["diesel"]["idag"],
                         # prognosen for næste dag – bruges til at måle, hvor præcis appen er
                         "prognose_benzin": braendstof["benzin"]["imorgen"],
                         "prognose_diesel": braendstof["diesel"]["imorgen"]})
        historik = sorted(historik, key=lambda h: h["dato"])[-90:]

    gem_json(DATA / "latest.json", latest)
    send_alarmer(braendstof, nu, el)
    gem_json(DATA / "history.json", historik)
    print(json.dumps(braendstof, ensure_ascii=False, indent=2))
    for a in advarsler:
        print("Advarsel:", a)


if __name__ == "__main__":
    main()
