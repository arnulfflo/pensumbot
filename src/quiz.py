"""Fase 2: quiz laget fra ditt eget materiale, som flervalg eller kortsvar.

Flyt per spørsmål:
  tema → hent biter → velg én bit → språkmodellen lager spørsmål som JSON
  → koden kontrollerer spørsmålet → du svarer → lagres i SQLite

Kjør:  uv run python -m src.quiz --fag MRK1001 --tema "prisstrategi" --antall 5
       uv run python -m src.quiz --fag MRK1001 --tema "lojalitet" --type kortsvar --stil case
       uv run python -m src.quiz --fag MRK1001 --tema "pris" --sjekk 20   (lag spørsmål til kontroll)
       uv run python -m src.quiz --resultater
"""

import argparse
import random
from datetime import datetime

from src.database import koble, lagre_sporsmal, resultater
from src.henting import Bit, hent
from src.kontroll import Duplikatfilter, avslorer_svaret, sitat_finnes, viser_til_ukjent
from src.kortsvar import REKKEFOLGE, STILER, lag_kortsvar, vurder
from src.innlesing import standardfag
from src.konfig import data_mappe, last_innstillinger
from src.llm import generer_json
from src.repetisjon import lagre_resultat
from src.terminal import les

SYSTEM_FLERVALG = """Du lager flervalgsspørsmål til en student som øver til eksamen. Du skal BARE bruke teksten du får.

Regler:
1. Spørsmålet skal teste forståelse av et faglig begrep, en modell eller en sammenheng i teksten.
2. Spørsmålet skal kunne stå alene som en eksamensoppgave. Studenten ser ikke teksten, så ikke skriv
   «ifølge teksten» eller «i teksten». Er teksten en oppgave om en bestemt bedrift eller med egne tall,
   ikke spør om den bedriften eller de tallene. Spør om prinsippet eller metoden i stedet.
3. Nøyaktig ett svar er riktig. De tre gale svarene skal være troverdige, men tydelig feil.
   Hvis teksten er en liste der flere punkter passer på spørsmålet, må de gale svarene IKKE hentes fra den listen.
4. Alle fire svar skal ha samme form og omtrent samme lengde. Ikke gjenta ord fra spørsmålet bare i det riktige
   svaret, og ikke skriv begrepets navn foran svarene.
5. Ikke spør om sidetall, årstall, navn på kilder eller andre detaljer uten faglig betydning.
6. «sitat» skal være en hel setning eller en lang del av en setning, kopiert ORDRETT fra teksten,
   som viser at svaret er riktig.
7. «forklaring» forklarer kort med egne ord hvorfor svaret er riktig.
8. Det riktige svaret skal ikke gjenta ord fra spørsmålet. Spør du etter et begrep eller en type
   («Hvilken type distribusjon …»), skal alle fire svar være navn på begreper (f.eks. «Intensiv distribusjon»),
   ikke beskrivelser. Spør du hva et begrep innebærer, skal svarene være beskrivelser, og begrepet skal stå i spørsmålet.
9. Hvis teksten bare er stikkord uten sammenheng, uleselig, eller handler om hva som mangler i notatene,
   sett «kan_lages» til false og la de andre feltene være tomme.
Skriv på norsk."""

SYSTEM_KONTROLL = """Du kontrollerer et flervalgsspørsmål. Bruk BARE teksten du får.
Oppgi bokstaven til HVERT alternativ som er riktig ifølge teksten. Er flere riktige, oppgi alle.
Er ingen riktige, oppgi en tom liste."""

SKJEMA_KONTROLL = {
    "type": "object",
    "properties": {"riktige": {"type": "array", "items": {"type": "string"}}},
    "required": ["riktige"],
}

