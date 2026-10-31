"""Flashcards: begrep på forsiden, definisjon og kilde på baksiden. Du vurderer selv.

Vurderingen styrer når kortet kommer igjen (spaced repetition, se repetisjon.py):
  1 igjen     → senere i samme økt
  2 vanskelig → forrige intervall × 1,2 (minst 1 dag)
  3 greit     → forrige intervall × 2,5 (minst 3 dager)
  4 lett      → forrige intervall × 4   (minst 7 dager)
Jo bedre du kan kortet, jo lenger blir det mellom hver gang.

Kjør:  uv run python -m src.flashcards --fag MRK1001 --tema "merkevare" --nye 8
       uv run python -m src.flashcards --fag MRK1001           (bare kort som skal repeteres)
       uv run python -m src.flashcards --fag MRK1001 --status
"""

import argparse
from datetime import datetime

from src.database import koble, kort, lagre_sporsmal
from src.henting import Bit
from src.innlesing import standardfag
from src.kontroll import Duplikatfilter, normaliser, sitat_finnes
from src.llm import generer_json
from src.quiz import kandidat_biter, modellnavn
from src.repetisjon import lagre_resultat
from src.terminal import les

SYSTEM_KORT = """Du lager flashcards til en student som øver til eksamen. Du skal BARE bruke teksten du får.

Regler:
1. Lag 1–3 kort for de viktigste faglige begrepene eller modellene i teksten.
2. «begrep»: navnet på begrepet, kort (1–6 ord). Ikke et spørsmål.
3. «definisjon»: en presis forklaring på 1–2 setninger med egne ord, slik den står i teksten.
4. «sitat»: en hel setning eller en lang del av en setning, kopiert ORDRETT fra teksten, som viser definisjonen.
5. Hvis teksten bare er stikkord uten sammenheng, uleselig, eller ikke har noen faglige begreper,
   lag en tom liste.
Skriv på norsk."""

# Bevisst uten enum og min/maks-lengder: slike regler gjorde Ollama svært treg (se kortsvar.py).
SKJEMA_KORT = {
    "type": "object",
    "properties": {
        "kort": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"begrep": {"type": "string"}, "definisjon": {"type": "string"}, "sitat": {"type": "string"}},
                "required": ["begrep", "definisjon", "sitat"],
            },
        }
    },
    "required": ["kort"],
}

VURDERINGER = {"1": "igjen", "2": "vanskelig", "3": "greit", "4": "lett"}


def lag_kort(bit: Bit) -> tuple[list[dict], str]:
    """Returnerer (gyldige kort, grunn hvis ingen)."""
    try:
        data = generer_json(SYSTEM_KORT, f"Tekst:\n{bit.tekst}", SKJEMA_KORT)
    except (ValueError, TimeoutError):
        return [], "modellen ga ikke et gyldig svar"
    gyldige = [k for k in data["kort"][:3]
               if 0 < len(k["begrep"].split()) <= 6 and 20 <= len(k["definisjon"]) <= 400
               and sitat_finnes(k["sitat"], bit.tekst)]
    return gyldige, "" if gyldige else "ingen kort med sitat som står i kilden"


def lag_nye_kort(db, fag: str, tema: str, antall: int) -> int:
    """Lager opptil `antall` nye kort om temaet og lagrer dem. Hopper over begreper du allerede har."""
    eksisterende = kort(db, fag)
    kjente = {normaliser(k["sporsmal"]) for k in eksisterende}
    duplikater = Duplikatfilter([k["sporsmal"] + ": " + k["fasit"] for k in eksisterende])
    laget = 0
    print(f"Lager nye kort om «{tema}» ...")
    for bit in kandidat_biter(fag, tema, antall):
        if laget >= antall:
            break
        nye, grunn = lag_kort(bit)
        if not nye:
            print(f"  (hoppet over {bit.kilde}: {grunn})")
        for k in nye:
            if laget >= antall:
                break
            if normaliser(k["begrep"]) in kjente or duplikater.er_duplikat(k["begrep"] + ": " + k["definisjon"]):
                print(f"  (finnes fra før: {k['begrep']})")
                continue
            kjente.add(normaliser(k["begrep"]))
            lagre_sporsmal(db, fag=fag, tema=tema, ovingsmate="flashcard", sporsmal=k["begrep"],
                           fasit=k["definisjon"], sitat=k["sitat"], kilde=f"{fag}/{bit.kilde}", modell=modellnavn(),
                           kildetekst=bit.tekst)
            laget += 1
            print(f"  + {k['begrep']}")
    return laget


def forfalte(db, fag: str, tema: str | None) -> list:
    naa = datetime.now().isoformat(timespec="seconds")
    return [k for k in kort(db, fag, tema) if k["neste"] is None or k["neste"] <= naa]


def ov(db, kortstokk: list):
    """Vis kortene ett om gangen. Kort du svarer «igjen» på, kommer bakerst i køen."""
    ko = list(kortstokk)
    vist = 0
    while ko:
        k = ko.pop(0)
        vist += 1
        print(f"\n[{len(ko) + 1} igjen]  {k['sporsmal']}")
        if les("  (Enter for å snu, q for å avslutte) ").lower() == "q":
            return
        print(f"  {k['fasit']}")
        print(f"  Kilde: {k['kilde']}")
        valg = ""
        while valg not in VURDERINGER:
            valg = les("  Hvor godt kunne du det? 1 igjen · 2 vanskelig · 3 greit · 4 lett: ")
            if valg.lower() == "q":
                return
        navn = VURDERINGER[valg]
        neste = lagre_resultat(db, k["id"], svar=navn, riktig=valg in ("3", "4"), vurdering=navn)
        if navn == "igjen":
            ko.append(k)
        else:
            print(f"  Neste gang: {neste:%d.%m}")
    print(f"\nFerdig for nå ({vist} visninger). Lagret i data/studie.db.")


def vis_status(db, fag: str):
    alle = kort(db, fag)
    if not alle:
        print(f"Ingen flashcards i {fag} ennå. Lag noen med --tema.")
        return
    naa = datetime.now().isoformat(timespec="seconds")
    temaer = {}
    for k in alle:
        t = temaer.setdefault(k["tema"], [0, 0, 0])
        t[0] += 1
        t[1] += k["neste"] is None
        t[2] += k["neste"] is not None and k["neste"] <= naa
    print(f"{'Tema':<32} {'Kort':>5} {'Nye':>5} {'Skal repeteres':>15}")
    for tema, (antall, nye, forfalt) in temaer.items():
        print(f"{tema[:32]:<32} {antall:>5} {nye:>5} {forfalt:>15}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flashcards fra pensumet ditt.")
    parser.add_argument("--fag", help="fag (standard: standardfag i innstillingene)")
    parser.add_argument("--tema", help="tema for nye kort, og for hvilke kort som øves")
    parser.add_argument("--nye", type=int, default=0, help="lag så mange nye kort om temaet først")
    parser.add_argument("--status", action="store_true", help="vis antall kort per tema")
    args = parser.parse_args()
    fag = args.fag or standardfag()
    db = koble()

    if args.status:
        vis_status(db, fag)
    else:
        if args.nye:
            if not args.tema:
                parser.error("--nye krever --tema")
            lag_nye_kort(db, fag, args.tema, args.nye)
        kortstokk = forfalte(db, fag, args.tema)
        if not kortstokk:
            print("Ingen kort skal repeteres nå. Lag nye med --tema \"...\" --nye 8, eller se --status.")
        else:
            ov(db, kortstokk)
