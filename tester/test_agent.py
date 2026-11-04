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


def test_fjerner_latex():
    from src.agent import uten_latex
    assert uten_latex("120 $\\times$ 5000 = 600 000") == "120 × 5000 = 600 000"
    assert uten_latex("$NPV = \\frac{70000}{1,1}$") == "NPV = (70000) / (1,1)"
    assert uten_latex("Pris 400 kr, 25 \\% rabatt") == "Pris 400 kr, 25 % rabatt"


# ---------- studieveilederen ----------

@pytest.mark.parametrize("tekst, minutter", [
    ("Jeg har to timer i kveld", 120),
    ("1,5 time", 90),
    ("har 45 min", 45),
    ("en halvtime før middag", 30),
    ("halvannen time", 90),
    ("Hva bør jeg øve på?", None),
    ("hva gjør jeg den timen", None),          # «den timen» er ikke «en time»
])
def test_finner_tid_i_sporsmalet(tekst, minutter):
    from src.veileder import minutter_i
    assert minutter_i(tekst) == minutter


def test_finner_faget_i_sporsmalet():
    from src.veileder import fag_i
    assert fag_i("Jeg har 45 min til BØA") == "BOA1100"
    assert fag_i("litt markedsføring i kveld") == "MRK1001"
    assert fag_i("hva bør jeg gjøre i dag?") is None
    assert fag_i("BØA eller MRK?") is None


@pytest.fixture
def db(tmp_path, monkeypatch):
    import src.database
    monkeypatch.setattr(src.database, "data_mappe", lambda: tmp_path)
    return src.database.koble()


def test_okt_holder_seg_innenfor_tiden_og_tar_svake_temaer_forst(db):
    from datetime import date
    from src.database import lagre_sporsmal
    from src.repetisjon import lagre_resultat
    from src.veileder import lag_okt

    idag = date(2026, 11, 1)                                  # fast dato, så eksamenene alltid ligger frem i tid
    svakt = "Prispolitikk (kap. 9)"
    for _ in range(3):
        sid = lagre_sporsmal(db, fag="MRK1001", tema=svakt, ovingsmate="flervalg", sporsmal="?", fasit="a", kilde="x")
        lagre_resultat(db, sid, svar="feil", riktig=False)

    for minutter in (20, 100, 120, 135):
        okt = lag_okt(db, minutter, idag=idag)
        assert sum(b.minutter for b in okt) <= minutter
        assert all(b.minutter >= 15 for b in okt)
    okt = lag_okt(db, 120, idag=idag)
    assert all(b.ovingsmate != "feilsvar" for b in okt)       # feilsvarene forfaller først i morgen
    temaer = [b.tema for b in okt if b.tema]
    assert temaer[0] == svakt                                 # lav mestring + nærmeste eksamen først
    assert all(b.fag == "BOA1100" for b in lag_okt(db, 90, fag="BØA1100", idag=idag))
    assert lag_okt(db, 10, idag=idag) == []


def test_veilederkontrollen(db):
    from src.agent import Steg
    from src.veileder import Veiledersvar, _kall_i_tekst, _mangler

    svar = Veiledersvar("Jeg har to timer", "")
    assert "minutter=120" in _mangler(svar, [], "Øv på MRK.")
    svar.steg.append(Steg("lag_okt", "120", "3 blokker"))
    data = ["MRK1001: eksamen 23.11 om 21 dager.", "Økt på 120 av 120 minutter:\n1. MRK1001 flervalg, 45 min"]
    assert _mangler(svar, data, "MRK1001 har eksamen 23. november, om 21 dager. Start med 45 minutter, 2 timer totalt.") is None
    assert "37" in _mangler(svar, data, "Du har 37 feilsvar.")
    assert "XYZ1234" in _mangler(svar, data, "Øv på XYZ1234.")
    assert "fag=BOA1100" in _mangler(Veiledersvar("45 min til BØA", "", steg=[Steg("lag_okt", "45", "")]), [], "")
    assert _mangler(Veiledersvar("45 min til BØA", "", steg=[Steg("lag_okt", "45, BOA1100", "")]),
                    ["45"], "Øv 45 minutter.") is None
    assert _kall_i_tekst("lag_okt(90, BOA1100)") == [{"id": "tekst0", "navn": "lag_okt",
                                                       "argumenter": {"fag": "BOA1100", "minutter": 90}}]


