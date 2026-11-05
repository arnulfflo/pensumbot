"""Finn modellene: tren på å se hvilke modeller en eksamenscase ber om.

Bygget på config/signaler_{fag}.yaml, som er hentet fra løsningsforslagene til ekte caser.
To øvingsmåter, begge uten språkmodell, så fasiten er alltid den løsningsforslaget gir:
  signal  ett signal fra en case eller oppgavetekst. Kryss av for modellene det peker på.
  finn    en hel eksamenscase med oppgavene. Kryss av for modellene du ville brukt.
          Rettingen viser signalet bak hver modell, og modeller løsningsforslaget sier ikke passer.

Kjør:  uv run python -m src.signaler MRK1001 --type finn -n 1     (viser spørsmål og fasit)
"""

import argparse
import math
import random
import re
from dataclasses import dataclass, field
from functools import cache

import docx
import yaml

from src.konfig import ROT, pensum_mappe
from src.modeller import Modell, kapittel_i, modeller

TYPER = {"signal": "Finn signalet", "finn": "Finn modellene i en eksamenscase"}
# Casene med løsningsforslag. Nøkkelen er navnet som står under «kilder» i signalfilen.
CASER = {"MRK1001": {"Apiir": "Apiir.docx", "Comfyballs": "Comfyballs.docx", "Grandiosa": "Grandiosa.docx",
                     "Kari Traa": "Karitraacase.docx", "Spike": "Spike.docx"}}
SPORSMAL_FINN = "Hvilke modeller fra pensum bør du bruke for å svare godt på oppgavene? Kryss av for modellene som passer."
SPORSMAL_SIGNAL = "Hvilke modeller peker dette på? Kryss av for modellene som passer."


@dataclass
class Signal:
    signal: str
    type: str
    modeller: list[str]
    begreper: list[str] = field(default_factory=list)
    kilder: list[str] = field(default_factory=list)
    hvorfor: str = ""
    utledet: bool = False

    @property
    def opphav(self) -> str:
        return "utledet fra notatene" if self.utledet else "løsningsforslag: " + ", ".join(self.kilder)


def _fil(fag: str):
    return ROT / "config" / f"signaler_{fag}.yaml"


def har_signaler(fag: str) -> bool:
    return _fil(fag).exists()


@cache
def signaler(fag: str) -> tuple[Signal, ...]:
    if not har_signaler(fag):
        return ()
    data = yaml.safe_load(_fil(fag).read_text(encoding="utf-8"))
    return tuple(Signal(**{k: s.get(k, v) for k, v in
                           dict(signal="", type="case", modeller=[], begreper=[], kilder=[], hvorfor="", utledet=False).items()})
                 for s in data["signaler"])


def _modell_etter_navn(fag: str) -> dict[str, Modell]:
    return {m.navn: m for m in modeller(fag)}


def er_modellvalg(q: dict) -> bool:
    """Spørsmål fra denne øvelsen, også når de kommer tilbake i repetisjonen."""
    return q.get("sporsmal", "").endswith((SPORSMAL_FINN, SPORSMAL_SIGNAL))


def krav(antall_riktige: int) -> int:
    """Hvor mange du må finne: halvparten, men aldri mer enn seks. En hel case kan ha 20 relevante modeller,
    og løsningsforslagene gir toppkarakter uten at hver eneste er med."""
    return min(math.ceil(antall_riktige / 2), 6)


def godkjent(antall_riktige: int, funnet: int, feil: int) -> bool:
    """Godkjent når du fant nok av modellene og ikke valgte noen som ikke passer."""
    return feil == 0 and funnet >= krav(antall_riktige)


def _gale_modeller(fag: str, riktige: list[str], rng: random.Random, antall: int, unngaa: set[str] = frozenset()) -> list[str]:
    """Modeller som ikke passer. Helst modeller som er brukt i andre signaler, så de ser fristende ut."""
    from src.modellquiz import _samme_tema
    alle = _modell_etter_navn(fag)
    rett = [alle[n] for n in riktige if n in alle]
    brukt = {n for s in signaler(fag) for n in s.modeller}
    kandidater = [m for m in alle.values() if m.navn not in riktige and m.navn not in unngaa and m.elementer
                  and not any(_samme_tema(r, m) for r in rett)]
    rng.shuffle(kandidater)
    kandidater.sort(key=lambda m: m.navn not in brukt)       # de fristende først
    return [m.navn for m in kandidater[:antall]]


