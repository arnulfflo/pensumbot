"""Fase 4: repetisjon av feilsvar, voksende intervaller og mestring per tema.

Spørsmål (flervalg, kortsvar):
  - Feil svar → kommer igjen om 1 dag.
  - Riktig, og spørsmålet står i repetisjonskøen → neste intervall: 1 → 3 → 7 → 14 → 30 dager.
  - Riktig etter 30 dager → lært, ute av køen. Riktig første gang → kommer ikke igjen.
Flashcards:
  - Intervallet vokser etter hvor godt du kunne kortet (lett ×4, greit ×2,5, vanskelig ×1,2).
Mestring per tema:
  - Glidende snitt av riktig/feil, der de siste forsøkene veier mest. Lagres i tabellen temaer
    og brukes av planleggeren: svake temaer kommer oftere.

Kjør:  uv run python -m src.repetisjon            (alt som skal repeteres i dag)
       uv run python -m src.repetisjon --fag MRK1001
       uv run python -m src.repetisjon --mestring  (vis mestring per tema)
"""

import argparse
import json
from datetime import datetime, timedelta

from src.database import lagre_forsok, naa

QUIZ_INTERVALLER = [1, 3, 7, 14, 30]    # dager (SPEC.md: 1, 3 og 7, så videre)
MAKS_KORTINTERVALL = 180                # dager


# ---------- rene funksjoner (testes i tester/test_repetisjon.py) ----------

def neste_quiz_intervall(forrige: float | None, riktig: bool) -> int | None:
    """forrige: intervallet (dager) som gjaldt da du svarte, eller None hvis spørsmålet ikke var i køen.

    Returnerer antall dager til neste visning, eller None (ikke vis igjen).
    """
    if not riktig:
        return QUIZ_INTERVALLER[0]          # feil: start på nytt
    if forrige is None:
        return None                         # riktig første gang: ikke i køen
    return next((d for d in QUIZ_INTERVALLER if d > forrige + 0.5), None)   # None = lært


def neste_kort_intervall(forrige: float | None, vurdering: str) -> float:
    """Dager til kortet vises igjen. 0 = senere i samme økt."""
    if vurdering == "igjen":
        return 0
    forrige = forrige or 0
    gange, minst = {"vanskelig": (1.2, 1), "greit": (2.5, 3), "lett": (4, 7)}[vurdering]
    return min(MAKS_KORTINTERVALL, max(minst, forrige * gange))


def mestring(resultater: list[int], start: float = 0.5, vekt: float = 0.3) -> float:
    """Glidende snitt (eksponentielt): hvert nytt forsøk teller 30 %, alt tidligere 70 %.

    Uten forsøk er mestringen 0,5 (ukjent). Tre riktige på rad gir ca. 0,83, tre feil ca. 0,17.
    """
    m = start
    for r in resultater:
        m = (1 - vekt) * m + vekt * r
    return m


# ---------- database ----------

def _forrige_intervall(db, sporsmal_id: int) -> float | None:
    """Intervallet (dager) fra forrige forsøk, hvis spørsmålet sto i repetisjonskøen."""
    rad = db.execute("SELECT tidspunkt, neste_repetisjon FROM forsok WHERE sporsmal_id = ? ORDER BY id DESC LIMIT 1",
                     (sporsmal_id,)).fetchone()
    if not rad or not rad["neste_repetisjon"]:
        return None
    dt = datetime.fromisoformat(rad["neste_repetisjon"]) - datetime.fromisoformat(rad["tidspunkt"])
    return dt.total_seconds() / 86400


def lagre_resultat(db, sporsmal_id: int, svar: str, riktig: bool, tilbakemelding: str | None = None,
                   vurdering: str | None = None) -> datetime | None:
    """Lagrer forsøket med riktig neste repetisjon, og oppdaterer mestringen for temaet.

    vurdering: bare for flashcards (igjen/vanskelig/greit/lett). Returnerer neste visning.
    """
    rad = db.execute("SELECT fag, tema, ovingsmate FROM sporsmal WHERE id = ?", (sporsmal_id,)).fetchone()
    forrige = _forrige_intervall(db, sporsmal_id)
    if rad["ovingsmate"] == "flashcard":
        dager = neste_kort_intervall(forrige, vurdering)
    else:
        dager = neste_quiz_intervall(forrige, riktig)
    neste = datetime.now() + timedelta(days=dager) if dager is not None else None
    lagre_forsok(db, sporsmal_id, svar=svar, riktig=riktig, tilbakemelding=tilbakemelding,
                 neste_repetisjon=neste.isoformat(timespec="seconds") if neste else None)
    oppdater_tema(db, rad["fag"], rad["tema"])
    return neste


