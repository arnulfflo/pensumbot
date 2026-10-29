"""Fase 2: flervalgsquiz laget fra ditt eget materiale.

Flyt per spørsmål:
  tema → hent biter → velg én bit → språkmodellen lager spørsmål som JSON
  → koden sjekker at sitatet står i kilden → du svarer → lagres i SQLite

Kjør:  uv run python -m src.quiz --fag MRK1001 --tema "prisstrategi" --antall 5
       uv run python -m src.quiz --fag MRK1001 --tema "pris" --sjekk 20   (lag spørsmål til kontroll)
       uv run python -m src.quiz --resultater
"""

import argparse
import random
import re
from datetime import datetime

from src.database import koble, lagre_forsok, lagre_sporsmal, resultater
from src.henting import Bit, hent
from src.indeks import embed_sporsmal
from src.innlesing import standardfag
from src.konfig import data_mappe, last_innstillinger
from src.llm import generer_json

SYSTEM_FLERVALG = """Du lager flervalgsspørsmål til en student som øver til eksamen. Du skal BARE bruke teksten du får.

Regler:
1. Spørsmålet skal teste forståelse av et faglig begrep, en modell eller en sammenheng i teksten.
2. Spørsmålet skal kunne stå alene som en eksamensoppgave. Studenten ser ikke teksten, så ikke skriv
   «ifølge teksten» eller «i teksten».
3. Nøyaktig ett svar er riktig. De tre gale svarene skal være troverdige, men tydelig feil.
   Hvis teksten er en liste der flere punkter passer på spørsmålet, må de gale svarene IKKE hentes fra den listen.
4. Alle fire svar skal ha samme form og omtrent samme lengde. Ikke gjenta ord fra spørsmålet bare i det riktige
   svaret, og ikke skriv begrepets navn foran svarene.
5. Ikke spør om sidetall, årstall, navn på kilder eller andre detaljer uten faglig betydning.
6. «sitat» skal være en hel setning eller en lang del av en setning, kopiert ORDRETT fra teksten,
   som viser at svaret er riktig.
7. «forklaring» forklarer kort med egne ord hvorfor svaret er riktig.
8. Hvis teksten bare er stikkord uten sammenheng, uleselig, eller handler om hva som mangler i notatene,
   sett «kan_lages» til false og la de andre feltene være tomme.
Skriv på norsk."""

SYSTEM_KONTROLL = """Du kontrollerer et flervalgsspørsmål. Bruk BARE teksten du får.
Oppgi bokstaven til HVERT alternativ som er riktig ifølge teksten. Er flere riktige, oppgi alle.
Er ingen riktige, oppgi en tom liste."""

SKJEMA_KONTROLL = {
    "type": "object",
    "properties": {"riktige": {"type": "array", "items": {"type": "string", "enum": list("ABCD")}}},
    "required": ["riktige"],
}

SKJEMA_FLERVALG = {
    "type": "object",
    "properties": {
        "kan_lages": {"type": "boolean"},
        "sporsmal": {"type": "string"},
        "riktig_svar": {"type": "string"},
        "gale_svar": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "forklaring": {"type": "string"},
        "sitat": {"type": "string"},
    },
    "required": ["kan_lages", "sporsmal", "riktig_svar", "gale_svar", "forklaring", "sitat"],
}

BOKSTAVER = "ABCD"


def _normaliser(tekst: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”•·–—-]", " ", tekst.lower())).strip()


def sitat_finnes(sitat: str, kildetekst: str) -> bool:
    """Står sitatet i kilden? Små forskjeller i mellomrom og tegnsetting tillates.

    Dette er en billig kontroll mot oppdiktet fasit: kan ikke modellen vise hvor i
    teksten svaret står, stoler vi ikke på spørsmålet.
    """
    sitat, kilde = _normaliser(sitat), _normaliser(kildetekst)
    if len(sitat.split()) < 5:
        return False          # ett eller to ord beviser ikke noe
    if sitat in kilde:
        return True
    # Modellen endrer av og til et ord eller to. Godta hvis nesten alle ordene står i kilden.
    ord_ = sitat.split()
    return len(ord_) >= 5 and sum(o in kilde for o in ord_) / len(ord_) >= 0.9


def kandidat_biter(fag: str, tema: str, antall: int) -> list[Bit]:
    """Biter om temaet, med nok tekst til å lage et spørsmål, én per kilde."""
    biter, sett = [], set()
    for bit in hent(tema, fag=fag, k=max(antall * 3, 12)):
        if len(bit.tekst) >= 300 and bit.kilde not in sett:
            sett.add(bit.kilde)
            biter.append(bit)
    return biter


