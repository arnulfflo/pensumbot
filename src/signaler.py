"""Finn modellene: tren på å se hvilke modeller en eksamenscase ber om.

Bygget på config/signaler_{fag}.yaml, som er hentet fra løsningsforslagene til ekte caser.
Tre øvingsmåter:
  signal  ett signal fra en case eller oppgavetekst. Kryss av for modellene det peker på.
  finn    en hel eksamenscase med oppgavene. Kryss av for modellene du ville brukt.
          Rettingen viser signalet bak hver modell, og modeller løsningsforslaget sier ikke passer.
  ny      en ny, oppdiktet case. Python velger 2–3 signaler fra katalogen først, og språkmodellen skriver
          en case med akkurat de signalene. Fasiten er modellene til signalene, ikke det språkmodellen mener.
          Casen forkastes hvis den nevner modellene, eller hvis setningen med signalet ikke står i casen.

Kjør:  uv run python -m src.signaler MRK1001 --type finn -n 1     (viser spørsmål og fasit)
"""

import argparse
import math
import random
import re
from dataclasses import dataclass, field
from functools import cache

import docx
import yaml

from src.konfig import ROT, pensum_mappe
from src.modeller import Modell, kapittel_i, modeller

TYPER = {"signal": "Finn signalet", "finn": "Finn modellene i en eksamenscase", "ny": "Ny case (generert)"}
SPORSMAL_FINN = "Hvilke modeller fra pensum bør du bruke for å svare godt på oppgavene? Kryss av for modellene som passer."
SPORSMAL_SIGNAL = "Hvilke modeller peker dette på? Kryss av for modellene som passer."
SPORSMAL_NY = "Hvilke modeller bør du bruke for å analysere denne casen? Kryss av for modellene som passer."


@dataclass
class Signal:
    signal: str
    type: str
    modeller: list[str]
    begreper: list[str] = field(default_factory=list)
    kilder: list[str] = field(default_factory=list)
    hvorfor: str = ""
    utledet: bool = False
    sitat: str = ""
    sitat_fra: str = ""

    @property
    def opphav(self) -> str:
        return ("utledet fra notatene, ikke fra en sensor" if self.utledet
                else "fra løsning/sensorveiledning: " + ", ".join(self.kilder))


def _fil(fag: str):
    return ROT / "config" / f"signaler_{fag}.yaml"


def har_signaler(fag: str) -> bool:
    return _fil(fag).exists()


@cache
def _data(fag: str) -> dict:
    return yaml.safe_load(_fil(fag).read_text(encoding="utf-8")) if har_signaler(fag) else {}


def signaler(fag: str) -> tuple[Signal, ...]:
    standard = dict(signal="", type="case", modeller=[], begreper=[], kilder=[], hvorfor="", utledet=False,
                    sitat="", sitat_fra="")
    return tuple(Signal(**{k: s.get(k, v) for k, v in standard.items()}) for s in _data(fag).get("signaler", []))


def caser(fag: str) -> dict[str, dict]:
    """Casene med fasit: navn → {fil, oppgave}. fil er relativ til eksamener/. oppgave legges til casen
    når casefilen ikke har med oppgaveteksten (den står da i sensorveiledningen)."""
    return _data(fag).get("caser", {})


def prinsipper(fag: str) -> list[str]:
    return _data(fag).get("prinsipper", [])


def _modell_etter_navn(fag: str) -> dict[str, Modell]:
    return {m.navn: m for m in modeller(fag)}


def er_modellvalg(q: dict) -> bool:
    """Spørsmål fra denne øvelsen, også når de kommer tilbake i repetisjonen."""
    return q.get("sporsmal", "").endswith((SPORSMAL_FINN, SPORSMAL_SIGNAL, SPORSMAL_NY))


def krav(antall_riktige: int) -> int:
    """Hvor mange du må finne: halvparten, men aldri mer enn seks. En hel case kan ha 20 relevante modeller,
    og løsningsforslagene gir toppkarakter uten at hver eneste er med."""
    return min(math.ceil(antall_riktige / 2), 6)


