"""Tester for planleggeren (SPEC.md: «sum av planlagte timer overstiger aldri tilgjengelige timer,
og ingen dag ligger etter eksamensdatoen»).

Kjør:  uv run pytest tester/ -v
"""

from collections import Counter, defaultdict
from datetime import date, timedelta

from src.planlegger import fordel_heltall, last_eksamener, lag_plan, ovingsmate_for, sjekk_plan

START = date(2026, 10, 30)
EKSAMENER = {"A": date(2026, 11, 23), "B": date(2026, 12, 15), "C": date(2027, 1, 7)}
TEMAER = {"A": [f"a{i}" for i in range(15)], "B": [f"b{i}" for i in range(16)], "C": [f"c{i}" for i in range(11)]}
TIMER = 6
BLOKK = 45


def plan(**kwargs):
    return lag_plan(EKSAMENER, TEMAER, START, TIMER, BLOKK, repetisjonsdager=2, **kwargs)


def per_dag(blokker):
    dager = defaultdict(list)
    for b in blokker:
        dager[b.dato].append(b)
    return dager


def test_aldri_over_timegrensen():
    for dag, blokker in per_dag(plan()).items():
        assert sum(b.minutter for b in blokker) <= TIMER * 60, dag


def test_ingen_blokk_paa_eller_etter_eksamen():
    for b in plan():
        assert b.dato < EKSAMENER[b.fag], b


def test_sjekk_plan_finner_ingen_problemer():
    assert sjekk_plan(plan(), EKSAMENER, TEMAER, TIMER) == []


def test_alle_temaer_dekkes_for_eksamen():
    dekket = {(b.fag, b.tema) for b in plan()}
    for fag, liste in TEMAER.items():
        assert all((fag, t) in dekket for t in liste), fag


def test_naermeste_eksamen_faar_mest_tid_naa():
    forste_uke = [b for b in plan() if b.dato < START + timedelta(days=7)]
    tid = Counter(b.fag for b in forste_uke)
    assert tid["A"] > tid["B"] > tid["C"]


def test_repetisjonsdager_brukes_bare_paa_ett_fag():
    for dag, blokker in per_dag(plan()).items():
        for fag, eksamen in EKSAMENER.items():
            if 0 < (eksamen - dag).days <= 2:
                assert {b.fag for b in blokker} == {fag}, dag


def test_hoppet_over_dag_faar_ingen_blokker_og_temaene_flyttes():
    vanlig = plan()
    med_hopp = plan(hoppes_over={START})
    assert not [b for b in med_hopp if b.dato == START]
    # Det som skulle vært gjort den hoppede dagen, kommer i løpet av de to neste dagene.
    skulle_gjort = {(b.fag, b.tema) for b in vanlig if b.dato == START}
    neste_dager = {(b.fag, b.tema) for b in med_hopp if b.dato <= START + timedelta(days=2)}
    assert skulle_gjort <= neste_dager
    # Én dag færre å planlegge på, og ingen dag over timegrensen.
    assert len(per_dag(med_hopp)) == len(per_dag(vanlig)) - 1
    assert sjekk_plan(med_hopp, EKSAMENER, TEMAER, TIMER) == []


def test_svake_temaer_faar_flere_blokker():
    mestring = {("A", "a0"): 0.1, ("A", "a1"): 0.95}
    antall = Counter(b.tema for b in plan(mestring=mestring) if b.fag == "A")
    assert antall["a0"] > antall["a1"]


def test_temaer_du_har_ovd_paa_nylig_kommer_senere():
    sist_ovd = {("A", "a0"): START - timedelta(days=1)}
    forste_dag = [b.tema for b in plan(sist_ovd=sist_ovd) if b.dato == START and b.fag == "A"]
    assert "a0" not in forste_dag


def test_fordel_heltall_summerer_riktig():
    assert sum(fordel_heltall({"A": 0.53, "B": 0.28, "C": 0.19}, 8).values()) == 8
    assert fordel_heltall({"A": 0.5, "B": 0.5}, 8) == {"A": 4, "B": 4}


def test_ovingsmate_blir_vanskeligere_mot_eksamen():
    assert [ovingsmate_for(d, 2) for d in (30, 14, 5, 1)] == ["flashcards", "flervalg", "kortsvar", "repetisjon"]


def test_tidlig_fase_veksler_mellom_flashcards_og_flervalg():
    modus_c = [b.ovingsmate for b in plan() if b.fag == "C" and b.dato < START + timedelta(days=14)]
    assert {"flashcards", "flervalg"} <= set(modus_c)


def test_din_egen_plan_er_gyldig():
    """Samme kontroll på config/eksamener.yaml, slik den ser ut nå."""
    eksamener, temaer, innst = last_eksamener()
    din_plan = lag_plan(eksamener, temaer, START, innst["timer_per_dag"], innst["blokk_minutter"],
                        innst["repetisjonsdager"])
    assert sjekk_plan(din_plan, eksamener, temaer, innst["timer_per_dag"]) == []
