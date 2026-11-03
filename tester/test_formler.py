"""Tester for BØA-formlene: at hver formel, hver omforming og hver fasit regner riktig.

Kjør:  uv run pytest tester/test_formler.py -v
"""

import random
import re
import unicodedata
from pathlib import Path

import pytest
import sympy as sp

from src.formler import (FORMEL, FORMLER, S, TYPER, VARIABLER, kjeder, lag_hva_skjer, les_tall, losninger,
                         ny_oppgave, omforminger, sjekk, skriv, verdier_for)

PENSUM = Path(__file__).parent.parent / "pensum" / "BOA1100"


@pytest.mark.parametrize("f", FORMLER, ids=lambda f: f.id)
def test_kilden_finnes(f):
    fil = unicodedata.normalize("NFC", f.kilde.split(", s.")[0])
    filer = {unicodedata.normalize("NFC", str(p.relative_to(PENSUM))) for p in PENSUM.rglob("*")}
    assert fil in filer


@pytest.mark.parametrize("f", [f for f in FORMLER if f.regnes], ids=lambda f: f.id)
def test_tallene_gaar_opp_og_hver_omforming_stemmer(f):
    rng = random.Random(1)
    for _ in range(20):
        verdier = verdier_for(f, rng)
        assert verdier, f"{f.id}: fant ingen pene tall"
        sett_inn = {S[k]: v for k, v in verdier.items()}
        assert float(f.rhs.subs(sett_inn)) == pytest.approx(verdier[f.lhs])
        for mal, _ in omforminger(f):
            assert float(losninger(f, mal).subs(sett_inn)) == pytest.approx(verdier[mal]), f"{f.id} løst for {mal}"


def test_formlene_skrives_som_i_pensum():
    assert skriv(FORMEL["pris_dg"].rhs) == "VEK/(1 − DG)"
    assert skriv(losninger(FORMEL["sm"], "OMS")) == "NPO/(1 − SM)"
    assert skriv(losninger(FORMEL["pris_dg"], "VEK")) == "pris · (1 − DG)"
    assert skriv(losninger(FORMEL["pris_dg"], "DG")) == "(pris − VEK)/pris"
    assert skriv(FORMEL["mo"].rhs) == "(FK + MR)/DG"
    assert skriv(losninger(FORMEL["nnv"], "I0")) == "X1/(1 + r) + X2/(1 + r)^2 − NNV"


@pytest.mark.parametrize("type_", list(TYPER))
def test_tilfeldige_oppgaver_har_riktig_fasit(type_):
    rng = random.Random(7)
    for _ in range(60):
        o = ny_oppgave(type_, rng=rng)
        assert o.kilder and o.forklaring
        if o.tallsvar:
            assert sjekk(o, str(o.fasit))
            assert not sjekk(o, str(o.fasit + abs(o.fasit) * 0.5 + 1))
        else:
            assert o.fasit in o.alternativer
            assert len(set(o.alternativer)) == len(o.alternativer) == (3 if type_ == "hva_skjer" else 4)
            assert sjekk(o, o.fasit)


def test_gale_alternativer_er_virkelig_gale():
    rng = random.Random(3)
    for _ in range(80):
        o = ny_oppgave("snu", rng=rng)
        riktig = sp.sympify(o.fasit.split(" = ")[1].replace("−", "-").replace("·", "*").replace("^", "**"), locals=S)
        for alt in o.alternativer:
            if alt != o.fasit:
                feil = sp.sympify(alt.split(" = ")[1].replace("−", "-").replace("·", "*").replace("^", "**"), locals=S)
                assert sp.simplify(feil - riktig) != 0, alt


def test_sammenhenger_paa_tvers():
    rekker = {tuple(f.id for f in k) for k in kjeder()}
    assert ("db", "dg", "npo") in rekker                  # pris og VEK → DB → DG → NPO
    assert ("npo", "sm") in rekker
    assert ("pris_paslag", "mva") in rekker


def test_hva_skjer_gir_riktig_retning():
    kjede = [FORMEL["db"], FORMEL["dg"], FORMEL["npo"]]
    sett = {}
    for frø in range(200):
        o = lag_hva_skjer(kjede, random.Random(frø))
        hva = re.search(r"\((\w+)\) øker", o.tekst).group(1)
        sett[hva] = o.fasit
    assert sett == {"pris": "synker", "VEK": "øker", "FK": "øker"}   # høyere VEK gir lavere DG og høyere nullpunkt


@pytest.mark.parametrize("tekst, mal, verdi", [
    ("750 000", "NPO", 750_000), ("kr 750 000", "NPO", 750_000), ("40 %", "DG", 0.4), ("40", "DG", 0.4),
    ("0,4", "DG", 0.4), ("−2,5", "EP", -2.5), ("1.500,5", "NPO", 1500.5), ("tull", "DG", None),
])
def test_leser_svaret_ditt(tekst, mal, verdi):
    assert les_tall(tekst, mal) == (pytest.approx(verdi) if verdi is not None else None)


def test_alle_variabler_har_forklaring():
    brukt = {v for f in FORMLER for v in f.variabler}
    assert brukt <= set(VARIABLER)