def godkjent(antall_riktige: int, funnet: int, feil: int) -> bool:
    """Godkjent når du fant nok av modellene og ikke valgte noen som ikke passer."""
    return feil == 0 and funnet >= krav(antall_riktige)


def _gale_modeller(fag: str, riktige: list[str], rng: random.Random, antall: int, unngaa: set[str] = frozenset()) -> list[str]:
    """Modeller som ikke passer. Helst modeller som er brukt i andre signaler, så de ser fristende ut."""
    from src.modellquiz import _samme_tema
    alle = _modell_etter_navn(fag)
    rett = [alle[n] for n in riktige if n in alle]
    brukt = {n for s in signaler(fag) for n in s.modeller}
    kandidater = [m for m in alle.values() if m.navn not in riktige and m.navn not in unngaa and m.elementer
                  and not any(_samme_tema(r, m) for r in rett)]
    rng.shuffle(kandidater)
    kandidater.sort(key=lambda m: m.navn not in brukt)       # de fristende først
    return [m.navn for m in kandidater[:antall]]


# ---------- finn signalet ----------

def lag_signal(fag: str, s: Signal, rng: random.Random) -> dict | None:
    riktige = list(dict.fromkeys(s.modeller))
    if not riktige or s.type == "ikke":
        return None
    gale = _gale_modeller(fag, riktige, rng, antall=max(3, min(5, 8 - len(riktige))))
    alternativer = riktige + gale
    rng.shuffle(alternativer)
    hvor = "i oppgaveteksten" if s.type == "oppgaveord" else "i casen"
    forklaring = s.hvorfor
    if s.begreper:
        forklaring += "\nBegreper å bruke: " + ", ".join(s.begreper) + "."
    forklaring += f"\n({s.opphav})"
    return {"sporsmal": f"Du ser dette {hvor}:\n«{s.signal.strip('«»')}»\n\n{SPORSMAL_SIGNAL}",
            "alternativer": alternativer, "fasit": riktige, "forklaring": forklaring, "sitat": "",
            "type": "avkrysning", "stil": "finn signalet", "kilde": f"signalkatalogen ({s.opphav})"}


# ---------- finn modellene i en hel case ----------

def _tekst(el, i_boks: bool = False) -> str:
    """Teksten i et element. Hopper over reservekopien Word lagrer av tekstbokser (mc:Fallback),
    og over tekstbokser når i_boks er False (de tas med som egne linjer)."""
    deler = []
    def gaa(e, boks):
        tag = e.tag.rsplit("}", 1)[-1]
        if tag == "Fallback" or (tag == "txbxContent" and not boks):
            return
        if tag == "t":
            deler.append(e.text or "")
        for barn in e:
            gaa(barn, boks)
    gaa(el, i_boks)
    return "".join(deler).strip()


def _tekstbokser(el) -> list[str]:
    """Bildetekster og figurtitler i tekstbokser, én linje per avsnitt i boksen."""
    linjer = []
    def gaa(e):
        tag = e.tag.rsplit("}", 1)[-1]
        if tag == "Fallback":
            return
        if tag == "txbxContent":
            linjer.extend(f"[{x}]" for p in e if p.tag.endswith("}p") and (x := _tekst(p, True)))
            return
        for barn in e:
            gaa(barn)
    gaa(el)
    return linjer


def _tekst_fra_docx(sti) -> str:
    """Avsnitt og tabeller i rekkefølge. Avsnitt som står to ganger (Kari Traa) tas med én gang."""
    d = docx.Document(sti)
    linjer, sett = [], set()
    for barn in d.element.body.iterchildren():
        tag = barn.tag.rsplit("}", 1)[-1]
        if tag == "p":
            tekst = _tekst(barn)
            biter = _tekstbokser(barn) + ([tekst] if tekst else [])
        elif tag == "tbl":
            biter = []
            for rad in barn.iter():
                if rad.tag.endswith("}tr"):
                    celler = [_tekst(c) for c in rad if c.tag.endswith("}tc")]
                    if any(celler):
                        biter.append(" | ".join(celler))
        else:
            continue
        for b in biter:
            if re.search(r"\bNUMPAGES\b|\bPAGE \d+ av\b", b):       # feltkoder fra topp- og bunntekst
                continue
            if b not in sett:
                sett.add(b)
                linjer.append(b)
    return "\n\n".join(linjer)


