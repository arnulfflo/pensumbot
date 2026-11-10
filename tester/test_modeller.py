"""Tester for modellarket (MRK og ORG) og modellspørsmålene laget i Python.

Kjør:  uv run pytest tester/test_modeller.py -v
"""

import random
from collections import Counter

import pytest

from src.kontroll import normaliser
from src.modeller import FILER, element, kapittel_i, manglende_nokler, modeller, seksjoner
from src.modellquiz import (_kort_forklaring, er_case_oppgave, nevner_element, _likt, _samme_tema, case_avslorer, lag_alle_elementer, rett_avkrysning, lag_betydning, lag_hvilken_modell, lag_hvilket_element, lag_kjenn,
                            lag_mangler, modell_strom)

FAG = list(FILER)


@pytest.mark.parametrize("fag", FAG)
def test_alle_modellene_finnes_i_notatene(fag):
    assert manglende_nokler(fag) == []


@pytest.mark.parametrize("fag", FAG)
def test_modellarket_er_komplett(fag):
    ms = modeller(fag)
    assert len(ms) >= 100
    assert not [i for i, n in Counter(m.id for m in ms).items() if n > 1]
    uten = [m.navn for m in ms if len(m.elementer) < 2]
    assert len(uten) <= 12, uten                       # noen teorier er én idé, f.eks. mestringstro
    assert all(m.tekst.strip() and m.fil for m in ms)
    # Ingen elementer som er rester av notatmalen («[begrep]») eller tomme navn
    assert not [e.navn for m in ms for e in m.elementer if not e.navn or "[" in e.navn]


def test_sentrale_modeller_har_riktige_elementer():
    mrk = {m.navn: [e.navn for e in m.elementer] for m in modeller("MRK1001")}
    org = {m.navn: [e.navn for e in m.elementer] for m in modeller("ORG1100")}
    assert mrk["STP-rammeverket"] == ["Segmentering", "Målretting", "Posisjonering"]
    assert mrk["BCG-matrisen"] == ["Stjerne", "Melkeku", "Problembarn", "Hund"]
    assert mrk["Ansoffs ekspansjonsmatrise"] == ["Markedspenetrasjon", "Produktutvikling", "Markedsutvikling",
                                                 "Diversifisering"]
    assert len(mrk["Gap-modellen"]) == 5
    assert org["Maslows behovshierarki"][0] == "Fysiologiske behov"
    assert org["Forventningsteori (Vroom)"] == ["Forventning", "Instrumentalitet", "Valens"]
    assert org["Lewins tretrinnsmodell"] == ["Mobilisere", "Endre", "Stabilisere"]
    assert len(org["Femfaktormodellen (Big Five)"]) == 5          # fra tabellen i notatet
    assert len(org["Åtte kilder til makt (French og Raven m.fl.)"]) == 8


def test_sidetall_og_figur_kommer_fra_notatet():
    org = {m.navn: m for m in modeller("ORG1100")}
    mrk = {m.navn: m for m in modeller("MRK1001")}
    assert org["Maslows behovshierarki"].side == "s. 97"
    assert "Figur 13.1" in mrk["Servicetrianglet (Andreassen)"].side
    assert mrk["Segmenteringsvariabler"].side == "Figur 6.4"


@pytest.mark.parametrize("tekst, navn, forklaring", [
    ("Behov – det som er nødvendig for vårt velvære", "Behov", "det som er nødvendig for vårt velvære"),
    ("Retning (valg): hva en person prøver å gjøre", "Retning", "valg – hva en person prøver å gjøre"),
    ("Fysiologiske behov (mat, søvn, ren luft)", "Fysiologiske behov", "mat, søvn, ren luft"),
    ("Atferdsuttrykk er handlinger og atferd", "Atferdsuttrykk", "handlinger og atferd"),
    ("arbeidsledelse", "Arbeidsledelse", ""),
])
def test_elementer_tolkes_fra_punktlisten(tekst, navn, forklaring):
    e = element(tekst)
    assert (e.navn, e.forklaring) == (navn, forklaring)


def test_elementer_fra_oppsettet_deles_bare_paa_tankestrek():
    assert element("Rute 1: No frills – lav pris", fra_oppsett=True).navn == "Rute 1: No frills"
    assert element("Psykodynamisk teori (Freud) – ubevisste krefter", fra_oppsett=True).navn == \
        "Psykodynamisk teori (Freud)"


def test_kapittel_fra_tema():
    assert kapittel_i("Motivasjon og arbeidsprestasjon (kap. 3)") == 3
    assert kapittel_i("Segmentering, målgruppevalg og STP (kap. 6)") == 6
    assert kapittel_i("prisstrategi") is None