def oppdater_tema(db, fag: str, tema: str):
    rader = db.execute("SELECT f.riktig, f.tidspunkt FROM forsok f JOIN sporsmal s ON s.id = f.sporsmal_id"
                       " WHERE s.fag = ? AND s.tema = ? ORDER BY f.id", (fag, tema)).fetchall()
    db.execute("INSERT INTO temaer (fag, tema, mestring, forsok, sist_ovd) VALUES (?, ?, ?, ?, ?)"
               " ON CONFLICT (fag, tema) DO UPDATE SET mestring = excluded.mestring, forsok = excluded.forsok,"
               " sist_ovd = excluded.sist_ovd",
               (fag, tema, mestring([r["riktig"] for r in rader]), len(rader), rader[-1]["tidspunkt"] if rader else None))
    db.commit()


def mestring_per_tema(db) -> dict:
    """{(fag, tema): mestring} for planleggeren."""
    return {(r["fag"], r["tema"]): r["mestring"] for r in db.execute("SELECT * FROM temaer")}


def forfalte_sporsmal(db, fag: str | None = None) -> list:
    """Flervalg og kortsvar der siste forsøk sier at spørsmålet skal vises igjen nå."""
    return db.execute(
        "SELECT s.* FROM sporsmal s JOIN forsok f ON f.id = (SELECT MAX(id) FROM forsok WHERE sporsmal_id = s.id)"
        " WHERE s.ovingsmate IN ('flervalg', 'kortsvar') AND f.neste_repetisjon <= ? AND (? IS NULL OR s.fag = ?)"
        " ORDER BY f.neste_repetisjon",
        (naa(), fag, fag),
    ).fetchall()


# ---------- økt ----------

def repeter(db, fag: str | None = None) -> int:
    """Still forfalte spørsmål på nytt. Returnerer antall besvarte."""
    from src.henting import Bit
    from src.quiz import still_flervalg, still_kortsvar

    sporsmal = forfalte_sporsmal(db, fag)
    if not sporsmal:
        print("Ingen spørsmål skal repeteres nå.")
        return 0
    print(f"\n{len(sporsmal)} spørsmål du har svart feil på før, skal repeteres. Skriv q for å avslutte.\n")
    besvart = 0
    for nr, s in enumerate(sporsmal, start=1):
        liste = json.loads(s["alternativer"]) if s["alternativer"] else []
        bit = Bit(s["kildetekst"] or s["sitat"] or "", {"fil": s["kilde"]}, 0.0)
        if s["ovingsmate"] == "flervalg":
            q = {"sporsmal": s["sporsmal"], "alternativer": liste, "fasit": s["fasit"], "forklaring": s["forklaring"]}
            still = still_flervalg
        else:
            q = {"sporsmal": s["sporsmal"], "nokkelpunkter": liste, "modellsvar": s["fasit"], "fasit": s["fasit"]}
            still = still_kortsvar
        print(f"{nr}. [{s['fag']} · {s['tema']}]\n   {s['sporsmal']}")
        resultat = still(q, bit)
        if resultat is None:
            break
        svar, riktig, tilbakemelding = resultat
        neste = lagre_resultat(db, s["id"], svar, riktig, tilbakemelding)
        besvart += 1
        print(f"   Kilde: {s['kilde']}")
        print(f"   Neste gang: {neste:%d.%m}\n" if neste else "   Lært! Spørsmålet kommer ikke igjen.\n")
    return besvart


def vis_mestring(db, fag: str | None):
    rader = db.execute("SELECT * FROM temaer WHERE (? IS NULL OR fag = ?) ORDER BY fag, mestring",
                       (fag, fag)).fetchall()
    if not rader:
        print("Ingen mestring registrert ennå. Ta en quiz eller øv på flashcards først.")
        return
    print(f"{'Fag':<9} {'Mestring':>8} {'Forsøk':>7}  Tema")
    for r in rader:
        stolpe = "█" * round(r["mestring"] * 10)
        print(f"{r['fag']:<9} {r['mestring']:>7.0%} {r['forsok']:>7}  {stolpe:<10} {r['tema']}")


if __name__ == "__main__":
    from src.database import koble

    parser = argparse.ArgumentParser(description="Repetisjon av feilsvar og mestring per tema.")
    parser.add_argument("--fag")
    parser.add_argument("--mestring", action="store_true", help="vis mestring per tema")
    args = parser.parse_args()
    db = koble()
    if args.mestring:
        vis_mestring(db, args.fag)
    else:
        repeter(db, args.fag)
