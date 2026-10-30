"""Tester for repetisjon og mestring (SPEC.md: «Spørsmål jeg svarer feil på, kommer igjen etter 1, 3 og
7 dager. Svarer jeg riktig, øker intervallet; feil igjen, starter det på nytt.»)

Kjør:  uv run pytest tester/ -v
"""

from src.repetisjon import mestring, neste_kort_intervall, neste_quiz_intervall


def test_riktig_forste_gang_kommer_ikke_igjen():
    assert neste_quiz_intervall(None, riktig=True) is None


def test_feil_gir_1_dag():
    assert neste_quiz_intervall(None, riktig=False) == 1


def test_riktige_svar_gir_1_3_7():
    intervall, rekke = neste_quiz_intervall(None, riktig=False), []
    for _ in range(3):
        rekke.append(intervall)
        intervall = neste_quiz_intervall(intervall, riktig=True)
    assert rekke == [1, 3, 7]


def test_feil_igjen_starter_paa_nytt():
    assert neste_quiz_intervall(7, riktig=False) == 1


def test_riktig_etter_lengste_intervall_er_laert():
    assert neste_quiz_intervall(30, riktig=True) is None


def test_intervall_som_ble_litt_kortere_enn_planlagt_gaar_likevel_videre():
    # Svarer du noen timer for tidlig, er intervallet f.eks. 2,8 dager. Det skal fortsatt regnes som 3.
    assert neste_quiz_intervall(2.8, riktig=True) == 7


def test_kort_igjen_kommer_i_samme_okt():
    assert neste_kort_intervall(10, "igjen") == 0


def test_kortintervall_vokser_og_lett_vokser_mest():
    assert neste_kort_intervall(None, "greit") == 3
    assert neste_kort_intervall(3, "greit") == 7.5
    assert neste_kort_intervall(3, "lett") > neste_kort_intervall(3, "greit") > neste_kort_intervall(3, "vanskelig")


def test_kortintervall_har_et_tak():
    assert neste_kort_intervall(170, "lett") == 180


def test_mestring_starter_paa_halvparten():
    assert mestring([]) == 0.5


def test_mestring_folger_siste_forsok_mest():
    assert mestring([1, 1, 1]) > 0.8
    assert mestring([0, 0, 0]) < 0.2
    # Samme antall riktige, men de siste riktige teller mer.
    assert mestring([0, 0, 1, 1]) > mestring([1, 1, 0, 0])