def test_seksjoner_slutter_ved_sentrale_begreper():
    """ORG-notatene har «2. Sentrale begreper» med malpunkter etter modellene. De skal ikke bli elementer."""
    assert not [s.overskrift for s in seksjoner("ORG1100") for e in s.elementer if "[begrep]" in e.navn]


# ---------- spørsmålene laget i Python ----------

@pytest.mark.parametrize("fag", FAG)
def test_kjenn_sporsmaal_har_entydig_fasit(fag):
    alle = list(modeller(fag))
    rng = random.Random(5)
    antall = Counter()
    for m in alle:
        egne = [e.navn for e in m.elementer]
        for lag in (lag_hvilken_modell, lag_hvilket_element, lag_mangler, lag_betydning):
            q = lag(m, alle, rng)
            if q is None:
                continue
            antall[lag.__name__] += 1
            assert q["fasit"] in q["alternativer"] and len(set(q["alternativer"])) == 4
            gale = [a for a in q["alternativer"] if a != q["fasit"]]
            if lag is lag_hvilken_modell:
                assert q["fasit"] == m.navn
                for g in gale:                         # en gal modell har ikke de samme elementene
                    annen = next(a for a in alle if a.navn == g)
                    assert not any(_likt(e.navn, x) for e in annen.elementer for x in egne), (m.navn, g)
            elif lag in (lag_hvilket_element, lag_mangler):
                assert q["fasit"] in egne
                for g in gale:                         # et galt element hører ikke til, og står ikke i teksten
                    assert not any(_likt(g, x) for x in egne), (m.navn, g)
                    assert normaliser(g) not in normaliser(m.tekst), (m.navn, g)
    assert all(antall[n] >= 30 for n in ("lag_hvilken_modell", "lag_hvilket_element", "lag_mangler")), antall


def test_navnet_avslorer_ikke_svaret():
    org = {m.navn: m for m in modeller("ORG1100")}
    alle = list(org.values())
    for frø in range(20):     # «Rettferdighetsteori» → «Fordelingsrettferdighet» gir svaret bort
        assert lag_hvilken_modell(org["Rettferdighetsteori (Adams)"], alle, random.Random(frø)) is None


def test_case_som_navngir_modellen_stoppes():
    mrk = {m.navn: m for m in modeller("MRK1001")}
    org = {m.navn: m for m in modeller("ORG1100")}
    assert case_avslorer("Bedriften bruker BCG-matrisen på produktene sine.", mrk["BCG-matrisen"])
    assert case_avslorer("Lederen leser om Maslow og behov.", org["Maslows behovshierarki"])
    assert case_avslorer("Kunden går gjennom en sentral rute.", mrk["ELM – Elaboration Likelihood Model"])
    assert case_avslorer("De vurderer leverandørens forhandlingsstyrke.", org["Fiedlers kontingensteori"]) is None
    assert case_avslorer("Butikken lurer på hvilke kunder som kjøper ofte og mye.", mrk["RFM-modellen"]) is None


def test_strommen_gir_hver_modell_bare_en_gang():
    sett = [m.id for _, _, m in modell_strom("ORG1100", "Motivasjon og arbeidsprestasjon (kap. 3)", "kjenn", 50,
                                             random.Random(2))]
    assert sett and len(sett) == len(set(sett))
    assert all(i.startswith("ORG1100-3-") for i in sett)


def test_kjenn_finner_spoersmaal_for_de_fleste_modellene():
    for fag in FAG:
        alle = list(modeller(fag))
        rng = random.Random(1)
        uten = [m.navn for m in alle if lag_kjenn(m, alle, rng) is None]
        # F.eks. «Behov, ønsker og begjær» (navnet er elementene) og teorier uten elementer. De er med i casene.
        assert len(uten) <= len(alle) * 0.3, uten


def test_gale_svar_kommer_ikke_fra_modeller_om_samme_begrep():
    """Skjermbilde 05.11: «Målkonflikt mellom avdelinger» (drivkrefter for markedsorientering) som galt svar
    på et spørsmål om markedsorientering hos Kohli og Jaworski. Det er for likt til å være et rettferdig galt svar."""
    mrk = {m.navn: m for m in modeller("MRK1001")}
    m = mrk["Markedsorientering (Kohli og Jaworski)"]
    assert _samme_tema(m, mrk["Interne drivkrefter for markedsorientering"])
    assert _samme_tema(m, mrk["Fire grunnpilarer i markedsorientert tankegang"])
    assert not _samme_tema(m, mrk["Markedsplanleggingsprosessen"])
    alle = list(mrk.values())
    for frø in range(30):
        q = lag_hvilket_element(m, alle, random.Random(frø))
        assert "Målkonflikt mellom avdelinger" not in q["alternativer"]
        assert "Målgruppetenkning" not in q["alternativer"]


