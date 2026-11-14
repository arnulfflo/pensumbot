"""Dekningsoversikt: hvilke eksamensmodeller har du øvd på, og på hvilken måte?

Mestringen per tema sier hvor godt det går i et kapittel. Den sier ikke om du har brukt Porter på en
case, eller bare kjent igjen elementene. Her telles hver modell som har vært fasit på en tidligere eksamen
(eller som et oppgaveord peker på, se eksamensvekt.py) på tre måter:

  kjenn   «kjenn modellen»: hvilken modell, hvilket element, hva betyr elementet
  case    «velg modell til casen» og «bruk modellen på casen»
  funnet  du fant modellen i en hel case: «finn modellene», «ny case», «finn signalet» og eksamensmodus

Kjør:  uv run python -m src.dekning MRK1001
"""

import argparse
import json
from dataclasses import dataclass, field

from src import eksamensvekt, modellquiz, signaler
from src.modeller import Modell, modeller
from src.repetisjon import MODELLARK

EKSAMEN = "eksamen"         # ovingsmate for en hel besvarelse i eksamensmodus (se eksamensmodus.py)


@dataclass
class Tall:
    riktige: int = 0
    forsok: int = 0

    def tell(self, riktig: bool):
        self.forsok += 1
        self.riktige += bool(riktig)


@dataclass
class Rad:
    modell: Modell
    treff: float                     # antall eksamenscaser modellen er fasit i (+ 0,5 per oppgaveord)
    kjenn: Tall = field(default_factory=Tall)
    case: Tall = field(default_factory=Tall)
    funnet: Tall = field(default_factory=Tall)

    @property
    def brukt_paa_case(self) -> bool:
        """Har du minst én gang brukt eller funnet modellen riktig i en case?"""
        return self.case.riktige + self.funnet.riktige > 0


def _liste(tekst: str | None) -> list:
    try:
        verdi = json.loads(tekst or "")
    except ValueError:
        return []
    return verdi if isinstance(verdi, list) else []


def dekning(db, fag: str) -> list[Rad]:
    """Én rad per eksamensmodell, tyngst først. Fag uten signalkatalog gir en tom liste."""
    if not signaler.har_signaler(fag):
        return []
    treff = eksamensvekt.treff_paa_eksamen(fag)
    rader = {m.navn: Rad(m, treff[m.navn]) for m in modeller(fag) if treff.get(m.navn)}
    etter_tekst = {r.modell.tekst: r for r in rader.values()}
    for f in db.execute("SELECT s.sporsmal, s.ovingsmate, s.fasit, s.modell, s.kildetekst, f.riktig, f.svar,"
                        " f.tilbakemelding FROM forsok f JOIN sporsmal s ON s.id = f.sporsmal_id WHERE s.fag = ?", (fag,)):
        if f["ovingsmate"] == EKSAMEN:
            resultat = json.loads(f["tilbakemelding"] or "{}")
            for navn, brukt in [(n, True) for n in resultat.get("brukt", [])] + [(n, False) for n in resultat.get("mangler", [])]:
                if navn in rader:
                    rader[navn].funnet.tell(brukt)
        elif f["ovingsmate"] == "avkrysning" and signaler.er_modellvalg({"sporsmal": f["sporsmal"]}):
            valgt = _liste(f["svar"])
            for navn in _liste(f["fasit"]):
                if navn in rader:
                    rader[navn].funnet.tell(navn in valgt)
        elif rad := etter_tekst.get(f["kildetekst"]):
            if f["modell"] == MODELLARK:
                rad.kjenn.tell(f["riktig"])
            elif "Hvilken modell eller teori passer best" in f["sporsmal"] or modellquiz.er_case_oppgave({"sporsmal": f["sporsmal"]}):
                rad.case.tell(f["riktig"])
    return sorted(rader.values(), key=lambda r: (-r.treff, r.modell.kapittel))


def oppsummering(rader: list[Rad]) -> tuple[int, int]:
    """(antall eksamensmodeller du har brukt riktig på en case, antall eksamensmodeller)."""
    return sum(r.brukt_paa_case for r in rader), len(rader)


if __name__ == "__main__":
    from src.database import koble

    ap = argparse.ArgumentParser(description="Hvilke eksamensmodeller har du øvd på?")
    ap.add_argument("fag", choices=["MRK1001", "ORG1100"])
    a = ap.parse_args()
    rader = dekning(koble(), a.fag)
    brukt, alle = oppsummering(rader)
    print(f"{brukt} av {alle} eksamensmodeller brukt riktig på en case.\n")
    print(f"{'Modell':<52} {'Kap':>3} {'Eks.':>5} {'Kjenn':>7} {'Case':>7} {'Funnet':>7}")
    vis = lambda t: f"{t.riktige}/{t.forsok}" if t.forsok else "–"
    for r in rader:
        print(f"{r.modell.navn[:52]:<52} {r.modell.kapittel:>3} {r.treff:>5.1f} {vis(r.kjenn):>7} {vis(r.case):>7} {vis(r.funnet):>7}")
