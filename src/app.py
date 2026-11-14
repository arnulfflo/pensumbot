"""Fase 5: Gradio-grensesnitt i nettleseren. Bruker de samme funksjonene som terminalkommandoene.

Kjører bare på din maskin (127.0.0.1). Ingenting deles på nettet.
Utseendet ligger i src/app.css; fargene per fag i FARGER under.

Kjør:  uv run python -m src.app      (åpner http://127.0.0.1:7860 i nettleseren)
"""

import json
import queue
import random
import re
import threading
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import gradio as gr

from src.database import koble, lagre_sporsmal
from src.flashcards import forfalte, lag_nye_kort
from src import dekning, eksamensmodus, eksamensvekt, formler, modellquiz, nyheter, signaler
from src.henting import Bit, hent
from src.innlesing import alle_fag, standardfag
from src.kortsvar import STILER, vurder
from src.llm import SprakmodellFeil, generer
from src.planlegger import UKEDAGER, angre_hopp_over, blokker_for, hopp_over, lag_og_lagre, last_eksamener, marker_fullfort
from src.quiz import modellnavn, sporsmal_strom
from src.modeller import FILER as MODELLFAG, kapittel_i, modellark
from src.repetisjon import MODELLARK, forfalte_sporsmal, lagre_resultat
from src.agent import FAG as AGENTFAG, kildeliste as agentkilder, kjor_agent
from src.svar import selvstendig_sporsmal, svar_pa
from src.veileder import kjor_veileder

FAG = alle_fag()
BOKSTAVER = "ABCD"
FARGER = {"MRK1001": "#ea7a1a", "ORG1100": "#2f6fde", "BOA1100": "#1f9d63", "MET1001": "#8b5cf6"}
NAVN = {"MRK1001": "Markedsføring", "ORG1100": "Organisasjon og ledelse", "BOA1100": "Bedriftsøkonomi",
        "MET1001": "Metode"}
IKONER = {"flashcards": "🗂️", "flervalg": "🎯", "kortsvar": "✍️", "repetisjon": "🔁", "feilsvar": "🔁",
          "modeller": "🧩"}
OVINGSNAVN = {"flashcards": "Flashcards", "flervalg": "Flervalg", "kortsvar": "Kortsvar", "repetisjon": "Repetisjon",
              "feilsvar": "Feilsvar på nytt", "modeller": "Modeller og teorier", "avkrysning": "Avkrysning"}
QUIZTYPER = [("flervalg", "flervalg"), ("kortsvar", "kortsvar"), ("modeller og teorier", "modeller"),
             ("repetisjon", "repetisjon")]
MODELLSTILER = [(navn, verdi) for verdi, navn in modellquiz.TYPER.items()]
ALLE_KAPITLER = "Alle kapitler"

# Quizøkter per nettleserfane. Generatorer kan ikke ligge i gr.State (den kopierer verdiene),
# så de lagres her med Gradios økt-ID som nøkkel.
OKTER: dict[str, dict] = {}
SPORSMAL_PER_TEMA = 15   # gir 45 kandidatbiter; flere enn det handler sjelden om temaet
SLUTT = object()         # markerer at bakgrunnstråden ikke finner flere spørsmål


# ---------- små HTML-hjelpere ----------

def farge(fag: str) -> str:
    return FARGER.get(fag, "#64748b")


def merke(fag: str, lys: bool = False) -> str:
    return f'<span class="merke{" lys" if lys else ""}" style="--fag:{farge(fag)}">{escape(fag)}</span>'


def kort_tema(tema: str) -> str:
    """«Distribusjon (kap. 8)» → «Distribusjon»."""
    return tema.split(" (")[0]


ALLE_KORT = "Alle kort som skal repeteres"


def temaer_for(fag: str, med_alle: bool = True) -> list[str]:
    """Temaene fra config/eksamener.yaml, til rullemenyene på quiz og flashcards."""
    temaer = last_eksamener()[1].get(fag, [])
    return [ALLE_KORT, *temaer] if med_alle else temaer


def startfag() -> str:
    """Faget som står valgt når appen åpnes: det med nærmest eksamen, så du slipper å bytte hver gang."""
    kommende = {f: d for f, d in last_eksamener()[0].items() if d >= date.today() and f in FAG}
    return min(kommende, key=kommende.get) if kommende else standardfag()


def topp() -> str:
    datoer, _, _ = last_eksamener()
    eks = "".join(
        f'<div class="eks" style="--fag:{farge(fag)}">{escape(fag)}<b>{(d - date.today()).days} dager</b></div>'
        for fag, d in sorted(datoer.items(), key=lambda x: x[1]) if d >= date.today())
    return (f'<div class="topp"><div><h1>📚 Pensumboten</h1>'
            f'<div class="under">Spør, øv og følg planen – alt fra ditt eget pensum.</div></div>'
            f'<div class="nedtelling">{eks}</div></div>')


# ---------- Spør ----------

def svar_som_markdown(s, tolket: str | None = None) -> str:
    deler = [f"<small><i>Tolket som: {escape(tolket)}</i></small>\n\n" if tolket else "", s.tekst]
    if s.finnes_ikke:
        vist = s.biter[:3]
        deler.append("\n\n**Nærmeste treff i materialet:**")
    else:
        vist = [b for b in s.biter if b in s.siterte] or s.biter
        deler.append("\n\n**Kilder:**")
    for b in vist:
        deler.append(f"\n- `[{s.biter.index(b) + 1}]` {b.metadata['fag']}/{b.kilde}")
    tekster = "".join(f"<p><b>[{nr}] {escape(b.metadata['fag'])}/{escape(b.kilde)}</b></p>"
                      f"<blockquote>{escape(b.tekst)}</blockquote>"
                      for nr, b in enumerate(s.biter, start=1))
    deler.append(f"\n\n<details><summary>Les kildetekstene ({len(s.biter)})</summary>{tekster}</details>")
    return "".join(deler)


STEGTEKST = {"sok_i_pensum": "🔎 Søkte i pensum: «{inn}» → {ut}", "regn_ut": "🧮 Regnet ut: {ut}",
             "kontrollregning": "✔ Koden kontrollregnet: {ut}", "kontroll": "↩ Sendt tilbake: {ut}",
             "se_status": "📋 Sjekket status: {ut}", "se_mestring": "📈 Så på mestringen i {inn}: {ut}",
             "lag_okt": "🗓️ Satte opp en økt ({inn}): {ut}"}


def _agentsteg(steg) -> str:
    return "\n".join(f"{nr}. " + STEGTEKST.get(st.verktoy, "{ut}").format(inn=escape(st.inn[:120]), ut=escape(st.ut))
                     for nr, st in enumerate(steg, start=1))


def agent_som_markdown(svar, tolket: str | None = None) -> str:
    deler = [f"<small><i>Tolket som: {escape(tolket)}</i></small>\n\n" if tolket else "", svar.tekst]
    if kilder := agentkilder(svar):
        deler.append("\n\n**Kilder:**" + "".join(f"\n- {k}" for k in kilder))
    deler.append(f"\n\n<details><summary>Slik jobbet agenten ({len(svar.steg)} steg)</summary>\n\n"
                 f"{_agentsteg(svar.steg)}\n\n</details>")
    return "".join(deler)


def _spor_agent(sporsmal, samtale, tolket):
    """Kjører BØA-agenten i en egen tråd og viser stegene etter hvert som de kommer."""
    steg, ferdig = [], {}
    trad = threading.Thread(target=lambda: ferdig.update(svar=kjor_agent(sporsmal, steg.append)), daemon=True)
    trad.start()
    vist = -1
    while trad.is_alive():
        if len(steg) != vist:
            vist = len(steg)
            samtale[-1] = {"role": "assistant", "content": "*BØA-agenten jobber …*\n\n" + _agentsteg(steg)}
            yield
        trad.join(0.3)
    svar = ferdig.get("svar")
    samtale[-1] = {"role": "assistant", "content": agent_som_markdown(svar, tolket) if svar
                   else "Agenten stoppet uventet. Prøv igjen."}
    yield svar


def spor(melding, samtale, utveksling, fag, eksempelsvar, agent=True):
    """samtale: meldingene som vises. utveksling: [(spørsmål, svartekst)] som oppfølgingsspørsmål tolkes ut fra.

    For BØA brukes agenten (søk + kalkulator) når «agent» er på."""
    if not melding.strip():
        yield samtale, samtale, utveksling, melding
        return
    samtale = samtale + [{"role": "user", "content": melding},
                         {"role": "assistant", "content": f"*Leter i {fag} …*"}]
    yield samtale, samtale, utveksling, ""
    try:
        # «forklar enklere», «hva med pull?» → et spørsmål som kan søkes på alene
        sporsmal = selvstendig_sporsmal(melding, utveksling)
        tolket = sporsmal if sporsmal.strip().lower() != melding.strip().lower() else None
        if agent and fag == AGENTFAG:
            for svar in _spor_agent(sporsmal, samtale, tolket):
                yield samtale, samtale, utveksling, ""
            if svar:
                utveksling = utveksling + [(sporsmal, svar.tekst)]
        else:
            s = svar_pa(sporsmal, fag=fag, med_eksempelsvar=eksempelsvar)
            samtale[-1] = {"role": "assistant", "content": svar_som_markdown(s, tolket)}
            utveksling = utveksling + [(sporsmal, s.tekst)]
    except TimeoutError:
        samtale[-1] = {"role": "assistant", "content": "Språkmodellen brukte for lang tid. Prøv igjen."}
    except SprakmodellFeil as feil:
        samtale[-1] = {"role": "assistant", "content": f"⚠️ {feil}"}
    yield samtale, samtale, utveksling, ""


