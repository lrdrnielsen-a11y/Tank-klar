"""
Henter den aktuelle pumpepris på hver enkelt tankstation fra kædernes officielle,
åbne API'er (krævet ved lov siden 1. januar 2026) og gemmer dem i data/stationer.json.

Kæder uden nøgle: OK, Q8 + F24, Shell, OIL! og Circle K + INGO.
Stationer uden koordinater (Q8/F24 og Circle K/INGO) placeres via det danske
adresseregister (DAWA), og resultatet huskes i data/geokode.json.

Endpoints og produktkoder er fundet med hjælp fra det MIT-licenserede projekt
github.com/laithsaid/ha-tankpriser.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; TankKlar/1.0; +https://tank-klar.pages.dev)"

Q8_URL = "https://beta.q8.dk/Station/GetStationPrices?page=1&pageSize=2000"
SHELL_URL = "https://shellpumpepriser.geoapp.me/v1/prices"
OK_URL = "https://mobility-prices.ok.dk/api/v1/fuel-prices"
OIL_URL = "https://apim-fuel-prices-prod.azure-api.net/Oil-FuelPrices/prices"
CIRCLEK_URL = "https://api.circlek.com/eu/prices/v1/fuel/countries/DK"
DAWA_URL = "https://api.dataforsyningen.dk/adresser"

# Produktkoder -> "benzin" (95) / "diesel" (almindelig)
Q8_PRODUKT = {"2": "benzin", "6": "diesel"}
SHELL_PRODUKT = {"Blyfri 95": "benzin", "FuelSave Diesel": "diesel"}
OK_PRODUKT = {"Blyfri 95": "benzin", "Svovlfri Diesel": "diesel"}
OIL_PRODUKT = {"95E10": "benzin", "DieselB7": "diesel"}
CIRCLEK_PRODUKT = {"1030921": "benzin", "592327": "benzin",
                   "1030928": "diesel", "797325": "diesel", "1030946": "diesel"}

POSTNR = re.compile(r"\b(\d{4})\b")


def _hent_json(url, headere=None, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headere or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _tal(v):
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def _dato(v):
    return str(v or "").replace("T", " ").split(" ")[0]


def _station(sid, kæde, adresse, postnr, by, lat, lon):
    return {"id": sid, "kæde": kæde, "adresse": adresse.strip(), "postnr": postnr, "by": by.strip(),
            "lat": lat, "lon": lon, "benzin": None, "diesel": None, "opdateret": ""}


def _sæt_pris(st, nøgle, pris, dato=""):
    if pris is None or not (5 < pris < 40):
        return
    if st[nøgle] is None or pris < st[nøgle]:  # flere koder for samme produkt: tag den laveste
        st[nøgle] = pris
    st["opdateret"] = max(st["opdateret"], _dato(dato))


# ---------- kæderne ----------

def hent_ok():
    ud = []
    for r in (_hent_json(OK_URL) or {}).get("items", []) or []:
        k = r.get("coordinates") or {}
        adr = " ".join(p for p in (str(r.get("street", "")).strip(), str(r.get("house_number") or "").strip()) if p)
        st = _station(f"ok-{r.get('id') or adr}", "OK", adr, str(r.get("postal_code", "")).strip(),
                      str(r.get("city", "")), _tal(k.get("latitude")), _tal(k.get("longitude")))
        for p in r.get("prices", []) or []:
            n = OK_PRODUKT.get(str(p.get("product_name", "")).strip())
            if n:
                _sæt_pris(st, n, _tal(p.get("price")), r.get("last_updated_time"))
        ud.append(st)
    return ud


def hent_q8():
    ud = []
    for r in (_hent_json(Q8_URL) or {}).get("data", {}).get("stationsPrices", []) or []:
        adresse = str(r.get("address", "")).strip()
        m = POSTNR.findall(adresse)
        if not m:
            continue
        postnr = m[-1]
        gade, _, rest = adresse.partition(postnr)
        by = re.sub(r"\s*Danmark\s*$", "", rest).strip(" ,")
        kæde = "F24" if "F24" in str(r.get("stationName", "")).upper() else "Q8"
        st = _station(f"q8-{r.get('stationId') or adresse}", kæde, gade.strip(" ,"), postnr, by, None, None)
        for p in r.get("products", []) or []:
            n = Q8_PRODUKT.get(str(p.get("productId")))
            if n:
                _sæt_pris(st, n, _tal(p.get("price")), p.get("priceChangeDate"))
        ud.append(st)
    return ud


def hent_shell():
    ud = []
    for r in _hent_json(SHELL_URL) or []:
        k = r.get("coordinates") or {}
        adr = " ".join(p for p in (str(r.get("street", "")).strip(), str(r.get("houseNumber") or "").strip()) if p)
        st = _station(f"shell-{r.get('stationId') or adr}", "Shell", adr, str(r.get("postalCode", "")).strip(),
                      str(r.get("city", "")), _tal(k.get("latitude")), _tal(k.get("longitude")))
        for p in r.get("prices", []) or []:
            n = SHELL_PRODUKT.get(str(p.get("productName", "")).strip())
            if n:
                _sæt_pris(st, n, _tal(p.get("price")), p.get("lastUpdated"))
        ud.append(st)
    return ud


def _gps(tekst):
    lat = lon = None
    for del_ in str(tekst or "").split(","):
        t = del_.strip().split()
        if len(t) == 2 and _tal(t[0]) is not None:
            v = float(t[0].replace(",", "."))
            if t[1].upper() in ("N", "S"):
                lat = -v if t[1].upper() == "S" else v
            elif t[1].upper() in ("E", "W"):
                lon = -v if t[1].upper() == "W" else v
    return lat, lon


def hent_oil():
    samlet = {}
    for kode, n in OIL_PRODUKT.items():
        for r in _hent_json(f"{OIL_URL}?fuelType={kode}") or []:
            sid = str(r.get("station_id"))
            st = samlet.get(sid)
            if st is None:
                adresse = str(r.get("address", "")).strip()
                m = POSTNR.findall(adresse)
                if not m:
                    continue
                gade, _, rest = adresse.partition(m[-1])
                lat, lon = _gps(r.get("gps"))
                st = samlet[sid] = _station(f"oil-{sid}", "OIL!", gade.strip(" ,"), m[-1], rest.strip(" ,"), lat, lon)
            _sæt_pris(st, n, _tal(r.get(kode)), r.get("updated"))
    return list(samlet.values())


def hent_circlek():
    ud = []
    data = _hent_json(CIRCLEK_URL, {"X-App-Name": "PRICES"}, timeout=60)
    for r in (data or {}).get("sites", []) or []:
        a = r.get("address") or {}
        navn = str(r.get("name", "")).strip()
        kæde = "INGO" if navn.upper().startswith("INGO") else "Circle K"
        st = _station(f"ck-{r.get('id')}", kæde, str(a.get("street", "")), str(a.get("postalCode", "")).strip(),
                      str(a.get("city", "")), None, None)
        for p in r.get("fuelPrices", []) or []:
            n = CIRCLEK_PRODUKT.get(str(p.get("code", "")).strip())
            if n:
                _sæt_pris(st, n, _tal(p.get("price")), p.get("lastUpdated"))
        ud.append(st)
    return ud


# ---------- placering af stationer uden koordinater ----------

def _dawa(tekst, fuzzy=False):
    q = {"q": tekst, "struktur": "mini", "per_side": "1"}
    url = DAWA_URL + "?" + urllib.parse.urlencode(q) + ("&fuzzy=" if fuzzy else "")
    try:
        d = _hent_json(url, timeout=20)
    except Exception:
        return None
    return d[0] if isinstance(d, list) and d and d[0].get("x") is not None else None


def geokod(stationer, cache, maks=700):
    nye = 0
    for st in stationer:
        if st["lat"] is not None or not st["adresse"] or not st["postnr"]:
            continue
        nøgle = f"{st['adresse']} {st['postnr']}".lower()
        if nøgle in cache:
            if cache[nøgle]:
                st["lat"], st["lon"] = cache[nøgle]
            continue
        if nye >= maks:
            continue
        nye += 1
        hit = None
        for tekst, fuzzy in ((f"{st['adresse']}, {st['postnr']} {st['by']}", False),
                             (f"{st['adresse']}, {st['postnr']} {st['by']}", True)):
            h = _dawa(tekst, fuzzy)
            if h and str(h.get("postnr")) == st["postnr"]:
                hit = h
                break
        cache[nøgle] = [round(hit["y"], 6), round(hit["x"], 6)] if hit else None
        if hit:
            st["lat"], st["lon"] = cache[nøgle]
        time.sleep(0.05)
    return nye


# ---------- samlet ----------

KILDER = (("OK", hent_ok), ("Q8/F24", hent_q8), ("Shell", hent_shell), ("OIL!", hent_oil), ("Circle K/INGO", hent_circlek))


def hent_alle(cache):
    alle, status = [], {}
    for navn, fn in KILDER:
        try:
            s = [x for x in fn() if x["benzin"] is not None or x["diesel"] is not None]
            alle += s
            status[navn] = len(s)
            print(f"  {navn}: {len(s)} stationer")
        except Exception as e:
            status[navn] = 0
            print(f"  ! {navn}: {e}")
    nye = geokod(alle, cache)
    uden = sum(1 for s in alle if s["lat"] is None)
    print(f"  Placeret {nye} nye adresser. Uden placering: {uden}")
    return alle, status


def kædemedianer(stationer):
    import statistics
    ud = {}
    for s in stationer:
        for n in ("benzin", "diesel"):
            if s[n] is not None:
                ud.setdefault(s["kæde"], {}).setdefault(n, []).append(s[n])
    return [{"navn": k, "benzin": round(statistics.median(v["benzin"]), 2) if v.get("benzin") else None,
             "diesel": round(statistics.median(v["diesel"]), 2) if v.get("diesel") else None} for k, v in ud.items()]


def til_fil(stationer, status):
    felter = ["id", "kæde", "adresse", "postnr", "by", "lat", "lon", "benzin", "diesel", "opdateret"]
    return {"opdateret": datetime.now(timezone.utc).isoformat(timespec="minutes"), "kilder": status, "felter": felter,
            "stationer": [[s[f] for f in felter] for s in stationer if s["lat"] is not None]}
