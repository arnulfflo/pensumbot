"""Modelløving i planen, dekningsoversikten, nyhetsverktøyet og eksamensmodus (14.11.2026)."""

import json
import random
from datetime import date, timedelta

import pytest

import src.database
from src import dekning, eksamensmodus, nyheter, signaler
from src.database import koble, lagre_sporsmal
from src.modeller import modeller
from src.planlegger import MODELLOVING_FRA, lag_plan, med_modelloving
from src.repetisjon import MODELLARK, forfalte_sporsmal, lagre_resultat

START = date(2026, 11, 1)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(src.database, "data_mappe", lambda: tmp_path)
    return koble()


# ---------- modelløving i planen ----------

def _plan(modellfag):
    return lag_plan({"A": START + timedelta(days=40), "B": START + timedelta(days=40)},
                    {"A": ["a1", "a2", "a3"], "B": ["b1", "b2"]}, START, 6, 45, 2, modellfag=modellfag)


def test_modellfag_faar_modelloving_annenhver_blokk_de_siste_tre_ukene():
    plan = _plan({"A"})
    tidlig = [b for b in plan if b.fag == "A" and (START + timedelta(days=40) - b.dato).days > MODELLOVING_FRA]
    sent = [b for b in plan if b.fag == "A" and 2 < (START + timedelta(days=40) - b.dato).days <= MODELLOVING_FRA]
    assert all(b.ovingsmate != "modeller" for b in tidlig)
    andel = sum(b.ovingsmate == "modeller" for b in sent) / len(sent)
    assert 0.4 <= andel <= 0.7, "omtrent annenhver blokk skal være modelløving"
    assert all(b.ovingsmate != "modeller" for b in plan if b.fag == "B"), "fag uten modellark får ikke modelløving"


def test_uten_modellfag_er_planen_som_for():
    assert _plan(frozenset()) == lag_plan({"A": START + timedelta(days=40), "B": START + timedelta(days=40)},
                                          {"A": ["a1", "a2", "a3"], "B": ["b1", "b2"]}, START, 6, 45, 2)
    assert med_modelloving("repetisjon", 0, True) == "repetisjon" and med_modelloving("flashcards", 0, True) == "flashcards"
    assert [med_modelloving("kortsvar", nr, True) for nr in range(3)] == ["modeller", "kortsvar", "modeller"]


# ---------- dekningsoversikten ----------

def test_dekning_skiller_kjenn_case_og_funnet(db):
    alle = {m.navn: m for m in modeller("MRK1001")}
    porter = alle["Porters bransjeanalyse (fem krefter, utvidet)"]
    swot = alle["SWOT-analyse"]
    lagre = lambda **k: lagre_sporsmal(db, fag="MRK1001", tema="t", kilde="k", **k)
    lagre_resultat(db, lagre(ovingsmate="flervalg", sporsmal="Hvilket av disse er et element?", fasit="x",
                             modell=MODELLARK, kildetekst=porter.tekst), "x", True)
    lagre_resultat(db, lagre(ovingsmate="kortsvar", sporsmal="Case.\n\nAnalyser casen med «SWOT-analyse»: vis …", fasit="x",
                             modell="gemma", kildetekst=swot.tekst), "svar", False)
    lagre_resultat(db, lagre(ovingsmate="avkrysning", sporsmal="📄 Case\n\n" + signaler.SPORSMAL_FINN,
                             fasit=json.dumps([porter.navn, swot.navn]), modell=MODELLARK, kildetekst=porter.tekst),
                   json.dumps([porter.navn]), True)
    lagre_resultat(db, lagre(ovingsmate=dekning.EKSAMEN, sporsmal="📝 Nyhetscase", fasit="[]", modell="gemma"), "lang tekst",
                   True, json.dumps({"brukt": [swot.navn], "mangler": [porter.navn]}))
    rader = {r.modell.navn: r for r in dekning.dekning(db, "MRK1001")}
    p, s = rader[porter.navn], rader[swot.navn]
    assert (p.kjenn.riktige, p.kjenn.forsok, p.case.forsok) == (1, 1, 0)
    assert (p.funnet.riktige, p.funnet.forsok) == (1, 2)          # funnet i «finn modellene», mangler i eksamensmodus
    assert (s.case.riktige, s.case.forsok) == (0, 1) and (s.funnet.riktige, s.funnet.forsok) == (1, 2)
    assert p.brukt_paa_case and s.brukt_paa_case
    brukt, antall = dekning.oppsummering(list(rader.values()))
    assert brukt == 2 and antall > 30
    assert list(rader.values())[0].treff >= list(rader.values())[-1].treff, "de vanligste eksamensmodellene først"


