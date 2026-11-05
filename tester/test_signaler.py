"""Finn modellene (src/signaler.py): fasit fra løsningsforslagene, aldri tvil om hva som er riktig."""

import random

import pytest

from src.modellquiz import rett_avkrysning
from src.signaler import (caser, casetekst, er_modellvalg, fasit_for_case, godkjent, krav, lag_finn, lag_signal,
                          signal_strom, signaler)

FAG = "MRK1001"
ALLE_CASER = [(fag, navn) for fag in ("MRK1001", "ORG1100") for navn in caser(fag)]


@pytest.mark.parametrize("fag,navn", ALLE_CASER)
def test_hver_case_har_fasit_og_lesbar_tekst(fag, navn):
    riktige, _ = fasit_for_case(fag, navn)
    assert len(riktige) >= 3, navn
    tekst = casetekst(fag, navn)
    assert "\ufffd" not in tekst, "ødelagte bokstaver fra PDF-en"
    assert len(tekst.split()) > 500 and "NUMPAGES" not in tekst
    avsnitt = [a for a in tekst.split("\n\n") if len(a) > 80]
    assert len(avsnitt) == len(set(avsnitt)), "avsnitt som står to ganger skal bare tas med én gang"


@pytest.mark.parametrize("fag,navn", ALLE_CASER)
def test_finn_gale_alternativer_er_aldri_i_fasiten(fag, navn):
    for seed in range(5):
        q = lag_finn(fag, navn, random.Random(seed))
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
    assert len(list(signal_strom(FAG, None, "finn", 10, random.Random(0)))) == len(caser(FAG))


@pytest.mark.parametrize("fag", ["MRK1001", "ORG1100"])
def test_sitatene_staar_ordrett_i_casen(fag):
    """Signalarket viser sitatet som bevis. Det må stå i casen, ikke være omskrevet."""
    import re
    vask = lambda s: re.sub(r"\s+", " ", s).strip()
    sjekket = 0
    for s in signaler(fag):
        if s.sitat and s.sitat_fra in caser(fag):
            assert vask(s.sitat) in vask(casetekst(fag, s.sitat_fra)), (s.sitat_fra, s.sitat)
            sjekket += 1
    assert sjekket >= 10


def test_org_schjodt_bruker_sensorveiledningen():
    riktige, _ = fasit_for_case("ORG1100", "Schjødt")
    for m in ("Situasjonsbestemt ledelse (Hersey og Blanchard)", "Forventningsteori (Vroom)", "Herzbergs tofaktorteori"):
        assert m in riktige
    assert "Oppgave 2 (60 %)" in casetekst("ORG1100", "Schjødt")


@pytest.mark.parametrize("fag", ["MRK1001", "ORG1100"])
def test_signalarket_viser_sitat_modell_og_kilde(fag):
    from src.signaler import signalark
    ark = signalark(fag)
    s = next(s for s in signaler(fag) if s.sitat and s.modeller)
    assert s.sitat.strip("«»") in ark and s.modeller[0] in ark and "Oppslag per modell" in ark


def test_signalarket_for_ett_kapittel_viser_bare_det_kapittelet():
    from src.signaler import signalark
    ark = signalark("ORG1100", 14)
    assert "Competing Values Framework" in ark and "Forventningsteori" not in ark.split("### Oppslag per modell")[1]
