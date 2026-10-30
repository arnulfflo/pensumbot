"""SQLite-databasen for alt som skal telles: quizspørsmål og forsøk.

Chroma er for tekst som skal søkes etter mening. SQLite er for tall og historikk
som skal regnes på (poengsum, hva du svarte feil på, når du øvde).

Tabellene følger SPEC.md. Eksamensdatoene ligger i config/eksamener.yaml i stedet for en egen tabell.
"""

import json
import sqlite3
from datetime import datetime

from src.konfig import data_mappe

SKJEMA = """
CREATE TABLE IF NOT EXISTS sporsmal (
    id           INTEGER PRIMARY KEY,
    fag          TEXT NOT NULL,
    tema         TEXT NOT NULL,
    ovingsmate   TEXT NOT NULL,          -- flervalg, kortsvar, flashcard ...
    sporsmal     TEXT NOT NULL,
    alternativer TEXT,                   -- JSON-liste, bare for flervalg
    fasit        TEXT NOT NULL,
    forklaring   TEXT,
    sitat        TEXT,                   -- ordrett fra kilden, brukes som kontroll
    kilde        TEXT NOT NULL,          -- f.eks. MRK1001/notater/kap 9.docx
    modell       TEXT,                   -- hvilken språkmodell som laget spørsmålet
    laget        TEXT NOT NULL,
    kildetekst   TEXT                    -- biten spørsmålet ble laget fra (trengs når kortsvar repeteres)
);
CREATE TABLE IF NOT EXISTS forsok (
    id               INTEGER PRIMARY KEY,
    sporsmal_id      INTEGER NOT NULL REFERENCES sporsmal(id),
    tidspunkt        TEXT NOT NULL,
    svar             TEXT,
    riktig           INTEGER NOT NULL,   -- 1 = riktig, 0 = feil
    tilbakemelding   TEXT,
    neste_repetisjon TEXT                -- når spørsmålet/kortet skal vises igjen (NULL = ikke)
);
CREATE TABLE IF NOT EXISTS plan (
    id          INTEGER PRIMARY KEY,
    dato        TEXT NOT NULL,           -- ÅÅÅÅ-MM-DD
    fag         TEXT NOT NULL,
    tema        TEXT NOT NULL,
    ovingsmate  TEXT NOT NULL,           -- flashcards, flervalg, kortsvar, repetisjon
    minutter    INTEGER NOT NULL,
    status      TEXT NOT NULL            -- planlagt, fullfort, hoppet_over
);
CREATE TABLE IF NOT EXISTS temaer (
    fag         TEXT NOT NULL,
    tema        TEXT NOT NULL,
    mestring    REAL NOT NULL,           -- 0–1, regnes ut fra forsøkene (se repetisjon.py)
    forsok      INTEGER NOT NULL,
    sist_ovd    TEXT,
    PRIMARY KEY (fag, tema)
);
"""

# Kolonner som er lagt til etter at databasen kan ha blitt laget. Legges til hvis de mangler.
NYE_KOLONNER = {"sporsmal": {"kildetekst": "TEXT"}}


def koble() -> sqlite3.Connection:
    data_mappe().mkdir(exist_ok=True)
    db = sqlite3.connect(data_mappe() / "studie.db")
    db.row_factory = sqlite3.Row      # rader kan leses som rad["fag"]
    db.executescript(SKJEMA)
    for tabell, kolonner in NYE_KOLONNER.items():
        finnes = {r["name"] for r in db.execute(f"PRAGMA table_info({tabell})")}
        for navn, type_ in kolonner.items():
            if navn not in finnes:
                db.execute(f"ALTER TABLE {tabell} ADD COLUMN {navn} {type_}")
    return db


def naa() -> str:
    return datetime.now().isoformat(timespec="seconds")


def lagre_sporsmal(db, *, fag, tema, ovingsmate, sporsmal, fasit, kilde,
                   alternativer=None, forklaring=None, sitat=None, modell=None, kildetekst=None) -> int:
    rad = db.execute(
        "INSERT INTO sporsmal (fag, tema, ovingsmate, sporsmal, alternativer, fasit, forklaring,"
        " sitat, kilde, modell, laget, kildetekst) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fag, tema, ovingsmate, sporsmal, json.dumps(alternativer, ensure_ascii=False) if alternativer else None,
         fasit, forklaring, sitat, kilde, modell, naa(), kildetekst),
    )
    db.commit()
    return rad.lastrowid


def lagre_forsok(db, sporsmal_id: int, svar: str, riktig: bool, tilbakemelding: str | None = None,
                 neste_repetisjon: str | None = None):
    db.execute(
        "INSERT INTO forsok (sporsmal_id, tidspunkt, svar, riktig, tilbakemelding, neste_repetisjon)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (sporsmal_id, naa(), svar, int(riktig), tilbakemelding, neste_repetisjon),
    )
    db.commit()


def kort(db, fag: str, tema: str | None = None) -> list[sqlite3.Row]:
    """Alle flashcards i faget (eventuelt ett tema), med tidspunktet de skal repeteres.

    neste er NULL for kort som aldri er øvd. Et kort forfaller når neste <= nå.
    """
    return db.execute(
        "SELECT s.*, (SELECT f.neste_repetisjon FROM forsok f WHERE f.sporsmal_id = s.id"
        "             ORDER BY f.id DESC LIMIT 1) AS neste"
        " FROM sporsmal s WHERE s.ovingsmate = 'flashcard' AND s.fag = ? AND (? IS NULL OR s.tema = ?)"
        " ORDER BY s.id",
        (fag, tema, tema),
    ).fetchall()


def resultater(db, fag: str | None = None) -> list[sqlite3.Row]:
    """Antall forsøk og riktige per fag og tema."""
    return db.execute(
        "SELECT s.fag, s.tema, COUNT(*) AS forsok, SUM(f.riktig) AS riktige, MAX(f.tidspunkt) AS sist"
        " FROM forsok f JOIN sporsmal s ON s.id = f.sporsmal_id"
        " WHERE (? IS NULL OR s.fag = ?) GROUP BY s.fag, s.tema ORDER BY s.fag, sist DESC",
        (fag, fag),
    ).fetchall()
