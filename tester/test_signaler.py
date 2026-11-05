"""Finn modellene (src/signaler.py): fasit fra løsningsforslagene, aldri tvil om hva som er riktig."""

import random

import pytest

from src.modellquiz import rett_avkrysning
from src.signaler import (CASER, casetekst, er_modellvalg, fasit_for_case, godkjent, krav, lag_finn, lag_signal,
                          signal_strom, signaler)

FAG = "MRK1001"


@pytest.mark.parametrize("navn", list(CASER[FAG]))
def test_hver_case_har_fasit_og_lesbar_tekst(navn):
    riktige, _ = fasit_for_case(FAG, navn)
    assert len(riktige) >= 5, navn
    tekst = casetekst(FAG, navn)
    assert len(tekst.split()) > 500 and "NUMPAGES" not in tekst
    avsnitt = [a for a in tekst.split("\n\n") if len(a) > 80]
    assert len(avsnitt) == len(set(avsnitt)), "avsnitt som står to ganger skal bare tas med én gang"


@pytest.mark.parametrize("navn", list(CASER[FAG]))
def test_finn_gale_alternativer_er_aldri_i_fasiten(navn):
    for seed in range(5):
        q = lag_finn(FAG, navn, random.Random(seed))
        assert er_modellvalg(q) and q["type"] == "avkrysning"
        assert set(q["fasit"]) <= set(q["alternativer"])
        assert len(q["alternativer"]) == len(set(q["alternativer"]))
        assert len(q["alternativer"]) - len(q["fasit"]) >= 4, "for få gale gjør det lett å krysse av for alt"


def test_kari_traa_ansoff_er_en_felle():
    """Løsningsforslaget: «Ansoff vekstmatrise er ikke relevant»."""
    riktige, feller = fasit_for_case(FAG, "Kari Traa")
    assert "Ansoffs ekspansjonsmatrise" not in riktige
    assert "ikke relevant" in feller["Ansoffs ekspansjonsmatrise"].hvorfor
    q = lag_finn(FAG, "Kari Traa", random.Random(1))
    assert "Ansoffs ekspansjonsmatrise" in q["alternativer"]
    assert not rett_avkrysning(q, q["fasit"] + ["Ansoffs ekspansjonsmatrise"])[0]


def test_signalsporsmaal_har_entydig_fasit():
    for i, s in enumerate(signaler(FAG)):
        q = lag_signal(FAG, s, random.Random(i))
        if s.type == "ikke":
            assert q is None
            continue
        assert er_modellvalg(q) and set(q["fasit"]) == set(s.modeller)
        assert set(q["fasit"]) <= set(q["alternativer"]) and len(q["alternativer"]) - len(q["fasit"]) >= 3


def test_kravet_er_halvparten_men_aldri_mer_enn_seks():
    assert krav(1) == 1 and krav(3) == 2 and krav(4) == 2 and krav(21) == 6
    assert godkjent(21, 6, 0) and not godkjent(21, 5, 0) and not godkjent(21, 21, 1)


def test_aa_krysse_av_for_alt_gir_ikke_godkjent():
    q = lag_finn(FAG, "Spike", random.Random(0))
    assert not rett_avkrysning(q, q["alternativer"])[0]
    assert rett_avkrysning(q, q["fasit"][:6])[0]


def test_elementspoersmaal_krever_fortsatt_alle():
    q = {"sporsmal": "Hvilke av disse er elementer i «X»? Kryss av for alle som hører til.", "fasit": ["a", "b", "c"]}
    assert not rett_avkrysning(q, ["a", "b"])[0]


def test_strommen_holder_seg_til_kapittelet():
    from src.modeller import modeller
    kap = {m.navn: m.kapittel for m in modeller(FAG)}
    qs = list(signal_strom(FAG, "kap. 12", "signal", 20, random.Random(0)))
    assert qs and all(any(kap[n] == 12 for n in q["fasit"]) and m.kapittel == 12 for q, m in qs)
    assert len(list(signal_strom(FAG, None, "finn", 10, random.Random(0)))) == len(CASER[FAG])
