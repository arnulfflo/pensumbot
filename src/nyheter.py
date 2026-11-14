"""Nyhetsverktøyet: henter ferske saker som kan brukes som eksamenscase (se eksamensmodus.py).

Eksamenscasene i MRK og ORG handler om ekte bedrifter og det som skjer rundt dem (Kari Traa, Grandiosa,
Easee, Norsk Tipping). Her hentes overskriftene fra nyhetskildene i config/innstillinger.yaml (RSS), og
sakene sorteres etter hvor godt de passer faget: en lansering eller priskrig for MRK, en omstilling eller
lederkonflikt for ORG. Artikkelteksten hentes først når du velger en sak.

Dette er det eneste i boten som går ut på nettet. Det sendes ingenting om deg eller pensumet ditt:
bare en vanlig forespørsel etter RSS-filen og artikkelen. Alt lagres i data/nyheter/, så en sak du
har hentet, kan brukes uten nett. Teksten fra nettet er data: den vises og rettes mot, aldri kjørt.

Kjør:  uv run python -m src.nyheter MRK1001           (de mest relevante sakene nå)
       uv run python -m src.nyheter ORG1100 --ferske  (hent på nytt, ikke bruk mellomlageret)
"""

import argparse
import hashlib
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from src.konfig import data_mappe, last_innstillinger

STANDARDKILDER = [{"navn": "E24", "url": "https://e24.no/rss2/"},
                  {"navn": "Kampanje", "url": "https://kampanje.com/rss/"},
                  {"navn": "Finansavisen", "url": "https://ws.finansavisen.no/api/articles.rss"},
                  {"navn": "NRK", "url": "https://www.nrk.no/toppsaker.rss"}]
# Dagens Næringsliv (https://services.dn.no/api/feed/rss/) er med vilje ikke med: alle sakene ligger bak
# betalingsmur (testet 14.11.2026, 0 av 25 ga tekst), så de ville bare fylt menyen med saker som ikke kan brukes.
FERSK_I_TIMER = 6            # så lenge brukes de lagrede overskriftene før de hentes på nytt
MAKS_BYTE = 3_000_000        # en nyhetsside er aldri større enn dette
MAKS_ORD = 750               # casen kuttes ved avsnittet der den passerer dette (eksamenscasene er 800–1700 ord)
MIN_ORD = 180                # kortere saker (notiser, saker bak betalingsmur) gir for lite å analysere
TIDSGRENSE = 15

# Ord som tyder på at saken kan analyseres med pensum. Stammer, så «lanserer» og «lanseringen» treffer begge.
FAGORD = {
    "MRK1001": ["lanser", "merkevare", "merket", "kunde", "markedsandel", "pris", "kjede", "butikk", "salg", "kampanje",
                "reklame", "konkurrent", "konkurranse", "vekst", "forbruker", "netthandel", "produkt", "omsetning",
                "posisjon", "marked", "segment", "målgruppe", "sortiment", "lojalitet", "annonse", "satser", "nedgang"],
    "ORG1100": ["ledelse", "leder", "sjef", "ansatte", "omstilling", "nedbemann", "oppsig", "kultur", "konflikt",
                "arbeidsmiljø", "streik", "fusjon", "omorganiser", "tillitsvalgt", "varsl", "bonus", "motivasjon",
                "sykefravær", "styret", "beslutning", "granskning", "permitter", "fagforening", "direktør", "hjemmekontor"],
}
# Saker som sjelden handler om en virksomhet man kan analysere
STOY = re.compile(r"\b(fotball|kamp(en)?|mål(et)?s?scorer|landslag|vm|ol|serie(n)?|drept|politiet|siktet|dømt|ulykke|krig|"
                  r"vær(et)?|kongehus|kjendis|quiz|kryssord|leilighet\w*|bolig\w*|villa(en)?|hytte\w*|aksje\w*|børs\w*)\b", re.I)


