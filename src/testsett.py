"""Kjør testsettet og mål om hentingen finner riktig kilde. Trenger ingen språkmodell.

Et spørsmål er bestått hvis minst én av de hentede bitene kommer fra en av
de forventede kildene. «fil» uten sidetall godtar alle biter fra filen.

Kjør:  uv run python -m src.testsett
       uv run python -m src.testsett --k 8      (prøv et annet antall biter)
       uv run python -m src.testsett --med-svar (la også språkmodellen svare)
"""

import argparse
import math
import re
import statistics

import yaml

from src.henting import hent
from src.innlesing import nfc
from src.konfig import ROT, last_innstillinger
from src.svar import svar_pa


def tolk_kilde(tekst: str) -> tuple[str, int | None]:
    """«foiler/X.pdf, s. 15» → ("foiler/X.pdf", 15).  «notater/Y.docx» → ("notater/Y.docx", None)."""
    treff = re.fullmatch(r"(.+?)(?:,\s*s\.\s*(\d+))?", nfc(tekst.strip()))
    fil, side = treff.groups()
    return fil, int(side) if side else None


def forventede_kilder(sporsmal: dict) -> list[tuple[str, int | None]]:
    kilder = sporsmal.get("forventet_kilde")
    if not kilder or kilder == "ingen":
        return []
    if isinstance(kilder, str):
        kilder = [kilder]
    return [tolk_kilde(k) for k in kilder]


def er_treff(bit, kilder) -> bool:
    return any(bit.metadata["fil"] == fil and (side is None or bit.metadata.get("side") == side)
               for fil, side in kilder)


def kjor(k: int | None, med_svar: bool = False):
    innst = last_innstillinger()
    with open(ROT / innst["testing"]["testsett"], encoding="utf-8") as f:
        testsett = yaml.safe_load(f)

    vanlige = [s for s in testsett["sporsmal"] if not s.get("felle")]
    feller = [s for s in testsett["sporsmal"] if s.get("felle")]
    k = k or innst["henting"]["antall_biter"]
    print(f"Testsett: {innst['testing']['testsett']}  |  fag {testsett['fag']}  |  henter {k} biter\n")

    riktige, beste_avstand_vanlige = 0, []
    sitert_riktig, sa_finnes_ikke = 0, []
    for s in vanlige:
        kilder = forventede_kilder(s)
        if med_svar:
            svar = svar_pa(s["sporsmal"], fag=testsett["fag"], k=k)
            biter = svar.biter
        else:
            biter = hent(s["sporsmal"], fag=testsett["fag"], k=k)
        rang = next((nr for nr, b in enumerate(biter, start=1) if er_treff(b, kilder)), None)
        riktige += rang is not None
        beste_avstand_vanlige.append(biter[0].avstand)

        merke = f"✓ rang {rang}" if rang else "✗"
        print(f"{s['id']:>2}. {merke:<9} {s['sporsmal']}")
        for nr, b in enumerate(biter[:3], start=1):
            stjerne = "*" if er_treff(b, kilder) else " "
            print(f"      {stjerne} {nr}. {b.avstand:.3f}  {b.kilde}")
        if not rang:
            print("      forventet: " + "; ".join(f"{f}, s. {p}" if p else f for f, p in kilder))
        if med_svar:
            sitert = any(er_treff(b, kilder) for b in svar.siterte)
            sitert_riktig += sitert
            if svar.finnes_ikke:
                sa_finnes_ikke.append(s["id"])
            print(f"      SVAR ({'siterer riktig kilde' if sitert else 'siterer IKKE riktig kilde'}):")
            print(_innrykk(svar.tekst))
            print("      FORVENTET:")
            print(_innrykk(s["forventet_svar"]) + "\n")

    beste_avstand_feller, feller_ok = [], 0
    if feller:
        print("\nFelle-spørsmål (skal ikke finnes; nærmeste bit vises bare som pekepinn):")
    for s in feller:
        if med_svar:
            svar = svar_pa(s["sporsmal"], fag=testsett["fag"], k=k)
            beste = svar.biter[0]
            feller_ok += svar.finnes_ikke
        else:
            beste = hent(s["sporsmal"], fag=testsett["fag"], k=1)[0]
        beste_avstand_feller.append(beste.avstand)
        print(f"{s['id']:>2}. {beste.avstand:.3f}  {beste.kilde:<55}  {s['sporsmal']}")
        if med_svar:
            print(f"      {'✓' if svar.finnes_ikke else '✗'} SVAR: " + svar.tekst.replace("\n", " ")[:300])

    mal = math.ceil(innst["testing"]["mal_andel"] * len(vanlige))
    print("\n" + "=" * 60)
    print(f"Riktig kilde: {riktige} av {len(vanlige)}  (mål: {mal})  "
          + ("BESTÅTT" if riktige >= mal else "IKKE BESTÅTT"))
    print(f"Beste avstand, vanlige spørsmål: median {statistics.median(beste_avstand_vanlige):.3f}, "
          f"høyest {max(beste_avstand_vanlige):.3f}")
    if beste_avstand_feller:
        print(f"Beste avstand, felle-spørsmål:   median {statistics.median(beste_avstand_feller):.3f}, "
              f"lavest {min(beste_avstand_feller):.3f}")
        print("(En avstandsterskel for «finnes ikke» virker bare hvis fellene ligger tydelig høyere enn de vanlige.)")
    if med_svar:
        print(f"\nSvar som siterer riktig kilde: {sitert_riktig} av {len(vanlige)}")
        print(f"Vanlige spørsmål besvart med «finnes ikke»: {len(sa_finnes_ikke)}"
              + (f" (nr. {', '.join(map(str, sa_finnes_ikke))})" if sa_finnes_ikke else ""))
        print(f"Felle-spørsmål besvart med «finnes ikke»: {feller_ok} av {len(feller)}")
        print("Om innholdet i svarene er riktig, må du vurdere selv ut fra FORVENTET.")


def _innrykk(tekst: str) -> str:
    return "\n".join("        " + linje for linje in tekst.splitlines())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mål hentingen (og eventuelt svarene) mot testsettet.")
    parser.add_argument("--k", type=int, help="antall biter å hente (overstyrer innstillingene)")
    parser.add_argument("--med-svar", action="store_true", help="la språkmodellen svare (tar noen minutter)")
    args = parser.parse_args()
    kjor(args.k, args.med_svar)