# ---------- Quiz ----------

def _repetisjonsstrom(fag):
    """Forfalte feilsvar i samme form som sporsmal_strom: (spørsmål, bit, id)."""
    for s in forfalte_sporsmal(koble(), fag):
        liste = json.loads(s["alternativer"]) if s["alternativer"] else []
        bit = Bit(s["kildetekst"] or s["sitat"] or "", {"fil": s["kilde"]}, 0.0)
        if s["ovingsmate"] == "flervalg":
            q = {"sporsmal": s["sporsmal"], "alternativer": liste, "fasit": s["fasit"], "forklaring": s["forklaring"],
                 "sitat": s["sitat"], "type": "flervalg", "tema": s["tema"]}
        elif s["ovingsmate"] == "avkrysning":
            q = {"sporsmal": s["sporsmal"], "alternativer": random.sample(liste, len(liste)),
                 "fasit": json.loads(s["fasit"]), "forklaring": s["forklaring"], "sitat": s["sitat"],
                 "type": "avkrysning", "tema": s["tema"]}
        else:
            q = {"sporsmal": s["sporsmal"], "nokkelpunkter": liste, "modellsvar": s["fasit"], "fasit": s["fasit"],
                 "sitat": s["sitat"], "type": "kortsvar", "tema": s["tema"]}
        yield {**q, "fag": s["fag"]}, bit, s["id"], s["kilde"]


def _tema_for_kapittel(fag, kapittel) -> str:
    """Temaet i config/eksamener.yaml med samme kapittel, så modellspørsmål teller på riktig tema i mestringen."""
    return next((t for t in temaer_for(fag, med_alle=False) if kapittel_i(t) == kapittel), f"kap. {kapittel}")


def _modellstrom(fag, tema, stil):
    db = koble()
    if stil in signaler.TYPER:          # fasit fra signalkatalogen (bare «ny case» bruker språkmodellen, til teksten)
        strom = ((q, Bit(m.tekst, {"fil": m.fil}, 0.0), m)
                 for q, m in signaler.signal_strom(fag, tema, stil, SPORSMAL_PER_TEMA))
    else:
        mestret, stilt = eksamensvekt.nylig_ovd(db, fag)
        strom = modellquiz.modell_strom(fag, tema, stil, SPORSMAL_PER_TEMA, mestret=mestret, stilt=stilt)
    for q, bit, m in strom:
        tema_m = _tema_for_kapittel(fag, m.kapittel)
        kilde = q.get("kilde") or m.kilde
        laget_av = modellnavn() if q["stil"] in ("velg modell", "bruk modellen", "ny case") else MODELLARK
        fasit = json.dumps(q["fasit"], ensure_ascii=False) if isinstance(q["fasit"], list) else q["fasit"]
        lagre = dict(fag=fag, tema=tema_m, ovingsmate=q["type"], sporsmal=q["sporsmal"],
                     alternativer=q.get("alternativer") or q.get("nokkelpunkter"), fasit=fasit,
                     forklaring=q.get("forklaring"), sitat=q["sitat"], kilde=kilde, modell=laget_av,
                     kildetekst=m.tekst)
        yield {**q, "tema": tema_m, "fag": fag}, bit, lagre, kilde


def riktig_stil(type_, stil):
    """Stilen som hører til typen. Rester fra forrige type («forklar» for modeller) gir standardvalget."""
    if type_ == "modeller":
        return stil if stil in modellquiz.TYPER or stil in signaler.TYPER else "blandet"
    return stil if stil in (*STILER, "blandet") else "forklar"


def _ny_strom(fag, tema, type_, stil):
    """Gir (spørsmål, bit, id eller lagringsdata, kilde). Nye spørsmål lagres først når de vises (se _vis),
    så spørsmål som lages på forhånd og aldri blir vist, ikke teller som «stilt» eller stopper like spørsmål."""
    if type_ == "repetisjon":
        yield from _repetisjonsstrom(fag)
        return
    if type_ == "modeller":
        yield from _modellstrom(fag, tema, stil)
        return
    db = koble()
    for q, bit in sporsmal_strom(fag, tema, SPORSMAL_PER_TEMA, type_, stil, db=db):
        kilde = f"{fag}/{bit.kilde}"
        lagre = dict(fag=fag, tema=tema, ovingsmate=type_, sporsmal=q["sporsmal"],
                     alternativer=q.get("alternativer") or q.get("nokkelpunkter"), fasit=q["fasit"],
                     forklaring=q.get("forklaring"), sitat=q["sitat"], kilde=kilde, modell=modellnavn(),
                     kildetekst=bit.tekst)
        yield {**q, "type": type_, "tema": tema, "fag": fag}, bit, lagre, kilde


def _start_okt(fag, tema, type_, stil) -> dict:
    """Lager spørsmål i en bakgrunnstråd, to foran det du svarer på, så «Nytt spørsmål» går fort."""
    stil = riktig_stil(type_, stil)
    okt = {"nokkel": (fag, tema, type_, stil), "ko": queue.Queue(maxsize=2), "stopp": threading.Event(),
           "besvart": 0, "riktige": 0, "nr": 0, "feil": [], "runde": []}

    def legg_i_ko(element) -> bool:
        while not okt["stopp"].is_set():
            try:
                okt["ko"].put(element, timeout=1)
                return True
            except queue.Full:
                continue
        return False

    def arbeid():
        # Vent litt: skriver du et eget tema eller bytter valg, stoppes denne før den rekker å bruke modellen.
        if okt["stopp"].wait(1.5):
            return
        try:
            for element in _ny_strom(fag, tema, type_, stil):
                if okt["stopp"].is_set() or not legg_i_ko(element):
                    return
        except SprakmodellFeil as feil:    # Ollama er ikke startet: si det i appen
            okt["feilmelding"] = str(feil)
        except BaseException as feil:      # alt annet: avslutt økten i stedet for å la «Nytt spørsmål» henge
            okt["feilmelding"] = "Noe gikk galt da spørsmålene skulle lages. Se terminalen, og prøv igjen."
            print(f"Feil under laging av spørsmål: {type(feil).__name__}: {feil}")
        legg_i_ko(SLUTT)

    threading.Thread(target=arbeid, daemon=True).start()
    return okt


def _poeng(okt) -> str:
    if not okt or not okt.get("besvart"):
        return ""
    andel = okt["riktige"] / okt["besvart"]
    return (f'<div class="poeng"><div>Besvart <b>{okt["besvart"]}</b></div>'
            f'<div>Riktige <b>{okt["riktige"]}</b></div><div>Treff <b>{andel:.0%}</b></div></div>')


def _sporsmalstekst(tekst: str) -> str:
    """En hel eksamenscase får vanlig skrift i en egen rulleboks, og bare spørsmålet står i fet skrift."""
    linjer = lambda s: escape(s).replace(chr(10), "<br>")
    if tekst.startswith("📄") and "\n\n" in tekst:
        tittel, rest = tekst.split("\n\n", 1)
        case, sporsmal = rest.rsplit("\n\n", 1)
        return (f'<div class="sporsmal">{linjer(tittel)}</div><div class="casetekst">{linjer(case)}</div>'
                f'<div class="sporsmal">{linjer(sporsmal)}</div>')
    return f'<div class="sporsmal">{linjer(tekst)}</div>'


def _sporsmalskort(fag, q, nr, kilde: str = "") -> str:
    """kilde: hvor i pensum spørsmålet er laget fra, så du kan slå det opp hvis du står fast."""
    stil = f' · {escape(q["stil"])}' if q.get("stil") and q["stil"] != "forklar" else ""
    return (f'<div class="kort" style="--fag:{farge(fag)}"><div class="topplinje">'
            f'<span>{merke(fag)} &nbsp;{escape(kort_tema(q.get("tema") or ""))}</span>'
            f'<span>Spørsmål {nr} · {OVINGSNAVN[q["type"]]}{stil}</span></div>'
            f'{_sporsmalstekst(q["sporsmal"])}'
            f'{f"<div class=fra>📖 Laget fra: {escape(kilde)}</div>" if kilde else ""}</div>')


def _melding(tekst) -> str:
    return f'<div class="tom">{escape(tekst)}</div>'


def rydd_okt(request: gr.Request):
    """Fanen er lukket eller lastet på nytt: stopp bakgrunnstråden, ellers lager den spørsmål til ingen."""
    if okt := OKTER.pop(request.session_hash, None):
        okt["stopp"].set()


def _ny_okt(request, fag, tema, type_, stil) -> dict:
    """Ny økt for nytt valg. Stopper den gamle bakgrunnstråden, men tar med feilsvarene du ikke har tatt på nytt."""
    gammel = OKTER.get(request.session_hash)
    okt = _start_okt(fag, tema, type_, stil)
    if gammel:
        gammel["stopp"].set()
        okt["feil"], okt["runde"], okt["runde_fag"] = gammel["feil"], gammel["runde"], gammel.get("runde_fag")
    OKTER[request.session_hash] = okt
    return okt


def forbered_quiz(fag, tema, type_, stil, request: gr.Request):
    """Begynner å lage spørsmål så snart temaet er valgt, før du trykker «Nytt spørsmål»."""
    tema = (tema or "").strip()
    okt = OKTER.get(request.session_hash)
    stil = riktig_stil(type_, stil)
    if type_ == "modeller" and fag not in MODELLFAG:
        return
    if (tema or type_ in ("repetisjon", "modeller")) and not (okt and okt["nokkel"] == (fag, tema, type_, stil)):
        _ny_okt(request, fag, tema, type_, stil)