# ---------- quiz: spørsmål som krever en oppgave studenten ikke ser ----------

def test_stopper_sporsmal_om_en_oppgave_i_pensum():
    from src.kontroll import viser_til_ukjent
    kilde = "Oppgave 4. Virksomheten AS produserer 10 000 enheter. En kunde i Danmark ber om en engangsordre ..."
    assert viser_til_ukjent("Hva er den laveste prisen Virksomheten AS kan akseptere for éngangsordren?", kilde)
    assert viser_til_ukjent("Hva blir dekningsbidraget i tabellen?", "")
    assert viser_til_ukjent("Løs oppgave 3 med bidragsmetoden.", "")
    assert viser_til_ukjent("Hva er det sentrale i motivasjonsprosessen, basert på teksten?", "")
    assert viser_til_ukjent("Hva er funksjonen til kostnader i prisfastsettelsen, ifølge teksten?", "")
    assert viser_til_ukjent("Hvordan føres et lån i regnskapet?", "") is None
    # oppdiktet case i selve spørsmålet (kortsvar, stil «case») og vanlige fagspørsmål er greit
    assert viser_til_ukjent("Fjordkaffe AS vurderer å senke prisen. Bruk nullpunktanalyse til å vurdere det.", kilde) is None
    assert viser_til_ukjent("Hva er laveste akseptable pris for en engangsordre ved ledig kapasitet?", kilde) is None


def test_stopper_sporsmal_der_svaret_star_i_sporsmalet():
    from src.kontroll import avslorer_svaret
    assert avslorer_svaret(
        "Hvilken type distribusjonsstrategisk tilnærming innebærer å selge produktet hos så mange forhandlere som mulig?",
        "Selg overalt, hos så mange forhandlere som mulig.",
        ["Fokuser på å selge kun i spesialiserte, lukkede miljøer.", "Begrens salget til et lite antall utvalgte "
         "utsalgssteder.", "Selg kun gjennom utvalgte, spesifikke partnere."])
    assert avslorer_svaret("Hva innebærer markedsføringens mål i sammenheng med markedsstrategien?",
                           "Markedsføringsmål", ["Kommunikasjonsmål", "Kommunikasjonstaktikker", "Markedsstrategi"])
    # spør etter navnet, svarene er navn: greit
    assert avslorer_svaret("Hvilken type distribusjon innebærer å selge hos så mange forhandlere som mulig?",
                           "Intensiv distribusjon", ["Selektiv distribusjon", "Eksklusiv distribusjon",
                                                     "Direkte distribusjon"]) is None
    assert avslorer_svaret("Hva er det sentrale utgangspunktet i behovsteorier?",
                           "Mennesker har grunnleggende behov, og disse driver atferden vår.",
                           ["Motivasjon er en prosess som påvirker intensiteten i handlinger.",
                            "Retning, varighet og intensitet er de viktigste elementene.",
                            "Indre motivasjon er alltid sterkt styrt mot mål."]) is None


@pytest.mark.parametrize("sporsmal, riktig, gale", [
    ("Hva innebærer markedsføringsmål i sammenheng med markedsstrategien?",
     "Markedsføringsmål er det overordnede målet som skal oppnås gjennom markedsføringen.",
     ["Markedsstrategien er selve budskapet som skal formidles til markedet.",
      "Kommunikasjonstaktikker er de verktøyene som brukes for å nå målene.",
      "Kommunikasjonsmål er de spesifikke handlingene som skal utføres."]),
    ("Hva er et sentralt formål med å kartlegge kjøpsatferd?", "Kjøpsatferd klarlegger behov, bruk og beslutningsprosess.",
     ["Det definerer hvilke kanaler som er mest effektive.", "Det fastslår hvilke priskriterier som er mest attraktive.",
      "Det beskriver hvordan markedet endrer seg over tid."]),
    ("Hva er hovedforskjellen mellom transaksjonsorientering og relasjonsorientering når det gjelder tidshorisont?",
     "lang tidshorisont", ["vekt på produksjonens sak", "kort tidshorisont", "fokus på produktfordeler"]),
    ("Hva er et formål med inntekts- og kostnadsfordeling?", "å fordele inntekter og kostnader på avdelingene",
     ["å beregne resultat for hver enkelt enhet", "å fastsette kostnader for spesifikke områder",
      "å registrere omsetning på enkelte enheter"]),
])
def test_stopper_dumme_flervalg(sporsmal, riktig, gale):
    from src.kontroll import avslorer_svaret
    assert avslorer_svaret(sporsmal, riktig, gale)