SKJEMA_FLERVALG = {
    "type": "object",
    "properties": {
        "kan_lages": {"type": "boolean"},
        "sporsmal": {"type": "string"},
        "riktig_svar": {"type": "string"},
        "gale_svar": {"type": "array", "items": {"type": "string"}},
        "forklaring": {"type": "string"},
        "sitat": {"type": "string"},
    },
    "required": ["kan_lages", "sporsmal", "riktig_svar", "gale_svar", "forklaring", "sitat"],
}

BOKSTAVER = "ABCD"


def kandidat_biter(fag: str, tema: str, antall: int) -> list[Bit]:
    """Biter om temaet, med nok tekst til å lage et spørsmål.

    Før var det bare én bit per kilde, men et Word-notat er én kilde uansett lengde, så et helt
    kapittel ga bare én bit. Nå er hver bit en kandidat; duplikatfilteret stopper like spørsmål.
    """
    biter = []
    # Bare øvingskilder: løsninger og eksempelsvar skal aldri lekke inn i spørsmål (SPEC.md).
    typer = last_innstillinger()["innlesing"]["ovingskilder"]
    for bit in hent(tema, fag=fag, k=max(antall * 3, 12), typer=typer):
        # Emneoversikten handler om kurset (datoer, fremdriftsplan), ikke om faget.
        if "emneoversikt" in bit.metadata["fil"]:
            continue
        if len(bit.tekst) >= 300:
            biter.append(bit)
    return biter


def lag_flervalg(bit: Bit) -> tuple[dict | None, str]:
    """Returnerer (spørsmål, "") eller (None, grunn til at det ble forkastet)."""
    try:
        data = generer_json(SYSTEM_FLERVALG, f"Tekst:\n{bit.tekst}", SKJEMA_FLERVALG)
    except ValueError:
        return None, "ugyldig JSON"
    except TimeoutError:
        return None, "modellen brukte for lang tid"
    if not data.get("kan_lages"):
        return None, "teksten egnet seg ikke"
    gale = [g for g in data["gale_svar"] if g.strip() and g.strip() != data["riktig_svar"].strip()][:3]
    if len(gale) != 3 or not data["sporsmal"].strip():
        return None, "manglende eller like alternativer"
    if not sitat_finnes(data["sitat"], bit.tekst):
        return None, "sitatet står ikke i kilden"
    if grunn := viser_til_ukjent(data["sporsmal"], bit.tekst):
        return None, grunn
    if grunn := avslorer_svaret(data["sporsmal"], data["riktig_svar"], gale):
        return None, grunn
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
    except TimeoutError:
        return None, "kontrollen brukte for lang tid"
    # Rydd opp i svaret («B)», « b » → «B»), siden skjemaet ikke låser bokstavene.
    funnet = sorted({r.strip().upper()[:1] for r in kontroll["riktige"] if r.strip()})
    if funnet != [fasit_bokstav]:
        return None, f"kontrollen fant {funnet or 'ingen'} riktige, fasit er {fasit_bokstav}"

    return {**data, "alternativer": alternativer, "fasit": data["riktig_svar"]}, ""


def sporsmal_strom(fag: str, tema: str, antall: int, type_: str = "flervalg", stil: str = "forklar"):
    """Gir ferdige spørsmål ett om gangen, og hopper over biter som ikke gir gode spørsmål."""
    duplikater = Duplikatfilter()
    laget = 0
    for bit in kandidat_biter(fag, tema, antall):
        if laget == antall:
            return
        if type_ == "flervalg":
            sporsmal, grunn = lag_flervalg(bit)
        else:
            # «blandet» veksler mellom stilene, så én økt gir case, hvorfor, sammenlign og forklar.
            denne = REKKEFOLGE[laget % len(REKKEFOLGE)] if stil == "blandet" else stil
            sporsmal, grunn = lag_kortsvar(bit, denne)
        if sporsmal is None:
            print(f"  (hoppet over {bit.kilde}: {grunn})")
            continue
        if duplikater.er_duplikat(sporsmal["sporsmal"] + " " + sporsmal["fasit"]):
            print(f"  (hoppet over {bit.kilde}: likner et spørsmål du allerede har fått)")
            continue
        laget += 1
        yield sporsmal, bit
    if laget < antall:
        print(f"\nFant bare nok gode biter til {laget} spørsmål om «{tema}». Prøv et bredere tema.")