def _knapper(okt, besvart: bool, kortsvar: bool = False):
    """Svar · Nytt spørsmål · Prøv igjen · Ta feilsvarene på nytt. Etter svar blir «Nytt spørsmål» hovedknappen."""
    feil = len(okt["feil"]) if okt else 0
    return (gr.update(interactive=not besvart, variant="secondary" if besvart else "primary"),
            gr.update(variant="primary" if besvart else "secondary"),
            gr.update(visible=besvart and kortsvar),
            gr.update(visible=besvart and feil > 0, value=f"🔁 Ta feilsvarene på nytt nå ({feil})"))


INGEN_ENDRING = (gr.update(),) * 4


def _vis(okt, fag, element):
    """Viser et spørsmål (fra køen eller fra en øvingsrunde med feilsvar)."""
    q, bit, sid, kilde = element
    if isinstance(sid, dict):             # nytt spørsmål: lagres nå som du faktisk får se det
        sid = lagre_sporsmal(koble(), **sid)
    fag = q.get("fag") or fag             # feilsvar fra et annet fag beholder sitt eget fagmerke
    okt.update(q=q, bit=bit, sid=sid, kilde=kilde, nr=okt["nr"] + 1)
    kort = _sporsmalskort(fag, q, okt["nr"], kilde)
    if okt.get("ovelse"):
        kort = kort.replace('<div class="topplinje">', '<div class="topplinje"><span class="varsel">🔁 Øvingsrunde – teller ikke</span>', 1)
    skjul = gr.update(visible=False)
    if q["type"] == "flervalg":
        valg = [f"{b}) {a}" for b, a in zip(BOKSTAVER, q["alternativer"])]
        felter = (gr.update(choices=valg, value=None, visible=True), skjul)
        flere = skjul
    elif q["type"] == "avkrysning":
        felter = (skjul, skjul)
        flere = gr.update(choices=q["alternativer"], value=[], visible=True)
    else:
        etikett = ("Din analyse: bruk hvert element i modellen på casen" if q.get("stil") == "bruk modellen"
                   else "Ditt svar (2–4 setninger)")
        felter = (skjul, gr.update(value="", visible=True, label=etikett, lines=7 if "analyse" in etikett else 4))
        flere = skjul
    return (kort, *felter, "", _poeng(okt), *_knapper(okt, besvart=False), flere)


def nytt_sporsmal(fag, tema, type_, stil, request: gr.Request):
    skjul = gr.update(visible=False)
    okt = OKTER.get(request.session_hash)
    if okt and okt["runde"]:                # øvingsrunde med feilsvar går først
        okt["ovelse"] = True
        return _vis(okt, okt["runde_fag"], okt["runde"].pop(0))
    tema = (tema or "").strip()
    stil = riktig_stil(type_, stil)
    if type_ == "modeller" and fag not in MODELLFAG:
        return (_melding("Modeller og teorier finnes for MRK1001 og ORG1100. For BØA: bruk fanen «BØA-formler»."),
                skjul, skjul, "", "", *INGEN_ENDRING, skjul)
    if type_ not in ("repetisjon", "modeller") and not tema:
        return (_melding("Velg et tema først, eller skriv ditt eget, f.eks. «prisstrategi»."), skjul, skjul, "", "",
                *INGEN_ENDRING, skjul)
    nokkel = (fag, tema, type_, stil)
    if not okt or okt["nokkel"] != nokkel:
        okt = _ny_okt(request, fag, tema, type_, stil)
    okt["ovelse"] = False
    element = okt["ko"].get()
    if element is SLUTT:
        okt["stopp"].set()
        okt["nokkel"] = None
        tekst = (f"⚠️ {okt['feilmelding']}" if okt.get("feilmelding")
                 else "Ingen spørsmål skal repeteres nå. 🎉" if type_ == "repetisjon"
                 else "Du har vært gjennom alle modellene i utvalget. Trykk «Nytt spørsmål» for en ny runde."
                 if type_ == "modeller"
                 else f"Fant ikke flere gode spørsmål om «{tema}». Prøv et bredere tema.")
        return _melding(tekst), skjul, skjul, "", _poeng(okt), *_knapper(okt, besvart=True), skjul
    return _vis(okt, fag, element)


def ta_feil_paa_nytt(fag, request: gr.Request):
    """Stiller feilsvarene fra denne økten på nytt med en gang. Teller ikke: de kommer i repetisjonen som før."""
    okt = OKTER.get(request.session_hash)
    if not okt or not okt["feil"]:
        return (_melding("Ingen feilsvar å ta på nytt."), gr.update(), gr.update(), "", _poeng(okt), *INGEN_ENDRING,
                gr.update())
    for q, bit, sid, kilde in okt["feil"]:
        if q["type"] in ("flervalg", "avkrysning"):     # stokk på nytt, så du ikke bare husker bokstaven
            q = {**q, "alternativer": random.sample(q["alternativer"], len(q["alternativer"]))}
        okt["runde"].append((q, bit, sid, kilde))
    okt["feil"] = []
    okt["runde_fag"] = fag
    okt["ovelse"] = True
    return _vis(okt, fag, okt["runde"].pop(0))


def _tilbakemelding(riktig: bool, dom: str, innhold: str) -> str:
    return (f'<div class="tilbakemelding {"riktig" if riktig else "feil"}">'
            f'<div class="dom">{"✅" if riktig else "❌"} {dom}</div>{innhold}</div>')


def _vurdering_html(q, v) -> tuple[str, str]:
    """(dom, innhold) for et vurdert kortsvar."""
    dom = f"{'Godkjent' if v['riktig'] else 'Ikke godkjent'} · {sum(v['dekket'])} av {len(v['dekket'])} nøkkelpunkter"
    if v["feil"]:
        dom += f" · {len(v['feil'])} {'påstand' if len(v['feil']) == 1 else 'påstander'} å sjekke"
    punkter = "".join(f"<li>{'✓' if d else '·'} {escape(p)}</li>" for p, d in zip(q["nokkelpunkter"], v["dekket"]))
    for f, sitat in zip(v["feil"], v.get("feil_sitat") or [""] * len(v["feil"])):
        merke = "✗ Brukt i strid med modellen" if modellquiz.er_case_oppgave(q) else "⚠️ Sjekk mot notatet"
        punkter += (f"<li>{merke}: «{escape(f)}»"
                    + (f"<br><span class=notis>Notatet sier: «{escape(sitat)}»</span>" if sitat else "") + "</li>")
    innhold = (f"<ul>{punkter}</ul><p>{escape(v['tilbakemelding'])}</p>"
               f'<div class="modellsvar"><b>Modellsvar:</b> {escape(q["modellsvar"])}</div>'
               f'<p class="notis">Vurderingen er en indikasjon fra en liten modell, ikke en karakter.</p>')
    return dom, innhold


def _vurder(q, svar, kildetekst):
    """Case-analyser rettes mot elementene i modellen, vanlige kortsvar mot notatet."""
    return (modellquiz.vurder_case if modellquiz.er_case_oppgave(q) else vurder)(q, svar, kildetekst)


def svar_quiz(valgt, tekst, flere, request: gr.Request):
    okt = OKTER.get(request.session_hash)
    if not okt or "q" not in okt:
        return _melding("Trykk «Nytt spørsmål» først."), _poeng(okt), *INGEN_ENDRING
    q, bit, sid = okt["q"], okt["bit"], okt["sid"]
    if q["type"] == "avkrysning":
        modellvalg = signaler.er_modellvalg(q)
        if not flere:
            return (_melding("Kryss av for modellene som passer." if modellvalg
                             else "Kryss av for elementene som hører til modellen."), _poeng(okt), *INGEN_ENDRING)
        riktig, glemt, gale = modellquiz.rett_avkrysning(q, flere)
        svar = json.dumps(flere, ensure_ascii=False)
        funnet = len(q["fasit"]) - len(glemt)
        if modellvalg:
            dom = (f"{'Godkjent' if riktig else 'Ikke godkjent'}: du fant {funnet} av {len(q['fasit'])} modeller"
                   + (f", og valgte {len(gale)} som ikke passer" if gale else "")
                   + ("" if riktig or gale else f". Du trenger {signaler.krav(len(q['fasit']))}"))
        else:
            dom = "Riktig! Du fant alle elementene." if riktig else (
                f"Ikke helt. {funnet} av {len(q['fasit'])} riktige"
                + (f", og {len(gale)} som ikke hører til" if gale else ""))
        linjer = "".join(f"<li>✓ {escape(a)}</li>" for a in q["fasit"] if a not in glemt)
        linjer += "".join(f"<li>· Du glemte: {escape(a)}</li>" for a in glemt)
        linjer += "".join(f"<li>✗ {'Ikke i fasiten' if modellvalg else 'Hører ikke til'}: {escape(a)}</li>" for a in gale)
        innhold = f"<ul>{linjer}</ul><p>{escape(q.get('forklaring') or '').replace(chr(10), '<br>')}</p>"
        tilbakemelding = None
    elif q["type"] == "flervalg":
        if not valgt:
            return _melding("Velg et alternativ."), _poeng(okt), *INGEN_ENDRING
        svar = valgt[3:]
        riktig = svar == q["fasit"]
        dom = "Riktig!" if riktig else f"Feil. Riktig svar: {escape(q['fasit'])}"
        innhold = f"<p>{escape(q.get('forklaring') or '')}</p>"
        tilbakemelding = None
    else:
        if len((tekst or "").split()) < 3:
            return _melding("Skriv et svar på 2–4 setninger."), _poeng(okt), *INGEN_ENDRING
        svar = tekst
        try:
            v = _vurder(q, svar, bit.tekst)
        except (TimeoutError, ValueError, SprakmodellFeil):
            return (_tilbakemelding(False, "Vurderingen feilet",
                                    f'<div class="modellsvar"><b>Sammenlign selv med modellsvaret:</b><br>'
                                    f'{escape(q["modellsvar"])}</div>'), _poeng(okt), *INGEN_ENDRING)
        riktig, tilbakemelding = v["riktig"], v["tilbakemelding"]
        dom, innhold = _vurdering_html(q, v)

    element = (q, bit, sid, okt["kilde"])
    sitat = f" «{escape(q['sitat'])}»" if q.get("sitat") else ""
    innhold += f'<div class="kilde">Kilde: {escape(okt["kilde"])}{sitat}'
    if okt.get("ovelse"):
        innhold += "<br>Øvingsrunde: teller ikke. Spørsmålet kommer fortsatt i repetisjonen.</div>"
    else:
        neste = lagre_resultat(koble(), sid, svar, riktig, tilbakemelding)
        okt["besvart"] += 1
        okt["riktige"] += int(riktig)
        innhold += f"<br>Kommer igjen {neste:%d.%m} for repetisjon.</div>" if neste else "</div>"
    if not riktig:
        okt["feil"].append(element)
    okt["forrige"] = (q, bit)                 # til «Prøv igjen»
    del okt["q"]
    return _tilbakemelding(riktig, dom, innhold), _poeng(okt), *_knapper(okt, True, q["type"] == "kortsvar")


