"""Tester for kalkulatoren i BØA-agenten (uten språkmodell).

Kjør:  uv run pytest tester/test_agent.py -v
"""

import pytest

from src.agent import regn, tall_som_tekst


@pytest.mark.parametrize("uttrykk, svar", [
    ("450000 / (250 - 130)", 3750),
    ("450 000 / (250 - 130)", 3750),          # norsk tusenskille
    ("1,5 * 4", 6),                           # desimalkomma
    ("25 % * 800", 200),                      # prosent
    ("-(3 - 5) ** 2", -4),
    ("1000 * 1.05 ** 2", 1102.5),
])
def test_regner_riktig(uttrykk, svar):
    assert regn(uttrykk) == pytest.approx(svar)


@pytest.mark.parametrize("farlig", [
    "__import__('os').system('ls')",
    "open('/etc/passwd')",
    "2 ** 10000",
    "abc + 1",
])
def test_kjorer_aldri_kode(farlig):
    with pytest.raises((ValueError, SyntaxError)):
        regn(farlig)


def test_tall_som_tekst():
    assert tall_som_tekst(3750.0) == "3 750"
    assert tall_som_tekst(0.416666) == "0,4167"


def test_finner_tall_som_ikke_kommer_fra_kalkulatoren():
    from src.agent import Agentsvar, Steg, ukjente_tall
    svar = Agentsvar("Direkte material 120 kr og direkte lønn 80 kr, påslag 15 % og 50 %.", "",
                     steg=[Steg("regn_ut", "120 * 0.15", "120 * 0.15 = 18"), Steg("regn_ut", "80 * 0.5", "80 * 0.5 = 40")])
    assert ukjente_tall(svar, "Tilvirkningskost: 120 + 80 + 18 + 40 = 258 kr [1].") == [258]
    svar.steg.append(Steg("regn_ut", "120 + 80 + 18 + 40", "120 + 80 + 18 + 40 = 258"))
    assert ukjente_tall(svar, "Tilvirkningskost: 120 + 80 + 18 + 40 = 258 kr [1].") == []
    assert ukjente_tall(Agentsvar("pris 400, DB 150", "", steg=[Steg("regn_ut", "150/400", "150/400 = 0,375")]),
                        "Dekningsgraden er 0,375, altså 37,5 %.") == []


def test_kontrollregning_finner_regnefeil():
    from src.agent import Agentsvar, kontrollregn, ukjente_tall
    svar = Agentsvar("Faste kostnader 600 000, pris 400, variable 250.", "")
    assert kontrollregn(svar, "Utregning: 600000 / (400 - 250) = 4000 enheter.") is None
    assert ukjente_tall(svar, "Utregning: 600000 / (400 - 250) = 4000 enheter.") == []
    feil = kontrollregn(Agentsvar("", ""), "Utregning: 600 000 / (400 - 250) = 4 100 enheter.")
    assert feil and "4 000" in feil
    assert kontrollregn(Agentsvar("", ""), "NPV = -200000 + 70000/1.1 + 70000/1.1^2 = -78512") is None   # avrundet
    assert kontrollregn(Agentsvar("", ""), "NPV = -200000 + 70000/1.1 + 70000/1.1^2 = -60000") is not None
    assert regn("2 ^ 3") == 8


def test_fanger_verktoykall_skrevet_som_tekst():
    from src.agent import _kall_i_tekst
    assert [k["argumenter"] for k in _kall_i_tekst("regn_ut((300 - 180) * 5000)")] == [{"uttrykk": "(300 - 180) * 5000"}]
    assert [k["argumenter"] for k in _kall_i_tekst('[regn_ut{uttrykk: "0.50 * 80"}]')] == [{"uttrykk": "0.50 * 80"}]
    assert _kall_i_tekst("Vi bruker regn_ut for dette.") == []
