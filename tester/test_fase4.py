"""Tester for fase 4 mot en midlertidig database (din egen data/studie.db brukes ikke).

SPEC.md, ferdig når: «et tema jeg feiler på, dukker opp oftere i planen uken etter».

Kjør:  uv run pytest tester/ -v
"""

from datetime import date, datetime, timedelta

import pytest

import src.database
from src.database import koble, lagre_sporsmal
from src.planlegger import lag_og_lagre
from src.repetisjon import forfalte_sporsmal, lagre_resultat, mestring_per_tema

START = date(2026, 10, 30)
TEMA = "Prispolitikk (kap. 9)"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(src.database, "data_mappe", lambda: tmp_path)
    return koble()


def nytt_sporsmal(db, tema=TEMA, ovingsmate="flervalg"):
    return lagre_sporsmal(db, fag="MRK1001", tema=tema, ovingsmate=ovingsmate, sporsmal="?",
                          fasit="svar", kilde="MRK1001/notater/kap 9.docx")


def blokker_neste_uke(db, tema):
    return db.execute("SELECT COUNT(*) FROM plan WHERE fag = 'MRK1001' AND tema = ? AND dato BETWEEN ? AND ?",
                      (tema, START.isoformat(), (START + timedelta(days=6)).isoformat())).fetchone()[0]


def test_tema_du_feiler_paa_kommer_oftere_uken_etter(db):
    lag_og_lagre(db, START)
    for_ = blokker_neste_uke(db, TEMA)

    for _ in range(3):
        lagre_resultat(db, nytt_sporsmal(db), svar="feil", riktig=False)
    assert mestring_per_tema(db)[("MRK1001", TEMA)] < 0.25

    lag_og_lagre(db, START)
    etter = blokker_neste_uke(db, TEMA)
    assert etter > for_, f"{TEMA}: {for_} blokker før, {etter} etter tre feil"


def test_tema_du_kan_godt_kommer_sjeldnere(db):
    lag_og_lagre(db, START)
    for_ = blokker_neste_uke(db, TEMA)
    for _ in range(4):
        lagre_resultat(db, nytt_sporsmal(db), svar="riktig", riktig=True)
    lag_og_lagre(db, START)
    assert blokker_neste_uke(db, TEMA) <= for_


def _dager_til(neste: datetime) -> float:
    return (neste - datetime.now()).total_seconds() / 86400


def _gjor_forfalt(db, sporsmal_id):
    """Late som om tiden har gått: flytt siste forsøk så spørsmålet er forfalt nå."""
    rad = db.execute("SELECT id, tidspunkt, neste_repetisjon FROM forsok WHERE sporsmal_id = ? ORDER BY id DESC LIMIT 1",
                     (sporsmal_id,)).fetchone()
    intervall = datetime.fromisoformat(rad["neste_repetisjon"]) - datetime.fromisoformat(rad["tidspunkt"])
    naa = datetime.now()
    db.execute("UPDATE forsok SET tidspunkt = ?, neste_repetisjon = ? WHERE id = ?",
               ((naa - intervall).isoformat(timespec="seconds"), naa.isoformat(timespec="seconds"), rad["id"]))
    db.commit()


def test_feilsvar_kommer_igjen_etter_1_3_og_7_dager(db):
    sid = nytt_sporsmal(db)
    neste = lagre_resultat(db, sid, "feil", riktig=False)
    assert round(_dager_til(neste)) == 1
    assert sid not in [s["id"] for s in forfalte_sporsmal(db)]     # ikke forfalt før det har gått en dag

    for forventet in (3, 7):
        _gjor_forfalt(db, sid)
        assert sid in [s["id"] for s in forfalte_sporsmal(db)]
        neste = lagre_resultat(db, sid, "riktig", riktig=True)
        assert round(_dager_til(neste)) == forventet


def test_feil_igjen_starter_paa_nytt(db):
    sid = nytt_sporsmal(db)
    lagre_resultat(db, sid, "feil", riktig=False)
    _gjor_forfalt(db, sid)
    lagre_resultat(db, sid, "riktig", riktig=True)        # nå 3 dager
    _gjor_forfalt(db, sid)
    neste = lagre_resultat(db, sid, "feil", riktig=False)
    assert round(_dager_til(neste)) == 1