def prov_igjen(tekst, request: gr.Request):
    """Nytt forsøk på et kortsvar etter at du har sett nøkkelpunktene. Vurderes, men lagres ikke."""
    okt = OKTER.get(request.session_hash)
    if not okt or "forrige" not in okt:
        return _melding("Svar på et kortsvar først.")
    q, bit = okt["forrige"]
    if len((tekst or "").split()) < 3:
        return _melding("Skriv det nye svaret ditt i feltet over, og trykk «Prøv igjen».")
    try:
        v = _vurder(q, tekst, bit.tekst)
    except (TimeoutError, ValueError, SprakmodellFeil):
        return _melding("Vurderingen feilet. Prøv igjen.")
    dom, innhold = _vurdering_html(q, v)
    return _tilbakemelding(v["riktig"], "Nytt forsøk (teller ikke) · " + dom, innhold)


# ---------- Flashcards ----------

def _kort(kid):
    return koble().execute("SELECT * FROM sporsmal WHERE id = ?", (kid,)).fetchone()


def _flashcard(ko, vis_svar=False) -> str:
    if not ko:
        return _melding("Ingen kort å øve på nå. Velg et tema og trykk «Start» for å lage nye kort.")
    k = _kort(ko[0])
    svar = (f'<div class="svar">{escape(k["fasit"])}<div class="kilde">Kilde: {escape(k["kilde"])}</div></div>'
            if vis_svar else "")
    return (f'<div class="kort flashcard" style="--fag:{farge(k["fag"])}"><div class="topplinje">'
            f'<span>{merke(k["fag"])} &nbsp;{escape(kort_tema(k["tema"]))}</span><span>{len(ko)} kort igjen</span></div>'
            f'<div class="sporsmal">{escape(k["sporsmal"])}</div>{svar}</div>')


def hent_kort(fag, tema, nye):
    db = koble()
    tema = "" if not tema or tema == ALLE_KORT else tema
    if nye and tema.strip():
        try:
            lag_nye_kort(db, fag, tema, int(nye))
        except SprakmodellFeil as feil:       # kortene du har fra før, kan fortsatt øves
            gr.Warning(str(feil))
    ko = [k["id"] for k in forfalte(db, fag, tema.strip() or None)]
    return ko, _flashcard(ko), gr.update(visible=bool(ko)), gr.update(visible=False)


def snu(ko):
    if not ko:
        return _flashcard(ko), gr.update(visible=False), gr.update(visible=False)
    return _flashcard(ko, vis_svar=True), gr.update(visible=False), gr.update(visible=True)


def vurder_kort(vurdering, ko):
    if ko:
        kid = ko.pop(0)
        lagre_resultat(koble(), kid, svar=vurdering, riktig=vurdering in ("greit", "lett"), vurdering=vurdering)
        if vurdering == "igjen":
            ko.append(kid)
    return ko, _flashcard(ko), gr.update(visible=bool(ko)), gr.update(visible=False)


# ---------- I dag og plan ----------

def _dagens(db):
    return [dict(b) for b in blokker_for(db, date.today()) if b["fag"] != "-"]


def _blokk_html(b) -> str:
    status = {"fullfort": ("fullfort", "✓ Fullført"), "hoppet_over": ("fullfort", "Hoppet over")}.get(b["status"])
    klasse, tekst = status or ("", f"{b['minutter']} min")
    return (f'<div class="blokk {klasse}" style="--fag:{farge(b["fag"])}">'
            f'<div class="ikon">{IKONER.get(b["ovingsmate"], "📘")}</div>'
            f'<div class="tekst"><div class="tema">{escape(kort_tema(b["tema"]))}</div>'
            f'<div class="meta">{merke(b["fag"], lys=True)} &nbsp;{OVINGSNAVN.get(b["ovingsmate"], b["ovingsmate"])}'
            f'{" · " + escape(b["grunn"]) if b.get("grunn") else ""}</div></div>'
            f'<div class="status">{tekst}</div></div>')


def _uke_html(db) -> str:
    dager = []
    for i in range(1, 8):
        dag = date.today() + timedelta(days=i)
        blokker = [b for b in blokker_for(db, dag) if b["fag"] != "-" and b["status"] == "planlagt"]
        biter = "".join(f'<div class="bit" style="--fag:{farge(b["fag"])}" title="{escape(b["tema"])}">'
                        f'{escape(kort_tema(b["tema"]))}</div>' for b in blokker)
        dager.append(f'<div class="dag"><div class="navn">{UKEDAGER[dag.weekday()][:3]} <span>{dag:%d.%m}</span></div>'
                     f'{biter or "<div class=bit>fri</div>"}</div>')
    return f'<div class="uke">{"".join(dager)}</div>'


_PLANLAGT = {}          # datoen planen sist ble lagt på nytt i denne appen


def _oppfrisk_plan(db):
    """Én gang per dag legges planen på nytt, så den følger det du faktisk har øvd på (også uten «Ferdig»).
    Har du allerede gjort eller hoppet over noe i dag, står dagens blokker urørt, og resten legges fra i morgen."""
    i_dag = date.today()
    if _PLANLAGT.get("dato") == i_dag:
        return
    _PLANLAGT["dato"] = i_dag
    urort = all(b["status"] == "planlagt" for b in blokker_for(db, i_dag))
    lag_og_lagre(db, i_dag if urort else i_dag + timedelta(days=1))


def vis_plan():
    db = koble()
    _oppfrisk_plan(db)
    if not _dagens(db):
        lag_og_lagre(db)
    dagens = _dagens(db)
    igjen = sum(b["status"] == "planlagt" for b in dagens)
    feilsvar = len(forfalte_sporsmal(db))
    varsel = f' <span class="varsel">🔁 {feilsvar} feilsvar venter på repetisjon</span>' if feilsvar else ""
    overskrift = (f'<div class="overskrift"><h2>I dag · {UKEDAGER[date.today().weekday()].capitalize()} {date.today():%d.%m}</h2>'
                  f'<span class="info">{igjen} av {len(dagens)} blokker igjen</span>{varsel}</div>')
    return overskrift, dagens, _uke_html(db)


def ov_paa_blokk(blokk_id):
    """Fyller ut riktig fane med fag og tema fra blokken, og bytter til den."""
    b = koble().execute("SELECT * FROM plan WHERE id = ?", (blokk_id,)).fetchone()
    return ov_paa(b["fag"], b["tema"], b["ovingsmate"])


def ov_paa(fag, tema, ovingsmate):
    """Tom tema betyr alle kort som skal repeteres (flashcards) eller feilsvarene (feilsvar)."""
    if ovingsmate == "flashcards":
        return (gr.Tabs(selected="kort"), gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(value=fag), gr.update(choices=temaer_for(fag), value=tema or ALLE_KORT))
    type_ = {"flervalg": "flervalg", "feilsvar": "repetisjon", "modeller": "modeller"}.get(ovingsmate, "kortsvar")
    stil = {**stilvalg(type_), "value": "blandet"} if type_ == "kortsvar" else stilvalg(type_, fag)
    return (gr.Tabs(selected="quiz"), gr.update(value=fag),
            gr.update(choices=temaer_for(fag, med_alle=False), value=tema or None),
            gr.update(value=type_), stil, gr.update(), gr.update())


def fullfort(blokk_id):
    db = koble()
    marker_fullfort(db, blokk_id)
    lag_og_lagre(db, date.today() + timedelta(days=1))   # mestringen fra økten styrer resten
    return vis_plan()


def hopp_over_i_dag():
    hopp_over(koble(), date.today())
    return vis_plan()