def modellnavn() -> str:
    innst = last_innstillinger()["sprakmodell"]
    return innst[innst["leverandor"]]["modell"]


def still_flervalg(q: dict, bit: Bit) -> tuple[str, bool, str | None] | None:
    """Viser spørsmålet, leser svaret og sier om det var riktig. None = brukeren avsluttet."""
    for bokstav, alt in zip(BOKSTAVER, q["alternativer"]):
        print(f"   {bokstav}) {alt}")
    # Merk: "" in "ABCD" er True i Python, så sjekk lengden også.
    svar = les("Svar: ").upper()
    while not (len(svar) == 1 and svar in BOKSTAVER + "Q"):
        svar = les("Skriv A, B, C, D (eller q for å avslutte): ").upper()
    if svar == "Q":
        return None
    riktig_bokstav = BOKSTAVER[q["alternativer"].index(q["fasit"])]
    er_riktig = svar == riktig_bokstav
    print("✓ Riktig!" if er_riktig else f"✗ Feil. Riktig svar er {riktig_bokstav}) {q['fasit']}")
    print(f"   {q['forklaring']}")
    return q["alternativer"][BOKSTAVER.index(svar)], er_riktig, None


def still_kortsvar(q: dict, bit: Bit) -> tuple[str, bool, str | None] | None:
    svar = ""
    while len(svar.split()) < 3:
        svar = les("Svaret ditt (2–4 setninger, q for å avslutte): ")
        if svar.lower() == "q":
            return None
    print("   (vurderer ...)")
    try:
        v = vurder(q, svar, bit.tekst)
    except (TimeoutError, ValueError):
        # Uten vurdering: vis modellsvaret og la studenten vurdere selv.
        print(f"   Vurderingen feilet. Sammenlign selv med modellsvaret:\n   {q['modellsvar']}")
        egen = ""
        while egen not in ("j", "n"):
            egen = les("   Var svaret ditt riktig? (j/n): ").lower()
            if egen == "q":
                return None
        return svar, egen == "j", "egenvurdering (modellen svarte ikke)"
    print(f"{'✓ Godkjent' if v['riktig'] else '✗ Ikke godkjent'}: {sum(v['dekket'])} av {len(v['dekket'])} nøkkelpunkter")
    for punkt, dekket in zip(q["nokkelpunkter"], v["dekket"]):
        print(f"   {'✓' if dekket else '·'} {punkt}")
    for feil in v["feil"]:
        print(f"   ✗ Stemmer ikke med kilden: {feil}")
    print(f"   {v['tilbakemelding']}")
    print(f"   Modellsvar: {q['modellsvar']}")
    print("   (Vurderingen er en indikasjon fra en liten modell, ikke en karakter.)")
    return svar, v["riktig"], v["tilbakemelding"]