@dataclass
class Nyhet:
    tittel: str
    ingress: str
    lenke: str
    kilde: str
    dato: str               # ISO-format, tom hvis kilden ikke oppgir det

    @property
    def etikett(self) -> str:
        """«Rema kutter prisene (E24, 14.11)»: slik saken vises i menyen."""
        dag = f", {self.dato[8:10]}.{self.dato[5:7]}" if self.dato else ""
        return f"{self.tittel} ({self.kilde}{dag})"


def kilder() -> list[dict]:
    return (last_innstillinger().get("nyheter") or {}).get("kilder") or STANDARDKILDER


def _mappe():
    mappe = data_mappe() / "nyheter"
    mappe.mkdir(parents=True, exist_ok=True)
    return mappe


def _tillatt(lenke: str) -> bool:
    """Bare https-lenker til de samme nettstedene som kildene. En RSS-fil skal ikke kunne sende boten andre steder."""
    del_ = urlparse(lenke)
    domene = lambda vert: ".".join(vert.lower().split(".")[-2:])
    return del_.scheme == "https" and domene(del_.hostname or "") in {domene(urlparse(k["url"]).hostname or "") for k in kilder()}


def _last_ned(lenke: str) -> bytes:
    foresporsel = urllib.request.Request(lenke, headers={"User-Agent": "pensumbot/0.1"})
    with urllib.request.urlopen(foresporsel, timeout=TIDSGRENSE) as svar:
        return svar.read(MAKS_BYTE)


def _ren(tekst: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(tekst or "")).split())


def les_rss(xml: bytes, kilde: str) -> list[Nyhet]:
    """Sakene i én RSS-fil. Saker uten tittel eller lenke hoppes over."""
    ut = []
    for sak in ET.fromstring(xml).iter("item"):
        tittel, lenke = _ren(sak.findtext("title")), (sak.findtext("link") or "").strip()
        if not tittel or not lenke:
            continue
        try:
            dato = parsedate_to_datetime(sak.findtext("pubDate") or "").astimezone().replace(tzinfo=None).isoformat(timespec="minutes")
        except (TypeError, ValueError):
            dato = ""
        ut.append(Nyhet(tittel, _ren(sak.findtext("description")), lenke, kilde, dato))
    return ut


def hent_nyheter(ferske: bool = False) -> list[Nyhet]:
    """Overskriftene fra alle kildene. Lagres i data/nyheter/overskrifter.json og brukes derfra i seks timer.
    Uten nett brukes det som er lagret, uansett alder. Finnes ikke det heller, blir listen tom."""
    fil = _mappe() / "overskrifter.json"
    lagret = json.loads(fil.read_text(encoding="utf-8")) if fil.exists() else None
    if lagret and not ferske and datetime.fromisoformat(lagret["hentet"]) > datetime.now() - timedelta(hours=FERSK_I_TIMER):
        return [Nyhet(**n) for n in lagret["saker"]]
    saker = []
    for k in kilder():
        try:
            saker += les_rss(_last_ned(k["url"]), k["navn"])
        except (OSError, ET.ParseError, ValueError) as feil:      # ikke nett, eller kilden er nede
            print(f"  (fikk ikke hentet nyheter fra {k['navn']}: {type(feil).__name__})")
    if not saker:
        return [Nyhet(**n) for n in lagret["saker"]] if lagret else []
    fil.write_text(json.dumps({"hentet": datetime.now().isoformat(timespec="seconds"),
                               "saker": [asdict(n) for n in saker]}, ensure_ascii=False), encoding="utf-8")
    return saker


def relevans(n: Nyhet, fag: str) -> int:
    """Hvor mange fagord tittel og ingress treffer. Sport, krim og vær gir 0."""
    tekst = f"{n.tittel} {n.ingress}".lower()
    if STOY.search(tekst):
        return 0
    return sum(o in tekst for o in FAGORD.get(fag, []))


def for_fag(fag: str, antall: int = 20, ferske: bool = False) -> list[Nyhet]:
    """De sakene som passer faget best, nyeste først ved likt antall treff. Saker uten treff er ikke med."""
    saker = [n for n in hent_nyheter(ferske) if relevans(n, fag) > 0]
    saker.sort(key=lambda n: n.dato, reverse=True)
    saker.sort(key=lambda n: relevans(n, fag), reverse=True)        # stabil sortering: dato avgjør ved likhet
    return saker[:antall]