# ---------- finn signalet ----------

def lag_signal(fag: str, s: Signal, rng: random.Random) -> dict | None:
    riktige = list(dict.fromkeys(s.modeller))
    if not riktige or s.type == "ikke":
        return None
    gale = _gale_modeller(fag, riktige, rng, antall=max(3, min(5, 8 - len(riktige))))
    alternativer = riktige + gale
    rng.shuffle(alternativer)
    hvor = "i oppgaveteksten" if s.type == "oppgaveord" else "i casen"
    forklaring = s.hvorfor
    if s.begreper:
        forklaring += "\nBegreper å bruke: " + ", ".join(s.begreper) + "."
    forklaring += f"\n({s.opphav})"
    return {"sporsmal": f"Du ser dette {hvor}:\n«{s.signal.strip('«»')}»\n\n{SPORSMAL_SIGNAL}",
            "alternativer": alternativer, "fasit": riktige, "forklaring": forklaring, "sitat": "",
            "type": "avkrysning", "stil": "finn signalet", "kilde": f"signalkatalogen ({s.opphav})"}


# ---------- finn modellene i en hel case ----------

def _tekst(el, i_boks: bool = False) -> str:
    """Teksten i et element. Hopper over reservekopien Word lagrer av tekstbokser (mc:Fallback),
    og over tekstbokser når i_boks er False (de tas med som egne linjer)."""
    deler = []
    def gaa(e, boks):
        tag = e.tag.rsplit("}", 1)[-1]
        if tag == "Fallback" or (tag == "txbxContent" and not boks):
            return
        if tag == "t":
            deler.append(e.text or "")
        for barn in e:
            gaa(barn, boks)
    gaa(el, i_boks)
    return "".join(deler).strip()


def _tekstbokser(el) -> list[str]:
    """Bildetekster og figurtitler i tekstbokser, én linje per avsnitt i boksen."""
    linjer = []
    def gaa(e):
        tag = e.tag.rsplit("}", 1)[-1]
        if tag == "Fallback":
            return
        if tag == "txbxContent":
            linjer.extend(f"[{x}]" for p in e if p.tag.endswith("}p") and (x := _tekst(p, True)))
            return
        for barn in e:
            gaa(barn)
    gaa(el)
    return linjer


def _tekst_fra_docx(sti) -> str:
    """Avsnitt og tabeller i rekkefølge. Avsnitt som står to ganger (Kari Traa) tas med én gang."""
    d = docx.Document(sti)
    linjer, sett = [], set()
    for barn in d.element.body.iterchildren():
        tag = barn.tag.rsplit("}", 1)[-1]
        if tag == "p":
            tekst = _tekst(barn)
            biter = _tekstbokser(barn) + ([tekst] if tekst else [])
        elif tag == "tbl":
            biter = []
            for rad in barn.iter():
                if rad.tag.endswith("}tr"):
                    celler = [_tekst(c) for c in rad if c.tag.endswith("}tc")]
                    if any(celler):
                        biter.append(" | ".join(celler))
        else:
            continue
        for b in biter:
            if re.search(r"\bNUMPAGES\b|\bPAGE \d+ av\b", b):       # feltkoder fra topp- og bunntekst
                continue
            if b not in sett:
                sett.add(b)
                linjer.append(b)
    return "\n\n".join(linjer)


def casetekst(fag: str, navn: str) -> str:
    return _tekst_fra_docx(pensum_mappe() / fag / "eksamener" / "oppgaver" / CASER[fag][navn])


def fasit_for_case(fag: str, navn: str) -> tuple[dict[str, list[Signal]], dict[str, Signal]]:
    """(modell → signalene som peker på den, modell som ikke passer → signalet som sier det)."""
    riktige: dict[str, list[Signal]] = {}
    for s in signaler(fag):
        if navn in s.kilder and s.type != "ikke":
            for m in s.modeller:
                riktige.setdefault(m, []).append(s)
    feller: dict[str, Signal] = {}
    for s in signaler(fag):
        if navn in s.kilder and s.type == "ikke":
            for m in s.modeller:
                if m not in riktige:
                    feller.setdefault(m, s)      # det første signalet er det mest konkrete
    return riktige, feller