def test_eksamensbesvarelser_kommer_ikke_i_repetisjonen(db):
    sid = lagre_sporsmal(db, fag="MRK1001", tema=eksamensmodus.TEMA, ovingsmate=dekning.EKSAMEN, sporsmal="📝", fasit="[]", kilde="k")
    lagre_resultat(db, sid, "svar", False, "{}")
    assert forfalte_sporsmal(db) == []


# ---------- nyhetsverktøyet ----------

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Rema lanserer ny kjede og kutter prisene</title><link>https://e24.no/a/1</link>
  <description>&lt;p&gt;Konkurrentene svarer med kampanjer.&lt;/p&gt;</description><pubDate>Sat, 14 Nov 2026 09:28:03 GMT</pubDate></item>
<item><title>Landslaget vant kampen</title><link>https://e24.no/a/2</link><description>Fotball og pris.</description></item>
<item><title>Uten lenke</title></item></channel></rss>"""


def test_rss_leses_og_sorteres_etter_fag():
    saker = nyheter.les_rss(RSS, "E24")
    assert [n.tittel for n in saker] == ["Rema lanserer ny kjede og kutter prisene", "Landslaget vant kampen"]
    assert saker[0].ingress == "Konkurrentene svarer med kampanjer." and saker[0].dato.startswith("2026-11-14")
    assert nyheter.relevans(saker[0], "MRK1001") >= 3 and nyheter.relevans(saker[1], "MRK1001") == 0, "sport er støy"
    assert saker[0].etikett == "Rema lanserer ny kjede og kutter prisene (E24, 14.11)"


def test_bare_lenker_til_kildene_hentes():
    assert nyheter._tillatt("https://e24.no/naeringsliv/i/x") and nyheter._tillatt("https://www.kampanje.com/premium/x")
    assert not nyheter._tillatt("http://e24.no/x") and not nyheter._tillatt("https://eksempel.no/x")
    assert not nyheter._tillatt("file:///etc/passwd") and not nyheter._tillatt("https://e24.no.ondsinnet.com/x")


def test_artikkelteksten_er_bare_avsnittene():
    side = ("<html><nav><p>" + "Meny som ikke er en del av saken i det hele tatt, selv om den er lang nok.</p></nav>"
            "<p>" + "Rema 1000 kutter prisene på hundre varer etter at kundene har flyttet seg til Kiwi. " * 2 + "</p>"
            "<script>var p = '<p>skript som ikke skal med, uansett hvor langt det måtte være her</p>'</script>"
            "<p>Kort.</p><figure><figcaption><p>" + "Bildetekst som er lang nok til å telle som et avsnitt i saken, men ikke skal med.</p>"
            "</figcaption></figure></html>")
    avsnitt = nyheter.avsnitt_i(side)
    assert len(avsnitt) == 1 and avsnitt[0].startswith("Rema 1000 kutter")
    assert len(nyheter.kutt(["ord " * 400, "ord " * 400, "ord " * 400], 750).split()) == 800, "hele avsnitt, ikke midt i"


# ---------- eksamensmodus ----------

@pytest.mark.parametrize("fag", list(eksamensmodus.OPPGAVER))
def test_alle_oppgavene_peker_paa_et_oppgaveord_i_katalogen(fag):
    alle = {m.navn for m in modeller(fag)}
    for del_ in eksamensmodus.OPPGAVER[fag].values():
        for start, tekst in del_:
            s = eksamensmodus._oppgaveord(fag, start)
            assert s.modeller and set(s.modeller) <= alle, start
            assert "{hvem}" in tekst or "saken" in tekst or tekst.endswith((".", "?"))
    for seed in range(20):
        oppgaver = eksamensmodus.velg_oppgaver(fag, random.Random(seed))
        assert len(oppgaver) == 3 and len({t for _, t in oppgaver}) == 3 and "{" not in "".join(t for _, t in oppgaver)


def test_nyhetscase_faar_tre_oppgaver_og_fasit_fra_katalogen(monkeypatch):
    n = nyheter.Nyhet("Rema kutter prisene", "Priskrig i dagligvare.", "https://e24.no/a/1", "E24", "2026-11-14T09:28")
    monkeypatch.setattr(nyheter, "artikkel", lambda sak: "Rema 1000 kutter prisene. " * 80)
    case = eksamensmodus.fra_nyhet("MRK1001", n, random.Random(1))
    assert case.type == "nyhet" and len(case.oppgaver) == 3 and "Oppgaver\n1. " in case.som_tekst
    assert "SWOT-analyse" in [p.modell for p in case.punkter] and len({p.modell for p in case.punkter}) == len(case.punkter)
    monkeypatch.setattr(nyheter, "artikkel", lambda sak: "")
    assert eksamensmodus.fra_nyhet("MRK1001", n) is None, "sak bak betalingsmur gir ingen case"


BESVARELSE = """Oppgave 1. Jeg starter med makroomgivelsene (PESTEL) og bruker deretter Porters fem krefter. Kjedene har
stor forhandlingsmakt overfor Grandiosa, og trusselen fra substitutter er høy fordi mange velger fersk pizza. På den ene
siden er rivaliseringen hard, men samtidig har Grandiosa et sterkt merke. Jeg oppsummerer i en SWOT: styrken er merket,
svakheten er at produktet oppleves som usunt, muligheten er sunnere varianter, og trusselen er kjedenes egne merkevarer.
Oppgave 2. For å vurdere merkestyrken bruker jeg Aakers modell: merkekjennskap, opplevd kvalitet, assosiasjoner og
lojalitet. Grandiosa har høy kjennskap, men assosiasjonene er delte. Jeg forutsetter at tallene i casen gjelder i dag.
Oppgave 3. Grandiosa vil øke markedsandelen. Ifølge Ansoff er markedspenetrering mest naturlig. Jeg anbefaler derfor
dette, gjort konkret med de 4 P-ene: produkt (sunnere variant), pris (kampanjer), distribusjon (hylleplass i kjedene)
og påvirkning (reklame mot unge). Konklusjonen er at Grandiosa bør forsvare posisjonen sin i dagligvare.""" * 2


def test_retting_finner_modellene_som_er_brukt():
    case = eksamensmodus.tidligere("MRK1001", "Grandiosa")
    r = eksamensmodus.rett(case, BESVARELSE, med_kommentar=False)
    for navn in ("Porters bransjeanalyse (fem krefter, utvidet)", "SWOT-analyse", "Ansoffs ekspansjonsmatrise",
                 "Marketing mix (5 P)", "Tre delsystemer: mikro, interessent og makro"):
        assert navn in r.brukt, navn
    assert r.mangler and r.godkjent == (len(r.brukt) >= r.krav)
    assert "EKB-modellen: forbrukerens kjøpsprosess" in r.mangler, "ordet «modell» i svaret er ikke nok"
    sjekk = dict(r.sjekk)
    assert next(ok for t, ok in sjekk.items() if "4 P" in t) and next(ok for t, ok in sjekk.items() if "koblet til casen" in t)
    assert all(not p.brukt for p in case.punkter), "casen endres ikke av rettingen"

    tom = eksamensmodus.rett(case, "Jeg vet ikke helt hva jeg skal skrive om denne bedriften. " * 12, med_kommentar=False)
    assert not tom.godkjent and len(tom.brukt) <= 1


def test_feller_flagges_naar_de_brukes():
    case = eksamensmodus.tidligere("MRK1001", "Kari Traa")
    assert "Ansoffs ekspansjonsmatrise" in case.feller
    r = eksamensmodus.rett(case, "Jeg bruker Ansoff sin vekstmatrise og velger markedsutvikling for Kari Traa. " * 10, False)
    assert [n for n, _ in r.feller] == ["Ansoffs ekspansjonsmatrise"]


def test_fag_uten_signalkatalog_har_ingen_dekning(db):
    assert dekning.dekning(db, "BOA1100") == []


# ---------- boten velger nyhetssaken selv ----------

def _saker():
    lag = lambda nr, tittel, ingress: nyheter.Nyhet(tittel, ingress, f"https://e24.no/a/{nr}", "E24", "2026-11-14T09:00")
    return [lag(1, "Kommentar: prisene er for høye", "Mener vår kommentator."),
            lag(2, "Rema 1000 lanserer ny kjede", "Rema 1000 vil ta markedsandeler med lavere pris."),
            lag(3, "Oda mister kunder", "Netthandelen faller, og Oda kutter i sortimentet.")]


def test_spraakmodellen_velger_saken_og_navnet_maa_staa_i_den(monkeypatch):
    import src.llm
    svar = {"valg": [{"nr": 3, "virksomhet": "Oda", "hvorfor": "Fall i salget gir en tydelig situasjonsanalyse."},
                     {"nr": 2, "virksomhet": "Kiwi", "hvorfor": "Lansering."}, {"nr": 9, "virksomhet": "x", "hvorfor": "y"},
                     {"nr": 3, "virksomhet": "Oda", "hvorfor": "to ganger"}]}
    monkeypatch.setattr(src.llm, "generer_json", lambda *a, **k: svar)
    valg = eksamensmodus.ranger_nyheter("MRK1001", _saker())
    assert [v.nyhet.tittel[:4] for v in valg] == ["Oda ", "Rema", "Komm"], "modellens valg først, resten etter stikkord"
    assert valg[0].virksomhet == "Oda" and valg[1].virksomhet == "", "Kiwi står ikke i Rema-saken og er funnet på"
    assert valg[2].hvorfor == ""


def test_uten_spraakmodell_brukes_stikkordrekkefolgen(monkeypatch):
    import src.llm

    def nede(*a, **k):
        raise src.llm.SprakmodellFeil("Start Ollama-appen")
    monkeypatch.setattr(src.llm, "generer_json", nede)
    valg = eksamensmodus.ranger_nyheter("MRK1001", _saker())
    assert [v.nyhet.lenke[-1] for v in valg] == ["1", "2", "3"] and not any(v.hvorfor or v.virksomhet for v in valg)
    monkeypatch.setattr(src.llm, "generer_json", lambda *a, **k: {"valg": []})
    assert eksamensmodus.ranger_nyheter("MRK1001", _saker())[0].hvorfor == eksamensmodus.NODLOSNING


def test_boten_hopper_over_brukte_saker_og_saker_bak_betalingsmur(monkeypatch):
    import src.llm
    monkeypatch.setattr(nyheter, "for_fag", lambda fag, antall=20, ferske=False: _saker())
    monkeypatch.setattr(src.llm, "generer_json", lambda *a, **k: {"valg": [
        {"nr": 1, "virksomhet": "Rema 1000", "hvorfor": "Lansering av ny kjede."},
        {"nr": 2, "virksomhet": "Oda", "hvorfor": "Fall i salget."}]})
    monkeypatch.setattr(nyheter, "artikkel", lambda n: "" if "Rema" in n.tittel else "Oda kutter i sortimentet. " * 60)
    case = eksamensmodus.velg_nyhet("MRK1001", unnga={"Kommentar: prisene er for høye"}, rng=random.Random(1))
    assert case.tittel == "Nyhetscase: Oda mister kunder", "Rema-saken ga ingen tekst, så neste valg brukes"
    assert case.hvorfor == "Fall i salget." and "Oda" in case.oppgaver[0] and "virksomheten i saken" not in case.som_tekst
    monkeypatch.setattr(nyheter, "artikkel", lambda n: "")
    assert eksamensmodus.velg_nyhet("MRK1001") is None
