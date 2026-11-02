"""Steg 5: hent biter, bygg prompten, la språkmodellen svare, og legg på kilder.

Dette er hele RAG-løkka:  spørsmål → hent() → prompt → generer() → svar + kilder

Kjør:  uv run python -m src.svar "Hva er kontrollspenn?"
       uv run python -m src.svar --fag MRK1001 "Hva er segmentering?"
"""

import argparse
import re
from dataclasses import dataclass

from src.henting import Bit, hent
from src.innlesing import standardfag
from src.konfig import last_innstillinger
from src.llm import generer

FINNES_IKKE = "Finnes ikke i materialet."

SYSTEM = f"""Du er en studieassistent. Du svarer på norsk, og BARE ut fra tekstbitene du får.

Regler:
1. Bruk bare informasjon som står i tekstbitene. Ikke bruk egen kunnskap, selv om du kjenner temaet.
2. Vis til bitene du bygger på med nummeret i hakeparentes rett etter påstanden, for eksempel [1] eller [2][4].
3. Hvis tekstbitene ikke inneholder svaret, svar nøyaktig «{FINNES_IKKE}» og ingenting annet.
4. Ikke skriv sidetall eller boksider selv. Kildene legges til automatisk ut fra numrene.
5. Svar kort og presist, med egne ord."""


SYSTEM_OMSKRIV = """Du får en samtale mellom en student og en studieassistent, og et nytt spørsmål fra studenten.
Skriv om det nye spørsmålet slik at det kan forstås uten samtalen: bytt ut ord som «det», «den», «dette»,
«de» og «hva med ...» med det de viser til i samtalen.
Behold ønsker om form, som «enklere», «med et eksempel» eller «i punkter».
Er spørsmålet allerede forståelig alene, skriv det uendret.
Svar bare med det omskrevne spørsmålet på norsk, uten forklaring og uten anførselstegn."""


def selvstendig_sporsmal(sporsmal: str, historikk: list[tuple[str, str]]) -> str:
    """Gjør et oppfølgingsspørsmål («forklar enklere», «hva med pull?») om til et spørsmål som kan
    brukes til å søke i pensum. historikk: [(spørsmål, svartekst), ...], eldste først."""
    if not historikk:
        return sporsmal
    linjer = []
    for tidligere, svar in historikk[-3:]:
        svar = re.sub(r"\[\d+\]", "", svar)[:500]      # numrene [1] betyr ingenting her
        linjer.append(f"Student: {tidligere}\nAssistent: {svar}")
    try:
        ny = generer(SYSTEM_OMSKRIV, "Samtale:\n" + "\n\n".join(linjer) + f"\n\nNytt spørsmål: {sporsmal}")
    except TimeoutError:
        return sporsmal
    ny = ny.strip().strip('"«»').splitlines()[0].strip() if ny.strip() else ""
    return ny or sporsmal


@dataclass
class Svar:
    sporsmal: str
    tekst: str
    finnes_ikke: bool
    biter: list[Bit]          # alle bitene modellen fikk
    siterte: list[Bit]        # bitene modellen viste til med [n]


def bygg_melding(sporsmal: str, biter: list[Bit]) -> str:
    deler = ["Tekstbiter:\n"]
    for nr, bit in enumerate(biter, start=1):
        deler.append(f"[{nr}] (fra {bit.metadata['fil']})\n{bit.tekst}\n")
    deler.append(f"Spørsmål: {sporsmal}")
    return "\n".join(deler)


def svar_pa(sporsmal: str, fag: str | None = None, k: int | None = None,
            bruk_reranker: bool = True, biter: list[Bit] | None = None,
            med_eksempelsvar: bool = False) -> Svar:
    """biter: allerede hentede biter (testscriptet bruker det for å slippe å hente to ganger)."""
    if biter is None:
        biter = hent(sporsmal, fag=fag, k=k, bruk_reranker=bruk_reranker, med_eksempelsvar=med_eksempelsvar)
    tekst = generer(SYSTEM, bygg_melding(sporsmal, biter)).strip()

    finnes_ikke = "finnes ikke i materialet" in tekst.lower()
    # Finn alle [n] i svaret og slå opp hvilke biter de peker på. Ugyldige numre ignoreres.
    numre = sorted({int(n) for n in re.findall(r"\[(\d+)\]", tekst)})
    siterte = [biter[n - 1] for n in numre if 1 <= n <= len(biter)]
    return Svar(sporsmal, tekst, finnes_ikke, biter, siterte)


def kildeliste(biter: list[Bit]) -> list[str]:
    """Unike kilder i rekkefølge, i formatet ORG1100/foiler/F05.pdf, s. 12."""
    sett = []
    for bit in biter:
        kilde = f"{bit.metadata['fag']}/{bit.kilde}"
        if kilde not in sett:
            sett.append(kilde)
    return sett


def vis(svar: Svar) -> str:
    linjer = [f"## {svar.sporsmal}", "", svar.tekst, ""]
    if svar.finnes_ikke:
        linjer.append("Nærmeste treff i materialet:")
        linjer += [f"  - {k}" for k in kildeliste(svar.biter[:3])]
    elif svar.siterte:
        linjer.append("Kilder:")
        for nr, bit in enumerate(svar.biter, start=1):
            if bit in svar.siterte:
                linjer.append(f"  [{nr}] {bit.metadata['fag']}/{bit.kilde}")
    else:
        linjer.append("Modellen viste ikke til noen bit. Hentede kilder:")
        linjer += [f"  - {k}" for k in kildeliste(svar.biter)]
    return "\n".join(linjer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Still et spørsmål til pensumboten.")
    parser.add_argument("--fag", help="fag å søke i (standard: standardfag i innstillingene)")
    parser.add_argument("--eksempelsvar", action="store_true", help="ta med A-besvarelser som kilde")
    parser.add_argument("sporsmal", nargs="+")
    args = parser.parse_args()
    innst = last_innstillinger()["sprakmodell"]
    print(f"(fag: {args.fag or standardfag()}, modell: {innst[innst['leverandor']]['modell']})\n")
    print(vis(svar_pa(" ".join(args.sporsmal), fag=args.fag, med_eksempelsvar=args.eksempelsvar)))