def test_riktig_forste_gang_kommer_ikke_i_repetisjonskoen(db):
    sid = nytt_sporsmal(db)
    assert lagre_resultat(db, sid, "riktig", riktig=True) is None
    assert sid not in [s["id"] for s in forfalte_sporsmal(db)]


def test_flashcard_intervall_vokser(db):
    kid = nytt_sporsmal(db, ovingsmate="flashcard")
    intervaller = []
    for _ in range(3):
        neste = lagre_resultat(db, kid, "greit", riktig=True, vurdering="greit")
        intervaller.append(_dager_til(neste))
        _gjor_forfalt(db, kid)
    assert intervaller == pytest.approx([3, 7.5, 18.75], abs=0.01)    # 3 × 2,5 × 2,5


def test_angre_hopp_over_gir_dagen_tilbake(db):
    from src.planlegger import angre_hopp_over, blokker_for, hopp_over
    i_dag = date.today()
    lag_og_lagre(db, i_dag)
    for_ = [(b["fag"], b["tema"]) for b in blokker_for(db, i_dag)]
    hopp_over(db, i_dag)
    assert all(b["status"] == "hoppet_over" for b in blokker_for(db, i_dag))
    angre_hopp_over(db, i_dag)
    etter = blokker_for(db, i_dag)
    assert [(b["fag"], b["tema"]) for b in etter] == for_
    assert all(b["status"] == "planlagt" for b in etter)


def test_sikkerhetskopi_en_per_dag_og_bare_de_nyeste(db, tmp_path):
    from src.database import SIKKERHETSKOPIER, ta_sikkerhetskopi
    mappe = tmp_path / "sikkerhetskopi"
    dagens = mappe / f"studie-{date.today():%Y-%m-%d}.db"
    assert dagens.exists()                                   # koble() tok kopi
    nytt_sporsmal(db)
    assert ta_sikkerhetskopi(db) is None                     # bare én per dag
    for i in range(1, 20):                                   # eldre kopier fra tidligere dager
        (mappe / f"studie-{date.today() - timedelta(days=i):%Y-%m-%d}.db").touch()
    dagens.unlink()
    assert ta_sikkerhetskopi(db) == dagens                   # ny dag: ny kopi, og de eldste slettes
    filer = sorted(mappe.glob("studie-*.db"))
    assert len(filer) == SIKKERHETSKOPIER and filer[-1] == dagens


def test_avkrysning_kommer_igjen_i_repetisjonen(db, monkeypatch):
    """Feil 05.11.2026: «Finn modellene» og «kryss av for alle elementene» sa «Kommer igjen for repetisjon»,
    men repetisjonen hentet bare flervalg og kortsvar."""
    import json
    import random
    from src.app import _repetisjonsstrom
    from src.modellquiz import rett_avkrysning
    from src.repetisjon import MODELLARK
    from src.signaler import krav, lag_finn
    q = lag_finn("ORG1100", "Easee", random.Random(0))
    sid = lagre_sporsmal(db, fag="ORG1100", tema="Organisasjonskultur (kap. 14)", ovingsmate="avkrysning",
                         sporsmal=q["sporsmal"], alternativer=q["alternativer"],
                         fasit=json.dumps(q["fasit"], ensure_ascii=False), forklaring=q["forklaring"], sitat="",
                         kilde="x", modell=MODELLARK, kildetekst="")
    lagre_resultat(db, sid, "[]", riktig=False)
    _gjor_forfalt(db, sid)
    assert sid in [s["id"] for s in forfalte_sporsmal(db)]
    import src.app
    monkeypatch.setattr(src.app, "koble", lambda: db)
    r, _, rid, _ = next(e for e in _repetisjonsstrom("ORG1100") if e[2] == sid)
    assert r["type"] == "avkrysning" and r["fag"] == "ORG1100" and set(r["fasit"]) == set(q["fasit"])
    assert rett_avkrysning(r, r["fasit"][:krav(len(r["fasit"]))])[0]       # samme retting som første gang
