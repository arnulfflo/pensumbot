"""Hvilke modeller og tekstbiter quizen bør velge først.

To ting styrer rekkefølgen:
  1. Eksamensvekt: modeller som er fasit i mange tidligere eksamenscaser, eller som oppgaveord peker på,
     kommer oftere. Modeller som aldri har vært på eksamen, kommer sjelden (men ikke aldri).
  2. Det du nettopp har øvd på: det du svarte riktig på de siste dagene, skyves bak, så du ikke får
     de samme spørsmålene økt etter økt. Feilsvar tar repetisjonen seg av.
"""

import random
from collections import Counter
from datetime import datetime, timedelta
from functools import cache

from src import signaler

ALDRI_PAA_EKSAMEN = 0.25        # vekten til en modell som ikke er fasit i noen case
MESTRET_NYLIG = 0.1             # svart riktig de siste dagene: mye lavere sjanse
STILT_NYLIG = 0.4               # fått, men ikke svart riktig: litt lavere sjanse
DAGER_MESTRET = 14
DAGER_STILT = 3


@cache
def treff_paa_eksamen(fag: str) -> Counter:
    """Modell → hvor mange eksamenscaser den er fasit i, pluss et halvt poeng per oppgaveord som peker på den."""
    treff: Counter = Counter()
    for navn in signaler.caser(fag):
        riktige, _ = signaler.fasit_for_case(fag, navn)
        treff.update(riktige.keys())
    for s in signaler.signaler(fag):
        if s.type == "oppgaveord":
            for m in s.modeller:
                treff[m] += 0.5
    return treff


def modellvekt(fag: str, navn: str) -> float:
    treff = treff_paa_eksamen(fag).get(navn, 0)
    return 1.0 + treff if treff else ALDRI_PAA_EKSAMEN


def nylig_ovd(db, fag: str, naa: datetime | None = None) -> tuple[set[str], set[str]]:
    """(kildetekster svart riktig på de siste 14 dagene, kildetekster stilt de siste 3 dagene).

    Et riktig svar på et «kjenn modellen»-spørsmål (laget fra modellarket) teller bare som stilt: at du
    kjenner igjen elementene i Porter, betyr ikke at du kan bruke Porter på en case. Modellen skyves
    derfor litt bak, men kommer fortsatt som case."""
    naa = naa or datetime.now()
    grense_mestret = (naa - timedelta(days=DAGER_MESTRET)).isoformat(timespec="seconds")
    grense_stilt = (naa - timedelta(days=DAGER_STILT)).isoformat(timespec="seconds")
    riktige = db.execute(
        "SELECT DISTINCT s.kildetekst, s.modell = 'modellark' FROM forsok f JOIN sporsmal s ON s.id = f.sporsmal_id"
        " WHERE s.fag = ? AND f.riktig = 1 AND f.tidspunkt >= ? AND s.kildetekst IS NOT NULL",
        (fag, grense_mestret)).fetchall()
    mestret = {tekst for tekst, pugg in riktige if not pugg}
    stilt = {r[0] for r in db.execute(
        "SELECT DISTINCT kildetekst FROM sporsmal WHERE fag = ? AND laget >= ? AND kildetekst IS NOT NULL",
        (fag, grense_stilt))}
    return mestret, stilt | {tekst for tekst, pugg in riktige if pugg}


def nylige_sporsmal(db, fag: str, dager: int = DAGER_MESTRET, naa: datetime | None = None) -> list[str]:
    """Spørsmålstekstene du har fått de siste dagene, så nye spørsmål kan sammenlignes med dem."""
    grense = ((naa or datetime.now()) - timedelta(days=dager)).isoformat(timespec="seconds")
    return [r[0] + " " + r[1] for r in db.execute(
        "SELECT sporsmal, fasit FROM sporsmal WHERE fag = ? AND laget >= ? ORDER BY laget DESC LIMIT 120",
        (fag, grense))]


def demping(tekst: str, mestret: set[str], stilt: set[str]) -> float:
    if tekst in mestret:
        return MESTRET_NYLIG
    if tekst in stilt:
        return STILT_NYLIG
    return 1.0


def vektet_rekkefolge(ting: list, vekt, rng: random.Random) -> list:
    """Trekker uten tilbakelegging, med sannsynlighet etter vekt (Efraimidis og Spirakis).
    Alt kommer med, men tunge ting havner oftest først."""
    return sorted(ting, key=lambda t: rng.random() ** (1.0 / max(vekt(t), 1e-6)), reverse=True)