def lag_flervalg(bit: Bit) -> tuple[dict | None, str]:
    """Returnerer (spørsmål, "") eller (None, grunn til at det ble forkastet)."""
    try:
        data = generer_json(SYSTEM_FLERVALG, f"Tekst:\n{bit.tekst}", SKJEMA_FLERVALG)
    except ValueError:
        return None, "ugyldig JSON"
    if not data.get("kan_lages"):
        return None, "teksten egnet seg ikke"
    gale = [g for g in data["gale_svar"] if g.strip() and g.strip() != data["riktig_svar"].strip()]
    if len(gale) != 3 or not data["sporsmal"].strip():
        return None, "manglende eller like alternativer"
    if not sitat_finnes(data["sitat"], bit.tekst):
        return None, "sitatet står ikke i kilden"
    # Er det riktige svaret mye lengre enn de gale, kan man gjette det uten å kunne stoffet.
    if len(data["riktig_svar"]) > 1.6 * sum(len(g) for g in gale) / 3:
        return None, "riktig svar skiller seg ut ved å være mye lengre"

    # Stokk alternativene. Språkmodeller legger ofte riktig svar på samme plass.
    alternativer = gale + [data["riktig_svar"]]
    random.shuffle(alternativer)
    fasit_bokstav = BOKSTAVER[alternativer.index(data["riktig_svar"])]

    # Kontrollrunde: la modellen svare på sitt eget spørsmål. Finner den flere riktige
    # svar, eller et annet enn fasiten, er spørsmålet ikke til å stole på.
    oppgave = data["sporsmal"] + "\n" + "\n".join(f"{b}) {a}" for b, a in zip(BOKSTAVER, alternativer))
    try:
        kontroll = generer_json(SYSTEM_KONTROLL, f"Tekst:\n{bit.tekst}\n\nSpørsmål:\n{oppgave}", SKJEMA_KONTROLL)
    except ValueError:
        return None, "kontrollen ga ugyldig JSON"
    if sorted(set(kontroll["riktige"])) != [fasit_bokstav]:
        return None, f"kontrollen fant {kontroll['riktige'] or 'ingen'} riktige, fasit er {fasit_bokstav}"

    return {**data, "alternativer": alternativer, "fasit": data["riktig_svar"]}, ""


# Like spørsmål (samme stoff i notat og foil) har likhet ca. 0,96 med e5-vektorer, mens ulike
# spørsmål om samme tema ligger rundt 0,83–0,87 (målt 29.10.2026). Grensen ligger midt i gapet.
DUPLIKAT_GRENSE = 0.92


def sporsmal_strom(fag: str, tema: str, antall: int):
    """Gir ferdige spørsmål ett om gangen, og hopper over biter som ikke gir gode spørsmål."""
    biter = kandidat_biter(fag, tema, antall)
    laget = []      # vektorer for spørsmål + fasit som allerede er gitt
    for bit in biter:
        if len(laget) == antall:
            return
        sporsmal, grunn = lag_flervalg(bit)
        if sporsmal is None:
            print(f"  (hoppet over {bit.kilde}: {grunn})")
            continue
        # Vektorene er normaliserte, så skalarproduktet er cosinuslikheten.
        vektor = embed_sporsmal(sporsmal["sporsmal"] + " " + sporsmal["fasit"])
        if any(sum(x * y for x, y in zip(vektor, v)) > DUPLIKAT_GRENSE for v in laget):
            print(f"  (hoppet over {bit.kilde}: likner et spørsmål du allerede har fått)")
            continue
        laget.append(vektor)
        yield sporsmal, bit
    if len(laget) < antall:
        print(f"\nFant bare nok gode biter til {len(laget)} spørsmål om «{tema}». Prøv et bredere tema.")


def modellnavn() -> str:
    innst = last_innstillinger()["sprakmodell"]
    return innst[innst["leverandor"]]["modell"]