def angre_i_dag():
    angre_hopp_over(koble(), date.today())
    return vis_plan()


def _forklaring_html(f, oppsummering) -> str:
    totalt = sum(x["blokker"] for x in f["fag"]) or 1
    rader = "".join(
        f'<div class="planfag" style="--fag:{farge(x["fag"])}"><div class="topp-linje">{merke(x["fag"])}'
        f'<span>eksamen {x["dato"]:%d.%m} · om <b>{x["dager_igjen"]} dager</b></span>'
        f'<span class="timer">{x["blokker"]} blokker · {x["timer"]:.0f} t</span></div>'
        f'<div class="stolpe"><div style="width:{x["blokker"] / totalt:.0%}"></div></div>'
        f'<div class="fase">Fase: {escape(x["fase"])}'
        + (f' · svake temaer først: {escape(", ".join(x["svake"]))}' if x["svake"] else "") + "</div></div>"
        for x in f["fag"])
    regler = (f"<ul><li>Faget med nærmest eksamen får mest tid. Andelen øker jo færre dager som er igjen.</li>"
              f"<li>De siste {f['repetisjonsdager']} dagene før en eksamen brukes bare på det faget.</li>"
              f"<li>Øvingen endrer seg mot eksamen: først gjenkjenne (flashcards), så hente frem (flervalg), "
              f"siste uke forklare med egne ord (kortsvar).</li>"
              f"<li>De siste tre ukene er annenhver blokk i MRK og ORG modelløving: du kjenner igjen modellen "
              f"i en case og bruker den, slik eksamen krever.</li>"
              f"<li>Temaer du ikke har øvd på eller er svak på, kommer oftere. Temaer du nettopp har øvd på, venter litt.</li>"
              f"<li>Når du trykker «Ferdig», legges planen på nytt fra i morgen ut fra mestringen din.</li></ul>")
    return (f'<div class="planforklaring"><h3>De neste {f["dager"]} dagene · {f["blokker"]} blokker à '
            f'{f["blokk_minutter"]} min</h3>{rader}<h4>Slik er planen laget</h4>{regler}'
            f'<h4>Oppsummering</h4><p>{oppsummering}</p></div>')


def spor_veileder(melding):
    """Kjører studieveilederen i en egen tråd og viser stegene etter hvert. Returnerer svaret og øktene."""
    if not melding.strip():
        melding = "Hva bør jeg øve på nå?"
    steg, ferdig = [], {}
    trad = threading.Thread(target=lambda: ferdig.update(svar=kjor_veileder(melding, steg.append)), daemon=True)
    trad.start()
    vist = -1
    while trad.is_alive():
        if len(steg) != vist:
            vist = len(steg)
            yield "*Veilederen ser på dataene dine …*\n\n" + _agentsteg(steg), []
        trad.join(0.3)
    svar = ferdig.get("svar")
    if not svar:
        yield "Veilederen stoppet uventet. Prøv igjen.", []
        return
    linjer = re.sub(r"(?<!\n)\n(?!\n)", "  \n", svar.tekst)      # behold linjeskiftene i listen over økter
    tekst = (f"{linjer}\n\n<details><summary>Slik jobbet veilederen ({len(svar.steg)} steg)</summary>\n\n"
             f"{_agentsteg(svar.steg)}\n\n</details>")
    okt = [{"fag": b.fag, "tema": b.tema, "ovingsmate": b.ovingsmate, "minutter": b.minutter, "status": "planlagt",
            "grunn": b.grunn} for b in svar.okt]
    yield tekst, okt


def forklar_plan():
    from src.planlegger import forklar, planfakta
    db = koble()
    f = planfakta(db)
    yield _forklaring_html(f, "<i>Språkmodellen skriver en oppsummering …</i>")
    try:
        tekst = escape(forklar(db))
    except Exception:   # tidsavbrudd eller Ollama ikke startet: tallene over står uansett
        tekst = "<i>Språkmodellen svarte ikke. Tallene over er likevel riktige.</i>"
    yield _forklaring_html(f, tekst)


# ---------- Formler (BØA) ----------

ALLE_TEMAER = "Alle temaer"
FORMELTYPER = {"Blandet": "blandet", **{navn: t for t, navn in formler.TYPER.items()}}


def _md(tekst: str) -> str:
    """Forklaringene fra formler.py: **fet** og avsnitt, ellers ren tekst."""
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(tekst))
    return "".join(f"<p>{a.replace(chr(10), '<br>')}</p>" for a in html.split("\n\n"))


def vis_formelark() -> str:
    seksjoner = []
    for tema, rader in formler.formelark():
        kort = []
        for r in rader:
            snudd = "".join(f"<span>{escape(t)}</span>" for t in r["snudd"])
            naboer = f'<div class="naboer">Henger sammen med: {escape(", ".join(r["henger_sammen"]))}</div>' \
                if r["henger_sammen"] else ""
            kort.append(f'<div class="formel"><div class="navn">{escape(r["navn"])}</div>'
                        f'<div class="uttrykk">{escape(r["formel"])}</div>'
                        f'<div class="bruk">{escape(r["bruk"])}</div>'
                        f'{f"<div class=snudd><b>Snudd:</b> {snudd}</div>" if snudd else ""}'
                        f'<div class="ordliste">{escape(r["variabler"])}</div>{naboer}'
                        f'<div class="kilde">📖 {escape(r["kilde"])}</div></div>')
        seksjoner.append(f'<h3>{escape(tema)}</h3><div class="formler">{"".join(kort)}</div>')
    antall = sum(len(r) for _, r in formler.formelark())
    return (f'<div class="formelark" style="--fag:{farge(formler.FAG)}"><p class="info">{antall} formler fra '
            f'BØA-pensumet, med kilde. «Snudd» viser formelen løst for hver av de andre størrelsene.</p>'
            f'{"".join(seksjoner)}</div>')


def _formelkort(o, nr) -> str:
    return (f'<div class="kort" style="--fag:{farge(formler.FAG)}"><div class="topplinje">'
            f'<span>{merke(formler.FAG)} &nbsp;{escape(o.tema)}</span>'
            f'<span>Oppgave {nr} · {escape(formler.TYPER[o.type])}</span></div>'
            f'<div class="sporsmal">{escape(o.tekst)}</div></div>')


def ny_formeloppgave(tema, type_, okt):
    okt = dict(okt or {"besvart": 0, "riktige": 0, "nr": 0})
    o = formler.ny_oppgave(FORMELTYPER.get(type_, "blandet"), None if tema in (None, ALLE_TEMAER) else tema)
    okt.update(oppgave=o, nr=okt["nr"] + 1, svart=False)
    valg = gr.update(choices=o.alternativer, value=None, visible=bool(o.alternativer))
    tekst = gr.update(value="", visible=o.tallsvar,
                      label="Ditt svar" + (" (i %)" if o.mal and formler.VARIABLER[o.mal].prosent else ""))
    return _formelkort(o, okt["nr"]), valg, tekst, "", _poeng(okt), okt


def svar_formel(valgt, tekst, okt):
    o = (okt or {}).get("oppgave")
    if not o:
        return _melding("Trykk «Ny oppgave» først."), gr.update(), okt
    svar = (tekst if o.tallsvar else valgt) or ""
    if not svar.strip():
        return _melding("Skriv eller velg et svar først."), gr.update(), okt
    riktig = formler.sjekk(o, svar)
    if not okt.get("svart"):                   # bare første forsøk teller i mestringen
        okt = {**okt, "svart": True, "besvart": okt["besvart"] + 1, "riktige": okt["riktige"] + riktig}
        db = koble()
        fasit = formler.med_enhet(o.fasit, o.mal) if o.tallsvar else o.fasit
        sid = lagre_sporsmal(db, fag=formler.FAG, tema=o.tema, ovingsmate="formel", sporsmal=o.tekst, fasit=fasit,
                             kilde=f"{formler.FAG}/{o.kilder[0]}", alternativer=o.alternativer or None,
                             forklaring=o.forklaring)
        lagre_resultat(db, sid, svar, riktig)
    fasit = formler.med_enhet(o.fasit, o.mal) if o.tallsvar else o.fasit
    dom = "✅ Riktig!" if riktig else f"❌ Riktig svar: {escape(fasit)}"
    kilder = "".join(f"<div>📖 {escape(formler.FAG)}/{escape(k)}</div>" for k in dict.fromkeys(o.kilder))
    html = (f'<div class="tilbakemelding {"riktig" if riktig else "feil"}"><div class="dom">{dom}</div>'
            f'{_md(o.forklaring)}<div class="kilde">{kilder}</div></div>')
    return html, _poeng(okt), okt


# ---------- Eksamensmodus ----------

EKSAMENSFAG = [f for f in FAG if eksamensmodus.har_eksamensmodus(f)]
TIDLIGERE, NYHET = "Tidligere eksamen", "Fersk nyhetssak"


def eksamensvalg(fag, kilde, ferske=False):
    """Fyller menyen med tidligere eksamenscaser, eller med nyhetssakene som passer faget best."""
    if kilde == TIDLIGERE:
        navn = list(signaler.caser(fag))
        return gr.update(choices=navn, value=navn[0] if navn else None, label="Case"), []
    saker = nyheter.for_fag(fag, 20, ferske)
    if not saker:
        gr.Warning("Fant ingen nyhetssaker. Sjekk at du er på nett, og trykk «Hent nyheter».")
    valg = [n.etikett for n in saker]
    return gr.update(choices=valg, value=valg[0] if valg else None, label="Nyhetssak (de mest relevante først)"), \
        [vars(n) for n in saker]