def lag_finn(fag: str, navn: str, rng: random.Random) -> dict | None:
    riktige, feller = fasit_for_case(fag, navn)
    if not riktige:
        return None
    tekst = casetekst(fag, navn)
    fasit = list(riktige)
    antall_gale = max(4, min(10, math.ceil(len(fasit) / 2))) - len(feller)
    gale = list(feller) + _gale_modeller(fag, fasit, rng, antall=max(2, antall_gale), unngaa=set(feller))
    alternativer = fasit + gale
    rng.shuffle(alternativer)
    linjer = [f"Du må finne minst {krav(len(fasit))} av de {len(fasit)} modellene løsningsforslaget bruker, "
              "uten å velge noen som ikke passer. Signalene i casen og modellene de peker på:"]
    for s in signaler(fag):
        if navn in s.kilder and s.type != "ikke":
            linjer.append(f"• {s.signal} → " + ", ".join(s.modeller))
    for m, s in feller.items():
        linjer.append(f"✗ {m} passer ikke her: {s.hvorfor}")
    linjer.append("Husk: modellene skal brukes på bedriften i casen, og strategien skal ende i de 4 P-ene.")
    return {"sporsmal": f"📄 Eksamenscase: {navn}\n\n{tekst}\n\n{SPORSMAL_FINN}",
            "alternativer": alternativer, "fasit": fasit, "forklaring": "\n".join(linjer), "sitat": "",
            "type": "avkrysning", "stil": "finn modellene", "case": navn,
            "kilde": f"eksamener/oppgaver/{CASER[fag][navn]} (fasit fra løsningsforslaget)"}


# ---------- strømmen til quiz-fanen ----------

def _i_kapittel(fag: str, navn: list[str], kap: int | None) -> bool:
    alle = _modell_etter_navn(fag)
    return kap is None or any(alle[n].kapittel == kap for n in navn if n in alle)


def signal_strom(fag: str, tema: str | None, stil: str, antall: int = 15, rng: random.Random | None = None):
    """Gir (spørsmål, modell) ett om gangen. Modellen er den første riktige, så spørsmålet havner på et tema."""
    rng = rng or random.Random()
    kap = kapittel_i(tema or "")
    alle = _modell_etter_navn(fag)
    if stil == "finn":
        navn = [n for n in CASER.get(fag, {}) if _i_kapittel(fag, list(fasit_for_case(fag, n)[0]), kap)]
        rng.shuffle(navn)
        laget = ((lag_finn(fag, n, rng), n) for n in navn)
    else:
        utvalg = [s for s in signaler(fag) if s.type != "ikke" and _i_kapittel(fag, s.modeller, kap)]
        rng.shuffle(utvalg)
        laget = ((lag_signal(fag, s, rng), s.signal) for s in utvalg)
    gitt = 0
    for q, hva in laget:
        if gitt == antall:
            return
        if q is None:
            print(f"  (hoppet over {hva})")
            continue
        foerste = next((alle[n] for n in q["fasit"] if n in alle and (kap is None or alle[n].kapittel == kap)),
                       alle.get(q["fasit"][0]))
        gitt += 1
        yield q, foerste


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Øv på å finne modellene i en case (viser spørsmål og fasit)")
    ap.add_argument("fag", choices=list(CASER))
    ap.add_argument("--type", choices=list(TYPER), default="signal")
    ap.add_argument("--kap", type=int)
    ap.add_argument("-n", type=int, default=3)
    a = ap.parse_args()
    for q, m in signal_strom(a.fag, f"kap. {a.kap}" if a.kap else None, a.type, a.n):
        tekst = q["sporsmal"]
        print("\n" + (tekst if len(tekst) < 600 else tekst[:300] + " […] " + tekst[-200:]))
        for alt in q["alternativer"]:
            print(f"  ☐ {alt}{'   ✓' if alt in q['fasit'] else ''}")
        print(q["forklaring"])