class _Avsnitt(HTMLParser):
    """Plukker ut teksten i <p>-avsnittene, uten menyer, bildetekster, skjemaer og skript."""
    UTENFOR = {"script", "style", "figure", "figcaption", "nav", "footer", "aside", "button", "form", "header"}

    TOMME = {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}      # har ingen slutt-tagg

    def __init__(self):
        super().__init__()
        self.utenfor, self.i_avsnitt, self.deler, self.avsnitt = 0, False, [], []
        self.lenker = 0              # <a> åpnet utenfor et avsnitt: «les også»-bokser, ikke brødtekst
        self.skjult = None           # [tagg, dybde] mens vi er inne i noe med aria-hidden (ordforklaringer)

    def handle_starttag(self, tag, attrs):
        if self.skjult:
            self.skjult[1] += tag == self.skjult[0]
        elif dict(attrs).get("aria-hidden") == "true" and tag not in self.TOMME:
            self.skjult = [tag, 1]
        elif tag in self.UTENFOR:
            self.utenfor += 1
        elif tag == "a" and not self.i_avsnitt:
            self.lenker += 1
        elif tag == "p" and not self.utenfor and not self.lenker:
            self.i_avsnitt, self.deler = True, []

    def handle_endtag(self, tag):
        if self.skjult:
            if tag == self.skjult[0]:
                self.skjult[1] -= 1
                if not self.skjult[1]:
                    self.skjult = None
        elif tag in self.UTENFOR and self.utenfor:
            self.utenfor -= 1
        elif tag == "a" and not self.i_avsnitt and self.lenker:
            self.lenker -= 1
        elif tag == "p" and self.i_avsnitt:
            self.i_avsnitt = False
            tekst = " ".join("".join(self.deler).split())
            henvisning = tekst.lower().startswith(("les også", "les mer", "les hele saken"))
            if len(tekst) > 60 and tekst not in self.avsnitt and not henvisning:   # korte linjer er knapper og bylines
                self.avsnitt.append(tekst)

    def handle_data(self, data):
        if self.i_avsnitt and not self.utenfor and not self.skjult:
            self.deler.append(data)


def avsnitt_i(side: str) -> list[str]:
    leser = _Avsnitt()
    leser.feed(side)
    return leser.avsnitt


def kutt(avsnitt: list[str], maks_ord: int = MAKS_ORD) -> str:
    """Hele avsnitt til teksten passerer maks_ord, så casen aldri slutter midt i en setning."""
    ut, ord_ = [], 0
    for a in avsnitt:
        ut.append(a)
        ord_ += len(a.split())
        if ord_ >= maks_ord:
            break
    return "\n\n".join(ut)


def artikkel(n: Nyhet) -> str:
    """Teksten i saken (lagret etter første gang). Tom streng hvis den ikke kan hentes eller er for kort."""
    if not _tillatt(n.lenke):
        return ""
    fil = _mappe() / (hashlib.sha1(n.lenke.encode()).hexdigest()[:16] + ".txt")
    if fil.exists():
        return fil.read_text(encoding="utf-8")
    try:
        tekst = kutt(avsnitt_i(_last_ned(n.lenke).decode("utf-8", "replace")))
    except OSError:
        return ""
    if len(tekst.split()) < MIN_ORD:
        return ""
    fil.write_text(tekst, encoding="utf-8")
    return tekst


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ferske nyhetssaker som kan brukes som eksamenscase")
    ap.add_argument("fag", choices=list(FAGORD))
    ap.add_argument("--ferske", action="store_true", help="hent på nytt i stedet for å bruke de lagrede overskriftene")
    a = ap.parse_args()
    for nr, n in enumerate(for_fag(a.fag, 15, a.ferske), start=1):
        print(f"{nr:>2}. [{relevans(n, a.fag)}] {n.etikett}\n      {n.ingress[:110]}\n      {n.lenke}")
