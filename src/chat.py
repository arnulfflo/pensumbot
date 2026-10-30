"""Samtalevindu: still spørsmål etter hverandre uten å laste modellene på nytt.

Kjør:  uv run python -m src.chat
       uv run python -m src.chat --fag MRK1001

Kommandoer underveis:
  /fag MRK1001   bytt fag
  /kilde 2       vis hele teksten i bit nr. 2 fra forrige svar
  /hjelp         vis kommandoene
  /avslutt       avslutt (eller Ctrl+D)
"""

import argparse
import readline  # noqa: F401  (gir piltaster og historikk i input())
import time

from src.henting import hent
from src.innlesing import alle_fag, standardfag
from src.konfig import last_innstillinger
from src.llm import generer
from src.svar import svar_pa, vis

HJELP = """Kommandoer:
  /fag <fag>     bytt fag, f.eks. /fag MRK1001  (fag: {fag})
  /kilde <nr>    vis hele teksten i en bit fra forrige svar, f.eks. /kilde 2
  /hjelp         vis denne teksten
  /avslutt       avslutt (eller Ctrl+D)
Alt annet du skriver, blir sendt som et spørsmål."""


def varm_opp(fag: str):
    """Last embedding-modell, reranker og språkmodell nå, så første spørsmål går like fort som resten."""
    print("Laster modellene ...", end=" ", flush=True)
    start = time.time()
    hent("oppvarming", fag=fag)
    generer("Svar med ett ord.", "Hei")
    print(f"klar ({time.time() - start:.0f} s).\n")


def vis_kilde(svar, argument: str):
    if svar is None:
        print("Still et spørsmål først.\n")
        return
    if not argument.isdigit() or not 1 <= int(argument) <= len(svar.biter):
        print(f"Skriv et tall fra 1 til {len(svar.biter)}, f.eks. /kilde 1\n")
        return
    bit = svar.biter[int(argument) - 1]
    print(f"\n[{argument}] {bit.metadata['fag']}/{bit.kilde}\n")
    print(bit.tekst + "\n")


def main(fag: str):
    innst = last_innstillinger()["sprakmodell"]
    print(f"Pensumboten · fag {fag} · modell {innst[innst['leverandor']]['modell']}")
    print("Skriv /hjelp for kommandoer.\n")
    varm_opp(fag)

    forrige = None
    while True:
        try:
            linje = input(f"{fag} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not linje:
            continue

        if linje.startswith("/"):
            kommando, _, argument = linje.partition(" ")
            argument = argument.strip()
            if kommando in ("/avslutt", "/q"):
                break
            elif kommando == "/hjelp":
                print(HJELP.format(fag=", ".join(alle_fag())) + "\n")
            elif kommando == "/fag":
                if argument.upper() in alle_fag():
                    fag = argument.upper()
                    print(f"Bytter til {fag}.\n")
                else:
                    print(f"Ukjent fag. Velg mellom: {', '.join(alle_fag())}\n")
            elif kommando == "/kilde":
                vis_kilde(forrige, argument)
            else:
                print("Ukjent kommando. Skriv /hjelp.\n")
            continue

        start = time.time()
        try:
            forrige = svar_pa(linje, fag=fag)
        except TimeoutError:
            print("Språkmodellen brukte for lang tid. Prøv igjen, gjerne med et kortere spørsmål.\n")
            continue
        print("\n" + vis(forrige))
        print(f"({time.time() - start:.1f} s)  Skriv /kilde <nr> for å lese en kilde.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Still spørsmål til pensumboten i et samtalevindu.")
    parser.add_argument("--fag", help="fag å starte i (standard: standardfag i innstillingene)")
    main(parser.parse_args().fag or standardfag())