def _flyt(tekst: str) -> str:
    """OCR gir én linje per trykte linje. Slå dem sammen til avsnitt; korte linjer uten punktum er titler."""
    avsnitt, naa = [], []
    for linje in (l.strip() for l in tekst.splitlines()):
        if not linje:
            continue
        tittel = len(linje) < 45 and not re.search(r"[.,:;?!»]$", linje)
        if tittel or linje.startswith(("- ", "– ")):
            if naa:
                avsnitt.append(" ".join(naa))
            naa = []
        if tittel:
            avsnitt.append(linje)
        else:
            naa.append(linje)
    if naa:
        avsnitt.append(" ".join(naa))
    return "\n\n".join(avsnitt)


def _tekst_fra_pdf(sti) -> str:
    """Tekst fra PDF. Skannede sider (og sider der PDF-en mangler bokstaver) leses med OCR, spalte for spalte."""
    from pypdf import PdfReader
    from src.ocr import les_side_spalter
    sider = []
    for i, side in enumerate(PdfReader(sti).pages):
        t = side.extract_text() or ""
        if len(t.split()) < 30 or "\ufffd" in t:
            t = les_side_spalter(sti, i + 1)
        sider.append(t)
    return _flyt("\n".join(sider))


@cache
def casetekst(fag: str, navn: str) -> str:
    c = caser(fag)[navn]
    sti = pensum_mappe() / fag / "eksamener" / c["fil"]
    tekst = _tekst_fra_pdf(sti) if sti.suffix == ".pdf" else _tekst_fra_docx(sti)
    if c.get("oppgave"):
        tekst += "\n\n" + c["oppgave"].strip()
    return tekst


def fasit_for_case(fag: str, navn: str) -> tuple[dict[str, list[Signal]], dict[str, Signal]]:
    """(modell → signalene som peker på den, modell som ikke passer → signalet som sier det)."""
    riktige: dict[str, list[Signal]] = {}
    for s in signaler(fag):
        if navn in s.kilder and s.type != "ikke":
            for m in s.modeller:
                riktige.setdefault(m, []).append(s)
    feller: dict[str, Signal] = {}
    for s in signaler(fag):
        if navn in s.kilder and s.type == "ikke":
            for m in s.modeller:
                if m not in riktige:
                    feller.setdefault(m, s)      # det første signalet er det mest konkrete
    return riktige, feller


def lag_finn(fag: str, navn: str, rng: random.Random) -> dict | None:
    riktige, feller = fasit_for_case(fag, navn)
    if not riktige:
        return None
    tekst = casetekst(fag, navn)
    fasit = list(riktige)
    antall_gale = max(4, min(10, math.ceil(len(fasit) / 2))) - len(feller)
    gale = list(feller) + _gale_modeller(fag, fasit, rng, antall=max(2, antall_gale), unngaa=set(feller))
    alternativer = fasit + gale
    rng.shuffle(alternativer)
    kilde = caser(fag)[navn].get("fasit", "løsningsforslaget")
    linjer = [f"Du må finne minst {krav(len(fasit))} av de {len(fasit)} modellene {kilde} bruker, "
              "uten å velge noen som ikke passer. Signalene i casen og modellene de peker på:"]
    for s in signaler(fag):
        if navn in s.kilder and s.type != "ikke":
            linjer.append(f"• {s.signal} → " + ", ".join(s.modeller))
    for m, s in feller.items():
        linjer.append(f"✗ {m} passer ikke her: {s.hvorfor}")
    linjer.append("Husk: modellene skal brukes på bedriften i casen, og strategien skal ende i de 4 P-ene.")
    return {"sporsmal": f"📄 Eksamenscase: {navn}\n\n{tekst}\n\n{SPORSMAL_FINN}",
            "alternativer": alternativer, "fasit": fasit, "forklaring": "\n".join(linjer), "sitat": "",
            "type": "avkrysning", "stil": "finn modellene", "case": navn,
            "kilde": f"eksamener/{caser(fag)[navn]['fil']} (fasit fra {caser(fag)[navn].get('fasit', 'løsningsforslaget')})"}


