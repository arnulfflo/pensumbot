"""Kommandoen «i dag»: viser dagens blokker fra planen og starter øvingen du velger.

Når du er ferdig med en blokk, markeres den som fullført, og planen fra i morgen lages
på nytt med oppdatert mestring. Slik får temaer du sliter med, mer tid (fase 4).
Spørsmål og kort som skal repeteres i dag, kan startes med «r».

Kjør:  uv run python -m src.i_dag
"""

from datetime import date, timedelta

from src.database import koble
from src.flashcards import forfalte, lag_nye_kort, ov
from src.innlesing import alle_fag
from src.planlegger import UKEDAGER, blokker_for, lag_og_lagre, marker_fullfort
from src.quiz import kjor_quiz
from src.repetisjon import forfalte_sporsmal, repeter
from src.terminal import les

# Hvor mye hver øvingsmåte gjør på én blokk (ca. 45 minutter med lesing av kildene).
OVELSER = {
    "flashcards": "6 nye kort, så repetisjon av kortene i temaet",
    "flervalg": "5 flervalgsspørsmål",
    "kortsvar": "4 oppgaver: case, hvorfor, sammenlign og forklar",
    "repetisjon": "4 oppgaver i blandet stil (repetisjon før eksamen)",
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
        kjor_quiz(fag, tema, 4, "kortsvar", stil="blandet")


def antall_til_repetisjon(db) -> tuple[int, int]:
    """(spørsmål, flashcards) som skal repeteres nå, i alle fag. Nye kort som aldri er øvd, telles ikke."""
    kort = sum(1 for fag in alle_fag() for k in forfalte(db, fag, None) if k["neste"])
    return len(forfalte_sporsmal(db)), kort


def repeter_alt(db):
    repeter(db)
    for fag in {k["fag"] for k in db.execute("SELECT DISTINCT fag FROM sporsmal WHERE ovingsmate = 'flashcard'")}:
        kort = [k for k in forfalte(db, fag, None) if k["neste"]]
        if kort:
            print(f"\nFlashcards i {fag} som skal repeteres:")
            ov(db, kort)


def vis(blokker, db):
    i_dag = date.today()
    print(f"\nI dag, {UKEDAGER[i_dag.weekday()]} {i_dag:%d.%m}:")
    for nr, b in enumerate(blokker, start=1):
        tegn = {"fullfort": "✓", "hoppet_over": "–"}.get(b["status"], " ")
        print(f"  {nr}. [{tegn}] {b['fag']}  {b['ovingsmate']:<10} {b['tema']}")
    igjen = sum(b["status"] == "planlagt" for b in blokker)
    print(f"  {igjen} av {len(blokker)} blokker igjen.")
    sporsmal, kort = antall_til_repetisjon(db)
    if sporsmal or kort:
        print(f"  r. Repetisjon: {sporsmal} spørsmål du svarte feil på før, {kort} flashcards")


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
        vis(blokker, db)
        valg = les("\nVelg en blokk (nummer), r for repetisjon, eller q for å avslutte: ").lower()
        if valg == "q" or valg == "":
            break
        if valg == "r":
            repeter_alt(db)
            continue
        if not valg.isdigit() or not 1 <= int(valg) <= len(blokker):
            print("Skriv et nummer fra listen.")
            continue
        blokk = blokker[int(valg) - 1]
        print(f"\n{blokk['fag']} · {blokk['tema']} · {OVELSER[blokk['ovingsmate']]}")
        start_ovelse(db, blokk)

        svar = ""
        while svar not in ("j", "n", "q"):
            svar = les("\nMarker blokken som fullført? (j/n): ").lower()
        if svar == "j":
            marker_fullfort(db, blokk["id"])
            # Planlegg fra i morgen på nytt, med mestringen fra økten du nettopp hadde.
            lag_og_lagre(db, date.today() + timedelta(days=1))
        if svar == "q":
            break
        blokker = [b for b in blokker_for(db, date.today()) if b["fag"] != "-"]


if __name__ == "__main__":
    main()
