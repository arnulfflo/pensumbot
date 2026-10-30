"""Kommandoen «i dag»: viser dagens blokker fra planen og starter øvingen du velger.

Når du er ferdig med en blokk, markeres den som fullført. Da vet planleggeren hva du
har øvd på, og temaet kommer igjen senere i stedet for i morgen.

Kjør:  uv run python -m src.i_dag
"""

from datetime import date

from src.database import koble
from src.flashcards import forfalte, lag_nye_kort, ov
from src.planlegger import UKEDAGER, blokker_for, lag_og_lagre, marker_fullfort
from src.quiz import kjor_quiz

# Hvor mye hver øvingsmåte gjør på én blokk (ca. 45 minutter med lesing av kildene).
OVELSER = {
    "flashcards": "6 nye kort, så repetisjon av kortene i temaet",
    "flervalg": "5 flervalgsspørsmål",
    "kortsvar": "3 kortsvarsoppgaver",
    "repetisjon": "3 kortsvarsoppgaver (repetisjon før eksamen)",
}


def start_ovelse(db, blokk):
    fag, tema, modus = blokk["fag"], blokk["tema"], blokk["ovingsmate"]
    if modus == "flashcards":
        lag_nye_kort(db, fag, tema, 6)
        kort = forfalte(db, fag, tema)
        if kort:
            ov(db, kort)
        else:
            print("Ingen kort å øve på i dette temaet nå.")
    elif modus == "flervalg":
        kjor_quiz(fag, tema, 5, "flervalg")
    else:
        kjor_quiz(fag, tema, 3, "kortsvar")


def vis(blokker):
    i_dag = date.today()
    print(f"\nI dag, {UKEDAGER[i_dag.weekday()]} {i_dag:%d.%m}:")
    for nr, b in enumerate(blokker, start=1):
        tegn = {"fullfort": "✓", "hoppet_over": "–"}.get(b["status"], " ")
        print(f"  {nr}. [{tegn}] {b['fag']}  {b['ovingsmate']:<10} {b['tema']}")
    igjen = sum(b["status"] == "planlagt" for b in blokker)
    print(f"  {igjen} av {len(blokker)} blokker igjen.")


def main():
    db = koble()
    blokker = [b for b in blokker_for(db, date.today()) if b["fag"] != "-"]
    if not blokker:
        print("Ingen plan for i dag. Lager planen nå ...")
        lag_og_lagre(db)
        blokker = [b for b in blokker_for(db, date.today()) if b["fag"] != "-"]
        if not blokker:
            print("Fortsatt ingenting planlagt i dag (fridag eller etter siste eksamen).")
            return

    while True:
        vis(blokker)
        valg = input("\nVelg en blokk (nummer), eller q for å avslutte: ").strip().lower()
        if valg == "q" or valg == "":
            break
        if not valg.isdigit() or not 1 <= int(valg) <= len(blokker):
            print("Skriv et nummer fra listen.")
            continue
        blokk = blokker[int(valg) - 1]
        print(f"\n{blokk['fag']} · {blokk['tema']} · {OVELSER[blokk['ovingsmate']]}")
        start_ovelse(db, blokk)

        svar = ""
        while svar not in ("j", "n"):
            svar = input("\nMarker blokken som fullført? (j/n): ").strip().lower()
        if svar == "j":
            marker_fullfort(db, blokk["id"])
        blokker = [b for b in blokker_for(db, date.today()) if b["fag"] != "-"]


if __name__ == "__main__":
    main()