# ---------- ny case: språkmodellen skriver, signalkatalogen gir fasiten ----------

BRANSJER = ["dagligvare", "sportsutstyr", "reiseliv og hotell", "sjømat", "kommune og helse", "bank og forsikring",
            "IT og programvare", "bygg og anlegg", "kafé og restaurant", "klær og mote", "energi", "treningssenter",
            "frivillig organisasjon", "transport og logistikk", "skole og utdanning", "media", "landbruk og mat",
            "industri", "kosmetikk", "elektronikkbutikk", "eldreomsorg", "oppstartsbedrift innen app", "advokatfirma",
            "brukthandel", "møbler", "festival og kultur", "bryggeri", "bilforhandler"]

_FORLEDD = ["Nord", "Fjell", "Vest", "Lys", "Bølge", "Elv", "Tind", "Furu", "Kyst", "Sol", "Fjord", "Lyng", "Stein",
            "Breen", "Skog", "Havn", "Mjøs", "Varde", "Orkla", "Bjørke"]
_ETTERLEDD = ["vik", "heim", "kraft", "gruppen", "partner", "hus", "verk", "lab", "torget", "linja"]

SYSTEM_SETNING = """Du skriver ÉN setning til en oppdiktet eksamenscase i {fagnavn}. Bedriften heter {navn} ({bransje}).

Du får et SIGNAL: en opplysning som gjør en bestemt modell relevant, og hvorfor. Skriv en ny, konkret setning om
{navn} som viser akkurat dette signalet tydelig, så en student som kan pensum kjenner det igjen.
- {hva}
- Ikke kopier eksempelet. Lag en ny situasjon som passer bransjen.
- ALDRI nevn navnet på modellen, forfattere eller navnene på elementene. Bare situasjonen.
- Hold deg til dette ene signalet.
Skriv på norsk bokmål."""

_HVA = {"case": "Setningen er en opplysning i casen (hva som skjer, hva noen sier, tall), ikke et spørsmål.",
        "oppgaveord": "Setningen er en eksamensoppgave til casen, og den skal bruke samme verb eller ord som signalet "
                      "(for eksempel «segmenter», «drøft», «analyser … fra et ledelsesperspektiv»)."}

SYSTEM_NY = """Du skriver en kort eksamenscase i {fagnavn} om {navn} ({bransje}), en oppdiktet norsk bedrift.

Du får noen setninger som MÅ stå i casen, ordrett og uendret. Skriv 6–10 setninger totalt: kort bakgrunn om
bedriften (hva de gjør, størrelse, kunder) og de gitte setningene flettet inn der de passer naturlig.
- Ikke legg til nye problemer, konflikter eller strategier utover det de gitte setningene sier.
- Ikke nevn modeller, teorier eller forfattere.
- Ikke skriv oppgaver eller spørsmål.
Skriv på norsk bokmål."""

SKJEMA_SETNING = {"type": "object", "properties": {"setning": {"type": "string"}}, "required": ["setning"]}
SKJEMA_NY = {"type": "object", "properties": {"case": {"type": "string"}}, "required": ["case"]}