def kjor_quiz(fag: str, tema: str, antall: int):
    db = koble()
    riktige = besvart = 0
    print(f"\nQuiz i {fag} om «{tema}» ({antall} spørsmål). Svar med A, B, C eller D. Skriv q for å avslutte.\n")
    for nr, (q, bit) in enumerate(sporsmal_strom(fag, tema, antall), start=1):
        kilde = f"{fag}/{bit.kilde}"
        sid = lagre_sporsmal(db, fag=fag, tema=tema, ovingsmate="flervalg", sporsmal=q["sporsmal"],
                             alternativer=q["alternativer"], fasit=q["fasit"], forklaring=q["forklaring"],
                             sitat=q["sitat"], kilde=kilde, modell=modellnavn())

        print(f"{nr}. {q['sporsmal']}")
        for bokstav, alt in zip(BOKSTAVER, q["alternativer"]):
            print(f"   {bokstav}) {alt}")
        # Merk: "" in "ABCD" er True i Python, så sjekk lengden også.
        svar = input("Svar: ").strip().upper()
        while not (len(svar) == 1 and svar in BOKSTAVER + "Q"):
            svar = input("Skriv A, B, C, D (eller q for å avslutte): ").strip().upper()
        if svar == "Q":
            break

        riktig_bokstav = BOKSTAVER[q["alternativer"].index(q["fasit"])]
        er_riktig = svar == riktig_bokstav
        riktige += er_riktig
        besvart += 1
        lagre_forsok(db, sid, svar=q["alternativer"][BOKSTAVER.index(svar)], riktig=er_riktig)

        print("✓ Riktig!" if er_riktig else f"✗ Feil. Riktig svar er {riktig_bokstav}) {q['fasit']}")
        print(f"   {q['forklaring']}")
        print(f"   Kilde: {kilde}  «{q['sitat']}»\n")

    if besvart:
        print(f"Resultat: {riktige} av {besvart} riktige ({riktige / besvart:.0%}). Lagret i data/studie.db.")


def lag_sjekkfil(fag: str, tema: str, antall: int):
    """Lag spørsmål og skriv dem til en fil sammen med kildeteksten, så du kan kontrollere fasiten."""
    sti = data_mappe() / f"quizsjekk_{fag}_{datetime.now():%Y%m%d_%H%M}.md"
    linjer = [f"# Kontroll av quizspørsmål – {fag}, tema «{tema}»", "",
              f"Modell: {modellnavn()}. Sjekk for hvert spørsmål: er fasiten riktig ifølge kilden? "
              "Er det bare ett riktig svar? Er spørsmålet faglig nyttig?", ""]
    for nr, (q, bit) in enumerate(sporsmal_strom(fag, tema, antall), start=1):
        print(f"  laget {nr}/{antall}")
        linjer += [f"## {nr}. {q['sporsmal']}", ""]
        linjer += [f"- {'**' if a == q['fasit'] else ''}{a}{' (fasit)**' if a == q['fasit'] else ''}"
                   for a in q["alternativer"]]
        linjer += ["", f"Forklaring: {q['forklaring']}", "", f"Sitat: «{q['sitat']}»", "",
                   f"Kilde: {fag}/{bit.kilde}", "", "<details><summary>Kildetekst</summary>", "",
                   bit.tekst, "", "</details>", "", "Vurdering: ☐ riktig  ☐ feil fasit  ☐ uklart", ""]
    sti.write_text("\n".join(linjer), encoding="utf-8")
    print(f"\nSkrevet til {sti}")


def vis_resultater(fag: str | None):
    rader = resultater(koble(), fag)
    if not rader:
        print("Ingen quizresultater ennå.")
        return
    print(f"{'Fag':<9} {'Tema':<30} {'Riktige':>9} {'Andel':>6}  Sist øvd")
    for r in rader:
        andel = f"{r['riktige']}/{r['forsok']}"
        print(f"{r['fag']:<9} {r['tema'][:30]:<30} {andel:>9} "
              f"{r['riktige'] / r['forsok']:>6.0%}  {r['sist'][:16].replace('T', ' ')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flervalgsquiz fra pensumet ditt.")
    parser.add_argument("--fag", help="fag (standard: standardfag i innstillingene)")
    parser.add_argument("--tema", help="hva quizen skal handle om, f.eks. «prisstrategi» eller «kap 9»")
    parser.add_argument("--antall", type=int, default=5)
    parser.add_argument("--sjekk", type=int, metavar="N", help="lag N spørsmål til en kontrollfil i stedet for quiz")
    parser.add_argument("--resultater", action="store_true", help="vis tidligere resultater")
    args = parser.parse_args()

    if args.resultater:
        vis_resultater(args.fag)
    elif not args.tema:
        parser.error("skriv --tema, f.eks. --tema \"prisstrategi\"")
    elif args.sjekk:
        lag_sjekkfil(args.fag or standardfag(), args.tema, args.sjekk)
    else:
        kjor_quiz(args.fag or standardfag(), args.tema, args.antall)