@pytest.mark.parametrize("fag", FAG)
def test_avkrysning_har_alle_elementene_og_bare_gale_ellers(fag):
    alle = list(modeller(fag))
    rng = random.Random(4)
    laget = 0
    for m in alle:
        q = lag_alle_elementer(m, alle, rng)
        if q is None:
            continue
        laget += 1
        egne = [e.navn for e in m.elementer]
        assert sorted(q["fasit"]) == sorted(egne)
        assert set(egne) <= set(q["alternativer"]) and 5 <= len(q["alternativer"]) <= 8
        assert len(set(q["alternativer"])) == len(q["alternativer"])
        for g in set(q["alternativer"]) - set(egne):
            assert not any(_likt(g, x) for x in egne) and normaliser(g) not in normaliser(m.tekst), (m.navn, g)
    assert laget >= 30


def test_avkrysning_rettes_som_alt_eller_ingenting():
    q = {"fasit": ["Mobilisere", "Endre", "Stabilisere"]}
    assert rett_avkrysning(q, ["Endre", "Stabilisere", "Mobilisere"]) == (True, [], [])
    assert rett_avkrysning(q, ["Endre", "Mobilisere"]) == (False, ["Stabilisere"], [])
    assert rett_avkrysning(q, ["Endre", "Mobilisere", "Stabilisere", "Lojalitet"]) == (False, [], ["Lojalitet"])


@pytest.mark.parametrize("navn, svar, ventet", [
    ("Målkonflikt mellom avdelinger", "det er tydelig målkonflikt mellom avdeligenen", True),   # skrivefeil i svaret
    ("Relasjoner mellom avdelinger", "dårlige relasjoner mellom avdelingene", True),
    ("Ledersignaler", "Bedriften mangler ledersignaler", True),
    ("Sentralisering", "Bedriften bør bli mer markedsorientert", False),
    ("Insentiver", "ingen blir belønnet for samarbeid", False),
])
def test_case_rettingen_ser_etter_elementet_i_svaret(navn, svar, ventet):
    """Skjermbilde 05.11: et svar som brukte alle elementene fikk 0 av 6, fordi casepåstandene ble sjekket mot notatet."""
    assert nevner_element(navn, svar) is ventet


def test_noekkelpunkt_viser_betydningen_ikke_tallet_fra_figuren():
    assert _kort_forklaring("+.32 – ansatte følger lederens holdning") == "Ansatte følger lederens holdning"


def test_case_oppgaver_kjennes_igjen_ogsaa_i_repetisjonen():
    assert er_case_oppgave({"sporsmal": "Casen …\n\nAnalyser casen med «BCG-matrisen». Bruk elementene i modellen."})
    assert not er_case_oppgave({"sporsmal": "Forklar hva BCG-matrisen er."})


@pytest.mark.parametrize("fag", ["MRK1001", "ORG1100"])
def test_signalene_viser_til_modeller_som_finnes(fag):
    """config/signaler_{fag}.yaml: hvert modellnavn må stå på modellarket, og hvert signal må ha kilde."""
    import yaml
    from src.konfig import ROT
    data = yaml.safe_load((ROT / "config" / f"signaler_{fag}.yaml").read_text(encoding="utf-8"))
    navn = {m.navn for m in modeller(fag)}
    for s in data["signaler"]:
        assert s["kilder"] and s["hvorfor"] and s["type"] in ("oppgaveord", "case", "ikke"), s["signal"]
        assert s.get("modeller") or s.get("begreper"), s["signal"]
        for m in s.get("modeller", []):
            assert m in navn, (m, s["signal"])


def test_case_som_merker_av_elementene_forkastes():
    """En SWOT-case med «(Styrke)» og «(Trussel)» i teksten har gjort analysen for studenten."""
    swot = next(m for m in modeller("MRK1001") if m.navn == "SWOT-analyse")
    merket = ("Bakeriet har et sterkt omdømme for håndlagde brød (Styrke). Kjedene presser prisene (Trussel). "
              "Trussel: nye konkurrenter.")
    assert case_avslorer(merket, swot)
    assert case_avslorer("Bakeriet har sterke sider, men kjedene presser prisene og truer marginene.", swot) is None