def _eksamenskort(case) -> str:
    linjer = lambda s: escape(s).replace(chr(10), "<br>")
    oppgaver = "".join(f"<li>{escape(o)}</li>" for o in case.oppgaver)
    lenke = (f' · <a href="{escape(case.lenke)}" target="_blank" rel="noopener noreferrer">les saken hos kilden</a>'
             if case.lenke else "")
    return (f'<div class="kort" style="--fag:{farge(case.fag)}"><div class="topplinje"><span>{merke(case.fag)} &nbsp;'
            f'Eksamensmodus</span><span>{len(case.tekst.split())} ord</span></div>'
            f'<div class="sporsmal">📝 {escape(case.tittel)}</div><div class="casetekst">{linjer(case.tekst)}</div>'
            + (f'<div class="oppgaver"><b>Oppgaver</b><ol>{oppgaver}</ol></div>' if oppgaver else "")
            + f'<div class="fra">📖 {escape(case.kilde)}{lenke}</div></div>')


def start_eksamen(fag, kilde, valg, saker):
    skjul = gr.update(visible=False)
    if not valg:
        return _melding("Velg en case først."), skjul, skjul, "", None
    if kilde == TIDLIGERE:
        case = eksamensmodus.tidligere(fag, valg)
    else:
        sak = next((s for s in saker or [] if nyheter.Nyhet(**s).etikett == valg), None)
        case = eksamensmodus.fra_nyhet(fag, nyheter.Nyhet(**sak)) if sak else None
        if case is None:
            return (_melding("Saken kunne ikke hentes, eller den er for kort til å være en case (kanskje bak "
                             "betalingsmur). Velg en annen sak."), skjul, skjul, "", None)
    okt = {"case": case, "start": datetime.now().isoformat(timespec="seconds")}
    return (_eksamenskort(case), gr.update(value="", visible=True), gr.update(visible=True),
            '<div class="tom">Skriv hele besvarelsen i feltet. Bruk gjerne overskrifter per oppgave. '
            'Du har boka med på MRK-eksamen, ikke på ORG.</div>', okt)


def _eksamensresultat_html(case, r, minutter) -> str:
    def rad(p):
        if p.brukt:
            el = (f' <span class="notis">({len(p.elementer)} av {p.antall_elementer} elementer nevnt)</span>'
                  if p.antall_elementer else "")
            return f"<li>✓ <b>{escape(p.modell)}</b>{el}</li>"
        return (f"<li>· <b>{escape(p.modell)}</b> mangler<br><span class=notis>Hvorfor den hører hjemme: "
                f"{escape(p.hvorfor)} ({escape(p.signal)})</span></li>")
    brukt = sum(p.brukt for p in r.punkter)
    dom = (f"{'Godkjent' if r.godkjent else 'Ikke godkjent'} · {brukt} av {len(r.punkter)} modeller fra fasiten "
           f"(du trenger {r.krav}) · {r.ord} ord på {minutter} min")
    punkter = "".join(rad(p) for p in sorted(r.punkter, key=lambda p: not p.brukt))
    feller = "".join(f"<li>✗ <b>{escape(n)}</b> gir lite uttelling her: {escape(h)}</li>" for n, h in r.feller)
    sjekk = "".join(f"<li>{'✓' if ok else '·'} {escape(t)}</li>" for t, ok in r.sjekk)
    k = r.kommentar or {}
    kommentar = "".join(f"<p><b>{tittel}</b></p><ul>{''.join(f'<li>{escape(x)}</li>' for x in k[n])}</ul>"
                        for n, tittel in (("bra", "Dette gjør du godt"), ("forbedre", "Dette bør du forbedre")) if k.get(n))
    if not kommentar:
        kommentar = '<p class="notis">Språkmodellen ga ingen kommentar denne gangen. Rettingen over står likevel.</p>'
    fasit = ("Fasiten er modellene oppgaveordene peker på i signalkatalogen. En nyhetssak har ingen sensorveiledning."
             if case.type == "nyhet" else "Fasiten er hentet fra sensorveiledning, løsningsforslag eller A-besvarelse.")
    return _tilbakemelding(r.godkjent, dom,
                           f"<p><b>Modellene i fasiten</b></p><ul>{punkter}{feller}</ul>"
                           f"<p><b>Det sensor ser etter</b></p><ul>{sjekk}</ul>{kommentar}"
                           f'<p class="notis">{fasit} Rettingen ser etter om modellene er brukt, ikke hvor godt. '
                           f"Den er en indikasjon, ikke en karakter.</p>")


def lever_eksamen(svar, okt):
    """Retter besvarelsen og lagrer den, så den teller i dekningsoversikten."""
    if not okt or not okt.get("case"):
        yield _melding("Trykk «Start» først."), okt
        return
    if len((svar or "").split()) < 50:
        yield _melding("Besvarelsen er for kort til å rettes. Skriv minst noen avsnitt."), okt
        return
    case = okt["case"]
    yield _melding("Retter besvarelsen … (Python sjekker modellene, språkmodellen skriver en kommentar)"), okt
    r = eksamensmodus.rett(case, svar)
    minutter = round((datetime.now() - datetime.fromisoformat(okt["start"])).total_seconds() / 60)
    if not okt.get("levert"):                  # bare første levering lagres
        db = koble()
        sid = lagre_sporsmal(db, fag=case.fag, tema=eksamensmodus.TEMA, ovingsmate=dekning.EKSAMEN,
                             sporsmal=f"📝 {case.tittel}" + "".join(f"\n{nr}. {o}" for nr, o in enumerate(case.oppgaver, 1)),
                             fasit=json.dumps([p.modell for p in r.punkter], ensure_ascii=False), kilde=case.kilde,
                             modell=modellnavn())
        lagre_resultat(db, sid, svar, r.godkjent, json.dumps(
            {"brukt": r.brukt, "mangler": r.mangler, "feller": [n for n, _ in r.feller], "ord": r.ord,
             "minutter": minutter}, ensure_ascii=False))
        okt = {**okt, "levert": True}
    yield _eksamensresultat_html(case, r, minutter), okt


# ---------- Mestring ----------

def _dekning_html(db, fag) -> str:
    """Eksamensmodellene i faget, tyngst først, med hva du har øvd på: kjenn, case og funnet i en hel case."""
    rader = dekning.dekning(db, fag)
    if not rader:
        return ""
    brukt, alle = dekning.oppsummering(rader)

    def celle(t):
        if not t.forsok:
            return '<div class="tom-celle">–</div>'
        return f'<div class="{"ok" if t.riktige else "svak"}">{t.riktige}/{t.forsok}</div>'

    linjer = "".join(
        f'<div class="dekrad{"" if r.brukt_paa_case else " mangler"}">'
        f'<div>{escape(r.modell.navn)} <span class="kap">kap. {r.modell.kapittel}</span></div>'
        f'<div class="vekt" title="Antall eksamenscaser der modellen er fasit, pluss et halvt poeng per oppgaveord">'
        f'{r.treff:g}</div>{celle(r.kjenn)}{celle(r.case)}{celle(r.funnet)}</div>' for r in rader)
    return (f'<details class="dekning"><summary>🧩 Eksamensmodellene: <b>{brukt} av {alle}</b> brukt riktig på en case'
            f'</summary><p class="info">Modellene som har vært fasit på tidligere eksamener, de vanligste først. '
            f'Tallene er riktige/forsøk. Rader i rødt har du ennå ikke brukt eller funnet riktig i en case.</p>'
            f'<div class="dekrad hode"><div>Modell</div><div>På eksamen</div><div>Kjenn</div><div>Case</div>'
            f'<div>Funnet i case</div></div>{linjer}</details>')


def vis_mestring():
    db = koble()
    _, temaer, _ = last_eksamener()
    lagret = {(r["fag"], r["tema"]): r for r in db.execute("SELECT * FROM temaer")}
    kort = sum(1 for fag in FAG for k in forfalte(db, fag, None) if k["neste"])
    fliser = [f'<div class="flis" style="--fag:#e5484d"><div class="tall">{len(forfalte_sporsmal(db))}</div>'
              f'<div class="tekst">feilsvar venter</div></div>',
              f'<div class="flis" style="--fag:#3b82f6"><div class="tall">{kort}</div>'
              f'<div class="tekst">flashcards forfalt</div></div>']
    seksjoner = []
    for fag in [f for f in FAG if f in temaer]:
        rader, ovde = [], []
        egne = [t for (f, t) in lagret if f == fag and t not in temaer[fag]]   # temaer du har skrevet selv i quizen
        for tema in temaer[fag] + egne:
            r = lagret.get((fag, tema))
            if r and r["forsok"]:
                ovde.append(r["mestring"])
                rader.append(f'<div class="temarad"><div>{escape(kort_tema(tema))}</div>'
                             f'<div class="stolpe"><div style="width:{r["mestring"]:.0%}"></div></div>'
                             f'<div class="prosent">{r["mestring"]:.0%}</div>'
                             f'<div class="sist">{r["forsok"]} forsøk · {(r["sist_ovd"] or "")[8:10]}.{(r["sist_ovd"] or "")[5:7]}</div></div>')
            elif tema in temaer[fag]:
                rader.append(f'<div class="temarad uovd"><div>{escape(kort_tema(tema))}</div>'
                             f'<div class="stolpe"></div><div class="prosent">–</div><div class="sist">ikke øvd</div></div>')
        snitt = sum(ovde) / len(ovde) if ovde else None
        fliser.append(f'<div class="flis" style="--fag:{farge(fag)}"><div class="tall">'
                      f'{f"{snitt:.0%}" if snitt is not None else "–"}</div>'
                      f'<div class="tekst">{escape(NAVN.get(fag, fag))} · {len(ovde)} temaer øvd</div></div>')
        seksjoner.append(f'<div class="fagseksjon" style="--fag:{farge(fag)}"><h3>{merke(fag)} {escape(NAVN.get(fag, fag))}</h3>'
                         f'{"".join(rader)}{_dekning_html(db, fag)}</div>')
    return f'<div class="fliser">{"".join(fliser)}</div>{"".join(seksjoner)}'


