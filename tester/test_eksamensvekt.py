"""Quizen velger eksamensrelevante modeller først og gjentar ikke det du nettopp har øvd på (src/eksamensvekt.py)."""

import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

import src.database
from src import eksamensvekt
from src.database import koble, lagre_forsok, lagre_sporsmal
from src.henting import Bit
from src.modellquiz import BLANDET, modell_strom
from src.modeller import modeller
from src.signaler import tilfeldig_bedrift


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(src.database, "data_mappe", lambda: tmp_path)
    return koble()


def test_modeller_fra_eksamen_veier_mer_enn_modeller_som_aldri_har_kommet():
    porter = eksamensvekt.modellvekt("MRK1001", "Porters bransjeanalyse (fem krefter, utvidet)")
    kohli = eksamensvekt.modellvekt("MRK1001", "Markedsorientering (Kohli og Jaworski)")
    assert porter >= 3 and kohli == eksamensvekt.ALDRI_PAA_EKSAMEN
    assert eksamensvekt.modellvekt("MRK1001", "BCG-matrisen") == eksamensvekt.ALDRI_PAA_EKSAMEN


def test_vektet_rekkefolge_tar_med_alt_og_setter_tunge_forst():
    ting = list(range(10))
    forst = Counter(eksamensvekt.vektet_rekkefolge(ting, lambda t: 20 if t == 7 else 1, random.Random(s))[0]
                    for s in range(200))
    assert forst[7] > 100
    assert sorted(eksamensvekt.vektet_rekkefolge(ting, lambda t: 1, random.Random(0))) == ting


def test_modellstrommen_starter_oftest_med_eksamensmodeller():
    navn = {m.navn for m in modeller("MRK1001")}
    eksamen = {n for n in navn if eksamensvekt.modellvekt("MRK1001", n) > 1}
    forste = [next(modell_strom("MRK1001", None, "kjenn", 1, random.Random(s)))[2].navn for s in range(40)]
    assert sum(n in eksamen for n in forste) >= 30, "minst tre av fire økter bør starte med en eksamensmodell"


def test_mestrede_modeller_skyves_bak():
    m_kap12 = [m for m in modeller("MRK1001") if m.kapittel == 12]
    oliver = next(m for m in m_kap12 if m.navn.startswith("Fire nivåer av lojalitet"))
    forste = Counter()
    for s in range(60):
        rekke = [m.navn for _, _, m in modell_strom("MRK1001", "kap. 12", "kjenn", 3, random.Random(s),
                                                    mestret={oliver.tekst})]
        forste[rekke[0]] += 1
    uten = Counter(next(modell_strom("MRK1001", "kap. 12", "kjenn", 1, random.Random(s)))[2].navn for s in range(60))
    assert forste[oliver.navn] < uten[oliver.navn]


def test_nylig_ovd_skiller_riktig_svar_og_bare_stilt(db):
    riktig = lagre_sporsmal(db, fag="MRK1001", tema="t", ovingsmate="flervalg", sporsmal="A?", fasit="a",
                            kilde="k", kildetekst="tekst A")
    lagre_sporsmal(db, fag="MRK1001", tema="t", ovingsmate="flervalg", sporsmal="B?", fasit="b", kilde="k",
                   kildetekst="tekst B")
    lagre_sporsmal(db, fag="ORG1100", tema="t", ovingsmate="flervalg", sporsmal="C?", fasit="c", kilde="k",
                   kildetekst="tekst C")
    lagre_forsok(db, riktig, "a", True)
    mestret, stilt = eksamensvekt.nylig_ovd(db, "MRK1001")
    assert mestret == {"tekst A"} and stilt == {"tekst A", "tekst B"}
    om_en_maaned = datetime.now() + timedelta(days=30)
    assert eksamensvekt.nylig_ovd(db, "MRK1001", om_en_maaned) == (set(), set())
    assert set(eksamensvekt.nylige_sporsmal(db, "MRK1001")) == {"A? a", "B? b"}


def test_kandidatbiter_som_er_mestret_havner_bak(monkeypatch):
    from src import quiz
    biter = [Bit(f"bit {i} " + "x" * 400, {"fil": f"notater/{i}.docx"}, 0.1) for i in range(6)]
    monkeypatch.setattr(quiz, "hent", lambda *a, **k: biter)
    forst = Counter(quiz.kandidat_biter("MRK1001", "t", 2, mestret={biter[0].tekst}, rng=random.Random(s))[0].tekst
                    for s in range(100))
    assert forst[biter[0].tekst] < 15
    assert quiz.kandidat_biter("MRK1001", "t", 2) == biter, "uten rng er rekkefølgen som før (flashcards)"


def test_blandet_er_mest_case():
    assert BLANDET.count("kjenn") < len(BLANDET) / 2


def test_casene_faar_ulike_bedrifter():
    rng = random.Random(0)
    navn = {tilfeldig_bedrift(rng)[0] for _ in range(30)}
    assert len(navn) >= 20 and sum(n.startswith("Fjord") for n in navn) <= 5
