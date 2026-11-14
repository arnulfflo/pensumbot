"""Feil som ble funnet i gjennomgangen 14.11.2026: appen skal si fra i stedet for å henge, og bare
spørsmål du faktisk har fått se, skal telle som stilt."""

import queue
import random
from datetime import date, timedelta

import pytest

import src.database
from src import app, eksamensvekt, llm, modellquiz
from src.database import koble, lagre_sporsmal
from src.henting import Bit
from src.modeller import modeller
from src.planlegger import lag_og_lagre, last_eksamener
from src.repetisjon import MODELLARK, lagre_resultat, mestring_per_tema


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(src.database, "data_mappe", lambda: tmp_path)
    return koble()


def test_ollama_som_ikke_svarer_gir_en_feil_appen_kan_vise():
    feil = llm._ollama_feil(ConnectionError("nektet"), "gemma")
    assert isinstance(feil, llm.SprakmodellFeil) and "Start Ollama" in str(feil)
    assert not isinstance(feil, SystemExit), "SystemExit i en bakgrunnstråd forsvinner uten spor"


@pytest.mark.parametrize("feil", [llm.SprakmodellFeil("Start Ollama-appen"), SystemExit("gammel feil"), KeyError("x")])
def test_quizen_henger_ikke_naar_sporsmalene_ikke_kan_lages(monkeypatch, feil):
    def strom(*a):
        raise feil
        yield
    monkeypatch.setattr(app, "_ny_strom", strom)
    okt = app._start_okt("MRK1001", "pris", "flervalg", "forklar")
    try:
        assert okt["ko"].get(timeout=8) is app.SLUTT
    except queue.Empty:
        pytest.fail("køen fikk aldri beskjed, så «Nytt spørsmål» ville ventet for alltid")
    assert okt["feilmelding"]
    if isinstance(feil, llm.SprakmodellFeil):
        assert okt["feilmelding"] == "Start Ollama-appen"


def test_sporsmal_lagres_forst_naar_de_vises(db, monkeypatch):
    bit = Bit("kildetekst " * 40, {"fil": "notater/kap 6.docx"}, 0.1)
    q = {"sporsmal": "Hva er segmentering?", "alternativer": ["a", "b", "c", "d"], "fasit": "a",
         "forklaring": "f", "sitat": "s"}
    monkeypatch.setattr(app, "sporsmal_strom", lambda *a, **k: iter([(q, bit), ({**q, "sporsmal": "Hva er STP?"}, bit)]))
    elementer = list(app._ny_strom("MRK1001", "segmentering", "flervalg", "forklar"))
    antall = lambda: db.execute("SELECT COUNT(*) FROM sporsmal").fetchone()[0]
    assert len(elementer) == 2 and antall() == 0, "laget på forhånd, men ikke vist: skal ikke ligge i databasen"

    okt = {"nr": 0, "feil": [], "besvart": 0, "riktige": 0}
    app._vis(okt, "MRK1001", elementer[0])
    assert antall() == 1 and isinstance(okt["sid"], int)
    assert eksamensvekt.nylige_sporsmal(db, "MRK1001") == ["Hva er segmentering? a"]


def test_riktig_paa_kjenn_teller_bare_som_stilt(db):
    kjenn = lagre_sporsmal(db, fag="MRK1001", tema="t", ovingsmate="flervalg", sporsmal="Hvilken modell?", fasit="Porter",
                           kilde="k", kildetekst="Porter-teksten", modell=MODELLARK)
    case = lagre_sporsmal(db, fag="MRK1001", tema="t", ovingsmate="kortsvar", sporsmal="Analyser casen", fasit="svar",
                          kilde="k", kildetekst="SWOT-teksten", modell="gemma")
    lagre_resultat(db, kjenn, "Porter", True)
    lagre_resultat(db, case, "svar", True)
    om_fire_dager = eksamensvekt.datetime.now() + timedelta(days=4)      # ikke lenger «stilt de siste 3 dagene»
    mestret, stilt = eksamensvekt.nylig_ovd(db, "MRK1001", om_fire_dager)
    assert mestret == {"SWOT-teksten"}, "bare casen viser at du kan bruke modellen"
    assert stilt == {"Porter-teksten"}, "kjenn-spørsmålet skyver modellen litt bak, men ikke bort"


def test_blandet_gir_case_for_modeller_uten_kjenn_sporsmal(monkeypatch):
    alle = list(modeller("MRK1001"))
    uten = next(m for m in alle if m.navn.startswith("Tre delsystemer"))
    assert all(modellquiz.lag_kjenn(uten, alle, random.Random(s)) is None for s in range(5))
    case = lambda m, *a: ({"sporsmal": "case", "stil": "velg modell", "type": "flervalg", "modell_id": m.id}, "")
    monkeypatch.setattr(modellquiz, "lag_velg", case)
    monkeypatch.setattr(modellquiz, "lag_bruk", lambda m, *a: case(m))
    tema = f"kap. {uten.kapittel}"
    for s in range(8):
        navn = [m.navn for _, _, m in modellquiz.modell_strom("MRK1001", tema, "blandet", 99, random.Random(s))]
        assert uten.navn in navn, "modellen er blant de vanligste på eksamen og skal ikke hoppes over"


def test_planen_ser_hva_du_har_ovd_paa_uten_ferdig_knappen(db):
    eksamener, temaer, _ = last_eksamener()
    fag = min(eksamener, key=eksamener.get)
    forste = temaer[fag][0]
    i_morgen = date.today() + timedelta(days=1)
    if eksamener[fag] <= i_morgen + timedelta(days=1):
        pytest.skip("eksamen er for nær til å teste planen")
    plan, _ = lag_og_lagre(db, i_morgen)
    assert next(b.tema for b in plan if b.fag == fag) == forste

    sid = lagre_sporsmal(db, fag=fag, tema=forste, ovingsmate="flervalg", sporsmal="?", fasit="a", kilde="k")
    lagre_resultat(db, sid, "a", True)                # øvd i quizen i dag, uten å trykke «Ferdig»
    plan, _ = lag_og_lagre(db, i_morgen)
    assert next(b.tema for b in plan if b.fag == fag) != forste, "temaet du øvde på i dag, skal ikke komme først i morgen"


def test_temaer_uten_forsok_regnes_ikke_som_ovd(db):
    db.execute("INSERT INTO temaer (fag, tema, mestring, forsok, sist_ovd) VALUES ('MRK1001', 'tomt tema', 0.5, 0, NULL)")
    db.commit()
    assert mestring_per_tema(db) == {}


def test_forbrukermodeller_faar_en_forbrukerbransje():
    from src.signaler import FORBRUKERBRANSJER, tilfeldig_bedrift
    alle = list(modeller("MRK1001"))
    ekb = next(m for m in alle if m.navn.startswith("EKB-modellen"))
    hollensen = next(m for m in alle if m.kapittel == 5)
    assert modellquiz.gjelder_forbrukere(ekb) and not modellquiz.gjelder_forbrukere(hollensen)
    rng = random.Random(0)
    assert all(tilfeldig_bedrift(rng, forbruker=True)[1] in FORBRUKERBRANSJER for _ in range(40))