def _velg_signaler(fag: str, kap: int | None, rng: random.Random, antall: int) -> list[Signal]:
    """Signaler som peker på helt ulike modeller, så fasiten blir entydig. Det første er fra kapittelet."""
    from src.modellquiz import _samme_tema
    alle = _modell_etter_navn(fag)
    utvalg = [s for s in signaler(fag) if s.type != "ikke" and s.modeller and all(n in alle for n in s.modeller)]
    rng.shuffle(utvalg)
    utvalg.sort(key=lambda s: not _i_kapittel(fag, s.modeller, kap))
    valgt: list[Signal] = []
    for s in utvalg:
        if not valgt and not _i_kapittel(fag, s.modeller, kap):
            return []
        brukt = [alle[n] for v in valgt for n in v.modeller]
        nye = [alle[n] for n in s.modeller]
        if any(a.navn == b.navn or _samme_tema(a, b) for a in nye for b in brukt):
            continue
        if sum(v.type == "oppgaveord" for v in valgt + [s]) > 1:
            continue                    # ett oppgaveord holder, ellers blir oppgaven en liste med verb
        valgt.append(s)
        if len(valgt) == antall:
            break
    return valgt


def _signalmelding(fag: str, s: Signal) -> str:
    alle = _modell_etter_navn(fag)
    linjer = [f"Signal: {s.signal}", "Peker på: " + "; ".join(s.modeller), f"Hvorfor: {s.hvorfor}"]
    if s.begreper:
        linjer.append("Begreper: " + ", ".join(s.begreper))
    if s.sitat:
        linjer.append(f"Eksempel fra en ekte eksamen (ikke kopier): «{s.sitat.strip('«»')}»")
    return "\n".join(linjer)


def _avslorer(fag: str, tekst: str, valgt: list[Signal]) -> str | None:
    from src.modellquiz import case_avslorer
    alle = _modell_etter_navn(fag)
    for s in valgt:
        for n in s.modeller:
            if grunn := case_avslorer(tekst, alle[n]):
                return f"{grunn} ({n})"
    return None


def lag_ny(fag: str, kap: int | None, rng: random.Random, forsok: int = 3) -> tuple[dict | None, str]:
    """En ny case med 2–3 signaler. Først én setning per signal, så bakgrunn rundt dem.
    Prøver på nytt med nye signaler hvis noe ikke består kontrollen."""
    from src.kontroll import sitat_finnes
    from src.llm import generer_json
    from src.modellquiz import FAGNAVN
    fagnavn = FAGNAVN.get(fag, fag)
    grunn = "fant ingen signaler i kapittelet"
    for _ in range(forsok):
        valgt = _velg_signaler(fag, kap, rng, rng.choice([2, 3, 3]))
        if len(valgt) < 2:
            return None, "for få signaler i kapittelet som peker på ulike modeller"
        bransje = rng.choice(BRANSJER)
        navn = rng.choice(_FORLEDD) + rng.choice(_ETTERLEDD) + " AS"
        try:
            setninger = []
            for s in valgt:
                system = SYSTEM_SETNING.format(fagnavn=fagnavn, navn=navn, bransje=bransje,
                                               hva=_HVA["oppgaveord" if s.type == "oppgaveord" else "case"])
                setninger.append(generer_json(system, _signalmelding(fag, s), SKJEMA_SETNING,
                                              temperatur=0.8)["setning"].strip())
            fakta = [x for x, s in zip(setninger, valgt) if s.type != "oppgaveord"]
            if grunn := _avslorer(fag, "\n".join(setninger), valgt):
                continue
            case = generer_json(SYSTEM_NY.format(fagnavn=fagnavn, navn=navn, bransje=bransje),
                                "Setninger som må stå i casen:\n" + "\n".join(f"- {x}" for x in fakta),
                                SKJEMA_NY, temperatur=0.6)["case"].strip()
        except (ValueError, TimeoutError, KeyError, TypeError) as feil:
            grunn = f"språkmodellen feilet ({type(feil).__name__})"
            continue
        if len(case.split()) < 60:
            grunn = "for kort case"
            continue
        if grunn := _avslorer(fag, case, valgt):
            continue
        if mangler := [x for x in fakta if not sitat_finnes(x, case)]:
            grunn = f"casen mangler setningen «{mangler[0][:60]}…»"
            continue
        oppgave = next((x for x, s in zip(setninger, valgt) if s.type == "oppgaveord"),
                       f"Analyser situasjonen i {navn} med relevant teori, og gi råd til ledelsen.")
        data = {"navn": navn, "case": case, "oppgave": oppgave,
                "spor": [{"nr": i, "setning": x} for i, x in enumerate(setninger, start=1)]}
        return _ny_sporsmal(fag, data, valgt, rng), ""
    return None, grunn