@pytest.mark.parametrize("sporsmal, riktig, gale", [
    ("Hva er det første steget i STP-prosessen for å håndtere et heterogent marked?",
     "Del markedet inn i grupper på den mest hensiktsmessige måten",
     ["Velg og nå de kundegruppene som gir mest nytte", "Definer hvordan man skal betjene de ulike gruppene",
      "Velg posisjon blant konkurrentene"]),
    ("Hva representerer egenkapital i en bedrift?", "Det er krav som eierne har på bedriften",
     ["Det er summen av alle inntekter", "Det er den delen av eiendelene som er finansiert med lån",
      "Det er pengene i banken"]),
    ("Hva er en kjerneegenskap ved psykologiske fordeler sammenlignet med rasjonelle produktfordeler?",
     "De er vanskeligere å ta igjen", ["De er rent funksjonelle og måles", "De er lett tilgjengelige for alle",
                                       "De er basert på umiddelbar nytte"]),
])
def test_slipper_gjennom_gode_flervalg(sporsmal, riktig, gale):
    from src.kontroll import avslorer_svaret
    assert avslorer_svaret(sporsmal, riktig, gale) is None


def test_stopper_sporsmal_om_kurset_og_konteksten():
    from src.kontroll import viser_til_ukjent
    assert viser_til_ukjent("Hva er et hovedmål med å studere langsiktige beslutningsproblemer?", "")
    assert viser_til_ukjent("Hva er en merkevare definert som i denne konteksten?", "")


def test_stopper_svar_og_sporsmal_som_viser_til_kilden():
    from src.kontroll import avslorer_svaret, viser_til_ukjent
    assert viser_til_ukjent("Hva er en merkevare definert som i denne sammenhengen?", "")
    assert viser_til_ukjent("Hva definerer destruktiv ledelse ifølge modellen?", "")
    assert avslorer_svaret("Hva definerer destruktiv ledelse?", "evne til å hemme/forhindre dette",
                           ["evne til å motivere andre", "evne til å skape mening", "evne til å styre daglig drift"])


def test_stopper_sporsmal_om_studenten_og_kapittelet():
    from src.kontroll import viser_til_ukjent
    assert viser_til_ukjent("Hvilke elementer skal studenten kunne beskrive etter å ha lest kapittelet om posisjonering?", "")
    assert viser_til_ukjent("Hvilke tre temaer trekker boken ut som en sjekkliste?", "")
    assert viser_til_ukjent("Hva er det første steget i STP-prosessen?", "") is None


@pytest.mark.parametrize("sporsmal, stoppes", [
    ("Hva er en potensiell fare knyttet til en for stor utvidelse av sortimentet?", True),
    ("Hva er et sentralt argument for å velge å maksimere salget som mål for prispolitikken?", True),
    ("Hva er en av faktorene som påvirker lojalitet utover tilfredshet?", True),
    ("Hva er et kjennetegn ved eksklusiv distribusjon?", False),
    ("Hva er en kognitiv struktur?", False),
    ("Hva er et grunnleggende krav for at ledelse skal kunne utøves?", False),
    ("Hva er det første steget i STP-prosessen?", False),
])
def test_stopper_sporsmal_om_en_av_flere(sporsmal, stoppes):
    from src.kontroll import avslorer_svaret
    resultat = avslorer_svaret(sporsmal, "Et ganske vanlig svar her", ["Et annet svar", "Et tredje svar", "Et fjerde"])
    assert bool(resultat) == stoppes, resultat