# ---------- oppsett ----------

TEMA = gr.themes.Soft(primary_hue="indigo", neutral_hue="slate", radius_size="lg",
                      font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"])
CSS = (Path(__file__).parent / "app.css").read_text(encoding="utf-8")


def stilvalg(type_, fag=None):
    """Stil-menyen: kortsvar har forklar/hvorfor/…, modeller har kjenn/velg/bruk, og «finn modellene»
    for fag med signalkatalog (config/signaler_{fag}.yaml)."""
    if type_ == "modeller":
        ekstra = [(navn, verdi) for verdi, navn in signaler.TYPER.items()] if fag and signaler.har_signaler(fag) else []
        return gr.update(choices=MODELLSTILER + ekstra, value="blandet", label="Øvingsmåte", visible=True)
    return gr.update(choices=[*STILER, "blandet"], value="forklar", label="Stil", visible=type_ == "kortsvar")


def _kapitler(fag) -> list[str]:
    return [ALLE_KAPITLER] + [t for t in temaer_for(fag, med_alle=False) if kapittel_i(t)]


ARK = ["Modellark", "Signalark"]


def vis_modellark(fag, kapittel, ark="Modellark") -> str:
    kap = kapittel_i(kapittel) if kapittel != ALLE_KAPITLER else None
    if ark == "Signalark":
        if not signaler.har_signaler(fag):
            return f"*Ingen signalkatalog for {fag} ennå.*"
        return ("*Signalene er hentet fra sensorveiledninger, løsningsforslag og A-besvarelser til ekte eksamenscaser. "
                "Les et signal, se sitatet fra casen, og lær hvilken modell det peker på. Øv etterpå med «Finn signalet», "
                "«Finn modellene i en eksamenscase» og «Ny case (generert)».*\n\n" + signaler.signalark(fag, kap))
    tekst = modellark(fag, kap)
    antall = tekst.count("\n**")
    return (f"*{antall} modeller og teorier, hentet fra modellnotatene dine. Elementene er det du bruker "
            f"når du analyserer en case.*\n" + tekst)


def ov_paa_modeller(fag, kapittel):
    tema = kapittel if kapittel != ALLE_KAPITLER else None
    return (gr.Tabs(selected="quiz"), gr.update(value=fag),
            gr.update(choices=temaer_for(fag, med_alle=False), value=tema),
            gr.update(value="modeller"), stilvalg("modeller", fag))


def lag_app() -> gr.Blocks:
    with gr.Blocks(title="Pensumboten") as app:
        gr.HTML(topp)
        with gr.Tabs() as faner:
            with gr.Tab("📅 I dag", id="idag"):
                plan_overskrift = gr.HTML()
                plan_data = gr.State([])

                @gr.render(inputs=plan_data)
                def tegn_blokker(blokker):
                    if not blokker:
                        gr.HTML(_melding("Ingenting planlagt i dag – fridag eller etter siste eksamen."))
                        return
                    for b in blokker:
                        with gr.Row(elem_classes="blokk-rad"):
                            with gr.Column(scale=8, min_width=240):
                                gr.HTML(_blokk_html(b))
                            if b["status"] == "planlagt":
                                ov = gr.Button("Øv nå", variant="primary", size="sm", scale=0, min_width=84, elem_classes="blokk-knapp")
                                ferdig = gr.Button("✓ Ferdig", size="sm", scale=0, min_width=84, elem_classes="blokk-knapp")
                                ov.click(lambda bid=b["id"]: ov_paa_blokk(bid), None,
                                         [faner, quiz_fag, quiz_tema, quiz_type, quiz_stil, kort_fag, kort_temavalg])
                                ferdig.click(lambda bid=b["id"]: fullfort(bid), None, plan_ut)

                with gr.Row():
                    hopp_knapp = gr.Button("Hopp over i dag", size="sm")
                    angre_knapp = gr.Button("↩ Angre hopp over", size="sm")
                    forklar_knapp = gr.Button("💡 Forklar planen", size="sm")
                forklaring = gr.HTML()

                with gr.Group(elem_classes="panel veileder"):
                    gr.Markdown("#### 🧭 Studieveileder")
                    with gr.Row():
                        veileder_tekst = gr.Textbox(placeholder="Hva bør jeg øve på i kveld? Jeg har to timer.",
                                                    show_label=False, scale=6, container=False)
                        veileder_knapp = gr.Button("Spør", variant="primary", scale=1, min_width=80)
                veileder_ut = gr.Markdown(elem_classes="veileder-svar")
                veileder_okt = gr.State([])

                @gr.render(inputs=veileder_okt)
                def tegn_okt(okt):
                    for b in okt:
                        with gr.Row(elem_classes="blokk-rad"):
                            with gr.Column(scale=8, min_width=240):
                                gr.HTML(_blokk_html({**b, "tema": b["tema"] or OVINGSNAVN[b["ovingsmate"]]}))
                            ov = gr.Button("Øv nå", variant="primary", size="sm", scale=0, min_width=84,
                                           elem_classes="blokk-knapp")
                            ov.click(lambda f=b["fag"], t=b["tema"], m=b["ovingsmate"]: ov_paa(f, t, m), None,
                                     [faner, quiz_fag, quiz_tema, quiz_type, quiz_stil, kort_fag, kort_temavalg])

                gr.Markdown("#### Neste 7 dager")
                uke = gr.HTML()

            with gr.Tab("💬 Spør", id="spor"):
                samtale = gr.State([])
                utveksling = gr.State([])
                with gr.Row():
                    fag0 = startfag()
                    spor_fag = gr.Dropdown(FAG, value=fag0, label="Fag", scale=1)
                    spor_eksempel = gr.Checkbox(label="Ta med A-besvarelser (ikke fasit)", scale=2)
                    spor_agent = gr.Checkbox(label="BØA-agent: søker i pensum og regner med kalkulator", value=True,
                                             scale=2, visible=fag0 == AGENTFAG)
                chat = gr.Chatbot(height=480, elem_classes="chat", show_label=False,
                                  placeholder="**Spør om hva som helst i pensumet ditt.**<br>"
                                              "Svarene kommer bare fra dine egne filer, med kilde.<br>"
                                              "Du kan følge opp: «forklar enklere», «gi et eksempel», «hva med pull?»")
                with gr.Row():
                    spor_tekst = gr.Textbox(placeholder="Hva er en pull-strategi?", show_label=False, scale=6,
                                            container=False)
                    spor_knapp = gr.Button("Send", variant="primary", scale=1, min_width=80)
                tom_knapp = gr.Button("Ny samtale", size="sm")

            with gr.Tab("🎯 Quiz", id="quiz"):
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        quiz_fag = gr.Dropdown(FAG, value=fag0, label="Fag")
                        quiz_tema = gr.Dropdown(temaer_for(fag0, med_alle=False), value=None, label="Tema",
                                                allow_custom_value=True, scale=2,
                                                info="Velg fra listen, eller skriv ditt eget tema")
                        quiz_type = gr.Radio(QUIZTYPER, value="flervalg", label="Type", scale=3)
                        # allow_custom_value: når typen byttes, kan Gradio sende den gamle stilen ett øyeblikk
                        quiz_stil = gr.Dropdown([*STILER, "blandet"], value="forklar", label="Stil", visible=False,
                                                allow_custom_value=True)
                poeng = gr.HTML()
                quiz_sporsmal = gr.HTML(_melding("Velg fag og tema, og trykk «Nytt spørsmål»."))
                quiz_valg = gr.Radio(show_label=False, visible=False, elem_classes="svaralternativer")
                quiz_flere = gr.CheckboxGroup(show_label=False, visible=False, elem_classes="svaralternativer")
                quiz_tekst = gr.Textbox(label="Ditt svar (2–4 setninger)", lines=4, visible=False)
                with gr.Row():
                    svar_knapp = gr.Button("Svar", variant="primary")
                    prov_knapp = gr.Button("✍️ Prøv igjen (teller ikke)", visible=False)
                    nytt_knapp = gr.Button("Nytt spørsmål ➜")
                quiz_resultat = gr.HTML()
                feil_knapp = gr.Button("🔁 Ta feilsvarene på nytt nå", visible=False, size="sm")

            with gr.Tab("📝 Eksamen", id="eksamen"):
                eks_okt = gr.State(None)
                eks_saker = gr.State([])
                efag0 = fag0 if fag0 in EKSAMENSFAG else (EKSAMENSFAG or [fag0])[0]
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        eks_fag = gr.Dropdown(EKSAMENSFAG, value=efag0, label="Fag")
                        eks_kilde = gr.Radio([TIDLIGERE, NYHET], value=TIDLIGERE, label="Case fra", scale=2)
                        eks_valg = gr.Dropdown(list(signaler.caser(efag0)), label="Case", scale=3,
                                               value=next(iter(signaler.caser(efag0)), None))
                    with gr.Row():
                        eks_start = gr.Button("Start", variant="primary")
                        eks_hent = gr.Button("🔄 Hent nyheter", size="sm", visible=False)
                eks_case = gr.HTML(_melding("Velg en tidligere eksamen eller en fersk nyhetssak, og trykk «Start». "
                                            "Du får hele casen med oppgaver, skriver én besvarelse, og får den rettet "
                                            "mot modellene sensor ser etter."))
                eks_svar = gr.Textbox(label="Din besvarelse", lines=18, visible=False,
                                      placeholder="Oppgave 1\n…\n\nOppgave 2\n…")
                eks_lever = gr.Button("Lever besvarelsen", variant="primary", visible=False)
                eks_resultat = gr.HTML()

            with gr.Tab("🗂️ Flashcards", id="kort"):
                ko = gr.State([])
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        kort_fag = gr.Dropdown(FAG, value=fag0, label="Fag")
                        kort_temavalg = gr.Dropdown(temaer_for(fag0), value=ALLE_KORT, label="Tema",
                                                    allow_custom_value=True, scale=2,
                                                    info="Velg fra listen, eller skriv ditt eget tema")
                        kort_nye = gr.Number(value=6, precision=0, label="Lag nye kort først")
                hent_knapp = gr.Button("Start", variant="primary")
                flashcard = gr.HTML(_melding("Velg fag og tema, og trykk «Start»."))
                with gr.Row(visible=False) as snu_rad:
                    snu_knapp = gr.Button("Snu kortet", variant="primary", size="lg")
                with gr.Row(visible=False) as vurder_rad:
                    vurderingsknapper = [gr.Button(v, size="lg", elem_classes=f"v-{v}")
                                         for v in ("igjen", "vanskelig", "greit", "lett")]

            with gr.Tab("🧮 BØA-formler", id="formler"):
                with gr.Tabs():
                    with gr.Tab("Trening"):
                        formel_okt = gr.State(None)
                        with gr.Group(elem_classes="panel"):
                            with gr.Row():
                                formel_tema = gr.Dropdown([ALLE_TEMAER, *[t for t in formler.TEMAREKKEFOLGE
                                                          if any(f.tema == t for f in formler.FORMLER)]],
                                                          value=ALLE_TEMAER, label="Tema", scale=2)
                                formel_type = gr.Dropdown(list(FORMELTYPER), value="Blandet", label="Type", scale=1)
                        formel_poeng = gr.HTML()
                        formel_kort = gr.HTML(_melding("Velg tema og type, og trykk «Ny oppgave». "
                                                       "Fasiten er regnet ut i Python, så den er alltid riktig."))
                        formel_valg = gr.Radio(show_label=False, visible=False, elem_classes="svaralternativer")
                        formel_tekst = gr.Textbox(label="Ditt svar", visible=False,
                                                  placeholder="f.eks. 750 000 eller 40 %")
                        with gr.Row():
                            formel_svar = gr.Button("Svar", variant="primary")
                            formel_ny = gr.Button("Ny oppgave ➜")
                        formel_resultat = gr.HTML()
                    with gr.Tab("Formelark"):
                        gr.HTML(vis_formelark())

            with gr.Tab("🧩 Modeller", id="modeller"):
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        mfag0 = fag0 if fag0 in MODELLFAG else "MRK1001"
                        modell_fag = gr.Dropdown(list(MODELLFAG), value=mfag0, label="Fag")
                        modell_kap = gr.Dropdown(_kapitler(mfag0), value=ALLE_KAPITLER, label="Kapittel", scale=2)
                        modell_vis = gr.Radio(ARK, value="Modellark", label="Vis", scale=2)
                        modell_ov = gr.Button("🎯 Øv på disse ➜", variant="primary", scale=1)
                modell_ark = gr.Markdown(vis_modellark(mfag0, ALLE_KAPITLER), elem_classes="modellark")

            with gr.Tab("📈 Mestring", id="mestring"):
                mestring = gr.HTML()
                oppdater_knapp = gr.Button("Oppdater", size="sm")


        plan_ut = [plan_overskrift, plan_data, uke]
        app.load(vis_plan, outputs=plan_ut)
        app.load(vis_mestring, outputs=mestring)
        app.unload(rydd_okt)
        hopp_knapp.click(hopp_over_i_dag, outputs=plan_ut)
        angre_knapp.click(angre_i_dag, outputs=plan_ut)
        forklar_knapp.click(forklar_plan, outputs=forklaring)
        veileder_knapp.click(spor_veileder, veileder_tekst, [veileder_ut, veileder_okt])
        veileder_tekst.submit(spor_veileder, veileder_tekst, [veileder_ut, veileder_okt])

        spor_inn = [spor_tekst, samtale, utveksling, spor_fag, spor_eksempel, spor_agent]
        spor_fag.change(lambda f: gr.update(visible=f == AGENTFAG), spor_fag, spor_agent)
        spor_ut = [chat, samtale, utveksling, spor_tekst]
        spor_knapp.click(spor, spor_inn, spor_ut)
        spor_tekst.submit(spor, spor_inn, spor_ut)
        tom_knapp.click(lambda: ([], [], []), outputs=[chat, samtale, utveksling])

        quiz_fag.input(lambda f: gr.update(choices=temaer_for(f, med_alle=False), value=None), quiz_fag, quiz_tema)
        quiz_valg_inn = [quiz_fag, quiz_tema, quiz_type, quiz_stil]
        for felt in (quiz_tema, quiz_type, quiz_stil):
            felt.change(forbered_quiz, quiz_valg_inn, None, show_progress="hidden")
        knapper = [svar_knapp, nytt_knapp, prov_knapp, feil_knapp]
        sporsmal_ut = [quiz_sporsmal, quiz_valg, quiz_tekst, quiz_resultat, poeng, *knapper, quiz_flere]
        nytt_knapp.click(nytt_sporsmal, [quiz_fag, quiz_tema, quiz_type, quiz_stil], sporsmal_ut)
        feil_knapp.click(ta_feil_paa_nytt, quiz_fag, sporsmal_ut)
        prov_knapp.click(prov_igjen, quiz_tekst, quiz_resultat)
        quiz_type.input(stilvalg, [quiz_type, quiz_fag], quiz_stil)
        quiz_fag.input(lambda f, t: stilvalg(t, f) if t == "modeller" else gr.update(), [quiz_fag, quiz_type], quiz_stil)
        svar_knapp.click(svar_quiz, [quiz_valg, quiz_tekst, quiz_flere], [quiz_resultat, poeng, *knapper])

        for felt in (eks_fag, eks_kilde):
            felt.input(eksamensvalg, [eks_fag, eks_kilde], [eks_valg, eks_saker])
        eks_kilde.input(lambda k: gr.update(visible=k == NYHET), eks_kilde, eks_hent)
        eks_hent.click(lambda f, k: eksamensvalg(f, k, ferske=True), [eks_fag, eks_kilde], [eks_valg, eks_saker])
        eks_start.click(start_eksamen, [eks_fag, eks_kilde, eks_valg, eks_saker],
                        [eks_case, eks_svar, eks_lever, eks_resultat, eks_okt])
        eks_lever.click(lever_eksamen, [eks_svar, eks_okt], [eks_resultat, eks_okt])

        # .input (ikke .change): bare når du selv bytter fag, så «Øv nå» ikke nullstiller temaet
        kort_fag.input(lambda f: gr.update(choices=temaer_for(f), value=ALLE_KORT), kort_fag, kort_temavalg)
        hent_knapp.click(hent_kort, [kort_fag, kort_temavalg, kort_nye], [ko, flashcard, snu_rad, vurder_rad])
        snu_knapp.click(snu, ko, [flashcard, snu_rad, vurder_rad])
        for knapp in vurderingsknapper:
            knapp.click(vurder_kort, [knapp, ko], [ko, flashcard, snu_rad, vurder_rad])

        oppdater_knapp.click(vis_mestring, outputs=mestring)

        modell_fag.input(lambda f, a: (gr.update(choices=_kapitler(f), value=ALLE_KAPITLER),
                                       vis_modellark(f, ALLE_KAPITLER, a)), [modell_fag, modell_vis], [modell_kap, modell_ark])
        modell_kap.input(vis_modellark, [modell_fag, modell_kap, modell_vis], modell_ark)
        modell_vis.input(vis_modellark, [modell_fag, modell_kap, modell_vis], modell_ark)
        modell_ov.click(ov_paa_modeller, [modell_fag, modell_kap], [faner, quiz_fag, quiz_tema, quiz_type, quiz_stil])

        formel_ut = [formel_kort, formel_valg, formel_tekst, formel_resultat, formel_poeng, formel_okt]
        formel_ny.click(ny_formeloppgave, [formel_tema, formel_type, formel_okt], formel_ut)
        formel_svar.click(svar_formel, [formel_valg, formel_tekst, formel_okt],
                          [formel_resultat, formel_poeng, formel_okt])
        formel_tekst.submit(svar_formel, [formel_valg, formel_tekst, formel_okt],
                            [formel_resultat, formel_poeng, formel_okt])
    return app


if __name__ == "__main__":
    print("Laster modellene ...")
    hent("oppvarming", fag=standardfag())
    generer("Svar med ett ord.", "Hei")
    lag_app().launch(server_name="127.0.0.1", inbrowser=True, theme=TEMA, css=CSS)