def _ny_sporsmal(fag: str, data: dict, valgt: list[Signal], rng: random.Random) -> dict:
    fasit = list(dict.fromkeys(n for s in valgt for n in s.modeller))
    gale = _gale_modeller(fag, fasit, rng, antall=max(4, 8 - len(fasit)))
    alternativer = fasit + gale
    rng.shuffle(alternativer)
    spor = {p["nr"]: p["setning"].strip() for p in data["spor"]}
    linjer = [f"Du må finne minst {krav(len(fasit))} av de {len(fasit)} modellene, uten å velge noen som ikke passer. "
              "Casen er skrevet av språkmodellen rundt signaler fra ekte eksamener:"]
    for nr, s in enumerate(valgt, start=1):
        linjer.append(f"• «{spor[nr].strip('«»')}» → " + ", ".join(s.modeller))
        linjer.append(f"   Signal: {s.signal}. {s.hvorfor}")
        if s.sitat:
            linjer.append(f"   Samme signal i {s.sitat_fra}: «{s.sitat.strip('«»')}»")
    linjer.append("Andre modeller kan også gi litt, men det er disse casen er skrevet for å teste.")
    navn = data["navn"].strip()
    tekst = f"{data['case'].strip()}\n\nOppgave: {data['oppgave'].strip()}"
    return {"sporsmal": f"📄 Ny case: {navn} (oppdiktet)\n\n{tekst}\n\n{SPORSMAL_NY}",
            "alternativer": alternativer, "fasit": fasit, "forklaring": "\n".join(linjer), "sitat": "",
            "type": "avkrysning", "stil": "ny case", "case": navn,
            "kilde": "ny case fra språkmodellen (fasit fra signalkatalogen: "
                     + ", ".join(dict.fromkeys(k for s in valgt for k in s.kilder)) + ")"}


# ---------- strømmen til quiz-fanen ----------

def _i_kapittel(fag: str, navn: list[str], kap: int | None) -> bool:
    alle = _modell_etter_navn(fag)
    return kap is None or any(alle[n].kapittel == kap for n in navn if n in alle)


def signal_strom(fag: str, tema: str | None, stil: str, antall: int = 15, rng: random.Random | None = None):
    """Gir (spørsmål, modell) ett om gangen. Modellen er den første riktige, så spørsmålet havner på et tema."""
    rng = rng or random.Random()
    kap = kapittel_i(tema or "")
    alle = _modell_etter_navn(fag)
    if stil == "ny":
        laget = (lag_ny(fag, kap, rng) for _ in range(antall))      # (spørsmål, grunn til at det feilet)
    elif stil == "finn":
        navn = [n for n in caser(fag) if _i_kapittel(fag, list(fasit_for_case(fag, n)[0]), kap)]
        rng.shuffle(navn)
        laget = ((lag_finn(fag, n, rng), n) for n in navn)
    else:
        utvalg = [s for s in signaler(fag) if s.type != "ikke" and _i_kapittel(fag, s.modeller, kap)]
        rng.shuffle(utvalg)
        laget = ((lag_signal(fag, s, rng), s.signal) for s in utvalg)
    gitt = 0
    for q, hva in laget:
        if gitt == antall:
            return
        if q is None:
            print(f"  (hoppet over {hva})")
            continue
        foerste = next((alle[n] for n in q["fasit"] if n in alle and (kap is None or alle[n].kapittel == kap)),
                       alle.get(q["fasit"][0]))
        gitt += 1
        yield q, foerste