def kjor_quiz(fag: str, tema: str, antall: int, type_: str = "flervalg", stil: str = "forklar"):
    db = koble()
    riktige = besvart = 0
    hjelp = "Svar med A, B, C eller D" if type_ == "flervalg" else "Svar med egne ord"
    print(f"\n{type_.capitalize()} i {fag} om «{tema}» ({antall} spørsmål). {hjelp}. Skriv q for å avslutte.\n")
    for nr, (q, bit) in enumerate(sporsmal_strom(fag, tema, antall, type_, stil), start=1):
        kilde = f"{fag}/{bit.kilde}"
        sid = lagre_sporsmal(db, fag=fag, tema=tema, ovingsmate=type_, sporsmal=q["sporsmal"],
                             alternativer=q.get("alternativer") or q.get("nokkelpunkter"), fasit=q["fasit"],
                             forklaring=q.get("forklaring"), sitat=q["sitat"], kilde=kilde, modell=modellnavn(),
                             kildetekst=bit.tekst)

        etikett = f"[{q['stil']}] " if q.get("stil") and q["stil"] != "forklar" else ""
        print(f"{nr}. {etikett}{q['sporsmal']}")
        resultat = (still_flervalg if type_ == "flervalg" else still_kortsvar)(q, bit)
        if resultat is None:
            break
        svar, er_riktig, tilbakemelding = resultat
        riktige += er_riktig
        besvart += 1
        neste = lagre_resultat(db, sid, svar, er_riktig, tilbakemelding)
        print(f"   Kilde: {kilde}  «{q['sitat']}»")
        print(f"   Kommer igjen {neste:%d.%m} for repetisjon.\n" if neste else "")

    if besvart:
        print(f"Resultat: {riktige} av {besvart} riktige ({riktige / besvart:.0%}). Lagret i data/studie.db.")


def lag_sjekkfil(fag: str, tema: str, antall: int, type_: str = "flervalg", stil: str = "forklar"):
    """Lag spørsmål og skriv dem til en fil sammen med kildeteksten, så du kan kontrollere fasiten."""
    sti = data_mappe() / f"quizsjekk_{fag}_{type_}_{datetime.now():%Y%m%d_%H%M}.md"
    linjer = [f"# Kontroll av {type_}spørsmål – {fag}, tema «{tema}»", "",
              f"Modell: {modellnavn()}. Sjekk for hvert spørsmål: er fasiten riktig ifølge kilden? "
              "Er det bare ett riktig svar? Er spørsmålet faglig nyttig?", ""]
    for nr, (q, bit) in enumerate(sporsmal_strom(fag, tema, antall, type_, stil), start=1):
        print(f"  laget {nr}/{antall}")
        linjer += [f"## {nr}. {'[' + q['stil'] + '] ' if q.get('stil') else ''}{q['sporsmal']}", ""]
        if type_ == "flervalg":
            linjer += [f"- {'**' if a == q['fasit'] else ''}{a}{' (fasit)**' if a == q['fasit'] else ''}"
                       for a in q["alternativer"]]
            linjer += ["", f"Forklaring: {q['forklaring']}"]
        else:
            linjer += ["Nøkkelpunkter:"] + [f"- {p}" for p in q["nokkelpunkter"]]
            linjer += ["", f"Modellsvar: {q['modellsvar']}"]
        linjer += ["", f"Sitat: «{q['sitat']}»", "",
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
    parser = argparse.ArgumentParser(description="Quiz fra pensumet ditt.")
    parser.add_argument("--fag", help="fag (standard: standardfag i innstillingene)")
    parser.add_argument("--tema", help="hva quizen skal handle om, f.eks. «prisstrategi» eller «kap 9»")
    parser.add_argument("--antall", type=int, default=5)
    parser.add_argument("--type", choices=["flervalg", "kortsvar"], default="flervalg")
    parser.add_argument("--stil", choices=[*STILER, "blandet"], default="forklar",
                        help="for kortsvar: forklar, hvorfor, sammenlign, case eller blandet")
    parser.add_argument("--sjekk", type=int, metavar="N", help="lag N spørsmål til en kontrollfil i stedet for quiz")
    parser.add_argument("--resultater", action="store_true", help="vis tidligere resultater")
    args = parser.parse_args()

    if args.resultater:
        vis_resultater(args.fag)
    elif not args.tema:
        parser.error("skriv --tema, f.eks. --tema \"prisstrategi\"")
    elif args.sjekk:
        lag_sjekkfil(args.fag or standardfag(), args.tema, args.sjekk, args.type, args.stil)
    else:
        kjor_quiz(args.fag or standardfag(), args.tema, args.antall, args.type, args.stil)