# ---------- signalarket: å lese og lære av ----------

_OVERSKRIFT = {"oppgaveord": "Ord i oppgaveteksten", "case": "Fakta i casen", "ikke": "Når en teori ikke passer"}
_INGRESS = {"oppgaveord": "Verbene og ordene i selve oppgaven sier hvilket tema sensor ser etter.",
            "case": "Opplysninger i caseteksten som gjør en bestemt modell relevant. Strek dem under når du leser casen.",
            "ikke": "Her sier sensor eller løsningsforslaget rett ut at noe gir lite uttelling."}


def signalark(fag: str, kapittel: int | None = None) -> str:
    """Markdown til Modeller-fanen: hvert signal med sitat fra casen, modellene det peker på og hvorfor.
    Med kapittel: bare signalene som peker på en modell i kapittelet."""
    alle = _modell_etter_navn(fag)
    utvalg = [s for s in signaler(fag) if kapittel is None or _i_kapittel(fag, s.modeller, kapittel)]
    if not utvalg:
        return "*Ingen signaler peker på modeller i dette kapittelet ennå.*"
    deler = []
    if kapittel is None and prinsipper(fag):
        deler.append("### Det sensor ser etter i alle oppgaver\n" + "\n".join(f"- {p}" for p in prinsipper(fag)))
    for type_ in ("oppgaveord", "case", "ikke"):
        gruppe = [s for s in utvalg if s.type == type_]
        if not gruppe:
            continue
        seksjon = [f"### {_OVERSKRIFT[type_]}\n*{_INGRESS[type_]}*"]
        for s in gruppe:
            linjer = [f"#### {s.signal}"]
            if s.sitat:
                linjer.append(f"> «{s.sitat.strip('«»')}»  \n> — *{s.sitat_fra}*")
            if s.modeller:
                etikett = "Gir lite uttelling" if type_ == "ikke" else "Peker på"
                navn = [f"{n} (kap. {alle[n].kapittel})" if n in alle else n for n in s.modeller]
                linjer.append(f"**{etikett}:** " + "; ".join(navn))
            if s.begreper:
                linjer.append("**Begreper:** " + "; ".join(s.begreper))
            linjer.append(f"**Hvorfor:** {s.hvorfor}")
            linjer.append(f"<sub>{'⚠️ ' if s.utledet else ''}{s.opphav}</sub>")
            seksjon.append("\n\n".join(linjer))
        deler.append("\n\n".join(seksjon))
    # oppslag andre veien: når du leser om en modell, se hvilke signaler som peker på den
    per_modell: dict[str, list[str]] = {}
    for s in utvalg:
        if s.type != "ikke":
            for n in s.modeller:
                if kapittel is None or (n in alle and alle[n].kapittel == kapittel):
                    per_modell.setdefault(n, []).append(s.signal)
    if per_modell:
        rader = [f"- **{n}**: " + " / ".join(ss) for n, ss in sorted(per_modell.items())]
        deler.append("### Oppslag per modell\n*Hvilke signaler peker på modellen?*\n" + "\n".join(rader))
    return "\n\n---\n\n".join(deler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Øv på å finne modellene i en case (viser spørsmål og fasit)")
    ap.add_argument("fag", choices=["MRK1001", "ORG1100"])
    ap.add_argument("--type", choices=list(TYPER), default="signal")
    ap.add_argument("--kap", type=int)
    ap.add_argument("-n", type=int, default=3)
    a = ap.parse_args()
    for q, m in signal_strom(a.fag, f"kap. {a.kap}" if a.kap else None, a.type, a.n):
        tekst = q["sporsmal"]
        print("\n" + (tekst if len(tekst) < 600 else tekst[:300] + " […] " + tekst[-200:]))
        for alt in q["alternativer"]:
            print(f"  ☐ {alt}{'   ✓' if alt in q['fasit'] else ''}")
        print(q["forklaring"])
