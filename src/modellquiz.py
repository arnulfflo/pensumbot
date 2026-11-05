"""Øving på modeller og teorier i MRK og ORG, slik du trenger dem til en case på eksamen.

Tre øvingsmåter, alle bygget på modellarket (src/modeller.py, fra dine egne notater):
  kjenn  flervalg laget i Python, uten språkmodell: hvilken modell har disse elementene, hvilket
         element hører til modellen, hvilket mangler, og hva betyr et element.
         De gale svarene er elementer og modeller fra samme fag, så det er aldri tvil om fasiten.
  velg   språkmodellen skriver en kort case der én modell passer. Du velger modellen.
  bruk   samme slags case, og du analyserer den med modellen. Svaret rettes mot elementene.

Kjør:  uv run python -m src.modellquiz MRK1001 --type kjenn -n 5     (prøv i terminalen)
       uv run python -m src.modellquiz ORG1100 --kap 3 --type velg
"""

import argparse
import random
import re

from src.henting import Bit
from src.kontroll import _stammer, avslorer_svaret, normaliser
from src.llm import generer_json
from src.modeller import FILER, Element, Modell, kapittel_i, modeller

TYPER = {"blandet": "Blandet", "kjenn": "Kjenn modellen", "velg": "Velg modell til casen",
         "bruk": "Bruk modellen på casen"}
BLANDET = ["kjenn", "velg", "kjenn", "bruk"]      # «kjenn» går fort, casene tar litt tid å lage
FAGNAVN = {"MRK1001": "markedsføring", "ORG1100": "organisasjon og ledelse"}


def har_modeller(fag: str) -> bool:
    return fag in FILER


def i_omfang(fag: str, tema: str | None) -> list[Modell]:
    """Modellene i temaet (kapittelet), eller alle i faget hvis temaet ikke har kapittelnummer."""
    kap = kapittel_i(tema or "")
    return [m for m in modeller(fag) if kap is None or m.kapittel == kap]


# ---------- hjelpere ----------

def _kort(e: Element) -> bool:
    return 1 <= len(e.navn.split()) <= 5 and len(e.navn) <= 45


def _likt(a: str, b: str) -> bool:
    """Samme element med litt ulik skrivemåte: «Tilhørighetsbehov» i både Maslow og Alderfer."""
    na, nb = normaliser(a), normaliser(b)
    return na == nb or (_stammer(a) and _stammer(a) == _stammer(b))


def _overlapp(m1: Modell, m2: Modell) -> int:
    return sum(any(_likt(a.navn, b.navn) for b in m2.elementer) for a in m1.elementer)


def _kort_forklaring(tekst: str, ord_: int = 18) -> str:
    """Første ledd av forklaringen, så alternativene blir omtrent like lange."""
    tekst = re.sub(r"\s*\([^)]*\)", "", tekst)                  # parenteser er eksempler og detaljer
    # Del ved punktum foran stor bokstav, ikke i «f.eks. lønn» eller «bl.a.»
    tekst = re.split(r"(?<=[a-zæøå0-9)])\.\s+(?=[A-ZÆØÅ])|;\s|\s–\s", tekst.strip())[0].rstrip(".;: ")
    deler = tekst.split()
    tekst = " ".join(deler[:ord_]) + (" …" if len(deler) > ord_ else "")
    return tekst[:1].upper() + tekst[1:]


def _liste(navn: list[str]) -> str:
    navn = [f"«{n}»" for n in navn]
    return navn[0] if len(navn) == 1 else ", ".join(navn[:-1]) + " og " + navn[-1]


def _forklaring(m: Modell) -> str:
    deler = [f"{e.navn} ({_kort_forklaring(e.forklaring, 10)})" if e.forklaring else e.navn for e in m.elementer]
    return f"{m.navn} består av: " + "; ".join(deler) + "."


def _flervalg(sporsmal: str, riktig: str, gale: list[str], m: Modell, stil: str, rng: random.Random,
              forklaring: str | None = None) -> dict | None:
    alternativer = [riktig, *gale[:3]]
    if len(alternativer) < 4 or len({normaliser(a) for a in alternativer}) < 4:
        return None
    rng.shuffle(alternativer)
    return {"sporsmal": sporsmal, "alternativer": alternativer, "fasit": riktig,
            "forklaring": forklaring or _forklaring(m), "sitat": "", "type": "flervalg", "stil": stil,
            "modell_id": m.id}


_GENERELLE_ORD = {"modellen", "modeller", "strategier", "strategien", "prosessen", "faktorer", "elementer",
                  "perspektivet", "kjennetegn", "innovasjoner"}


def _nokkelord(navn: str) -> set[str]:
    """Lange fagord i navnet, kuttet så bøyninger møtes: «markedsorientering» → «markedsorienter»."""
    return {o[:max(8, len(o) - 3)] for o in re.findall(r"[a-zæøå]{8,}", navn.lower()) if o not in _GENERELLE_ORD}


def _samme_tema(m: Modell, a: Modell) -> bool:
    """Handler modellene om samme begrep? «Markedsorientering (Kohli og Jaworski)» og «Interne drivkrefter for
    markedsorientering» gjør det, og da er elementene i den ene lette å tro hører til den andre.
    Samme forfattere i parentes teller også."""
    tekst_a = normaliser(a.navn).replace(" ", "")
    if any(o in tekst_a for o in _nokkelord(m.navn)) or any(o in normaliser(m.navn).replace(" ", "")
                                                          for o in _nokkelord(a.navn)):
        return True
    forfattere = lambda n: set(re.findall(r"\b[A-ZÆØÅ][a-zæøå]{3,}", " ".join(re.findall(r"\(([^)]+)\)", n))))
    return bool(forfattere(m.navn) & forfattere(a.navn)) or (m.overskrift in a.tekst[:300])


def _andre_modeller(m: Modell, alle: list[Modell], rng: random.Random, samme_kap_forst: bool = True) -> list[Modell]:
    """Andre modeller i faget som ikke deler elementer med m. Nærmeste kapitler først, i tilfeldig rekkefølge."""
    andre = [a for a in alle if a.id != m.id and _overlapp(m, a) == 0 and not _likt(a.navn, m.navn)
             and not _samme_tema(m, a)]
    rng.shuffle(andre)
    if samme_kap_forst:
        andre.sort(key=lambda a: abs(a.kapittel - m.kapittel))
    return andre


def _gale_elementer(m: Modell, alle: list[Modell], rng: random.Random, antall: int = 3) -> list[str]:
    """Elementer fra andre modeller som verken er, eller står i teksten om, modellen m."""
    i_teksten = normaliser(m.tekst)
    ut = []
    for annen in _andre_modeller(m, alle, rng):
        kandidater = [e for e in annen.elementer if _kort(e) and normaliser(e.navn) not in i_teksten
                      and not any(_likt(e.navn, x.navn) for x in m.elementer)
                      and not any(_likt(e.navn, u) for u in ut)]
        if kandidater:
            ut.append(rng.choice(kandidater).navn)
        if len(ut) == antall:
            break
    return ut


def _navnet_avslorer(m: Modell, elementnavn: list[str]) -> bool:
    """«Tre typer beslutninger» med elementet «Valgbeslutning»: navnet står i elementet."""
    generelle = {"modell", "modellen", "teori", "teorien", "typer", "former", "nivåer", "faser", "strategier",
                 "kilder", "steg", "områder", "matrisen", "prosess", "prosessen"}
    i_navn = {s for s in _stammer(m.navn) if s not in {g[:6] for g in generelle}}
    # Også inne i sammensatte ord: «Rettferdighetsteori» røper «Fordelingsrettferdighet»
    return any(st in normaliser(n).replace(" ", "") for n in elementnavn for st in i_navn)


# ---------- «kjenn modellen»: laget i Python ----------

def lag_hvilken_modell(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    elementer = [e.navn for e in m.elementer]
    if not 2 <= len(elementer) <= 8 or not all(_kort(e) for e in m.elementer) or _navnet_avslorer(m, elementer):
        return None
    gale = [a.navn for a in _andre_modeller(m, alle, rng)[:3]]
    return _flervalg(f"Hvilken modell eller teori består av {_liste(elementer)}?", m.navn, gale, m,
                     "hvilken modell", rng)


def lag_hvilket_element(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    kandidater = [e for e in m.elementer if _kort(e) and not _navnet_avslorer(m, [e.navn])]
    if len(m.elementer) < 2 or not kandidater:
        return None
    riktig = rng.choice(kandidater).navn
    return _flervalg(f"Hvilket av disse er et element i «{m.navn}»?", riktig, _gale_elementer(m, alle, rng), m,
                     "hvilket element", rng)


def lag_mangler(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    if not 4 <= len(m.elementer) <= 9 or not all(_kort(e) for e in m.elementer):
        return None
    nr = rng.randrange(len(m.elementer))
    vist = ["___" if i == nr else e.navn for i, e in enumerate(m.elementer)]
    return _flervalg(f"«{m.navn}» har disse elementene: {', '.join(vist)}. Hvilket element mangler?",
                     m.elementer[nr].navn, _gale_elementer(m, alle, rng), m, "hva mangler", rng)


def lag_betydning(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    """«Hva kjennetegner «Melkeku» i BCG-matrisen?» De gale svarene er de andre elementene i samme modell."""
    med = [e for e in m.elementer if len(_kort_forklaring(e.forklaring).split()) >= 4]
    if len(med) < 4:
        return None
    riktig = rng.choice(med)
    gale = [_kort_forklaring(e.forklaring) for e in med if e is not riktig]
    rng.shuffle(gale)
    sporsmal = f"Hva kjennetegner «{riktig.navn}» i «{m.navn}»?"
    fasit = _kort_forklaring(riktig.forklaring)
    if avslorer_svaret(sporsmal, fasit, gale[:3]) or _stammer(riktig.navn) & _stammer(fasit):
        return None                 # «Kundeberedskap» → «… manglende kundeberedskap er …»
    return _flervalg(sporsmal, fasit, gale, m, "hva betyr elementet", rng)


def lag_alle_elementer(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    """«Hvilke av disse er elementer i Kotters åtte steg? Kryss av for alle.» Alle elementene er med, og
    2–4 gale fra andre modeller. Riktig bare når du har krysset av for alle de riktige og ingen gale."""
    if not 3 <= len(m.elementer) <= 6 or not all(_kort(e) for e in m.elementer) or _navnet_avslorer(m, [e.navn for e in m.elementer]):
        return None
    riktige = [e.navn for e in m.elementer]
    gale = _gale_elementer(m, alle, rng, antall=max(2, min(4, 8 - len(riktige))))
    if len(gale) < 2:
        return None
    alternativer = riktige + gale
    rng.shuffle(alternativer)
    return {"sporsmal": f"Hvilke av disse er elementer i «{m.navn}»? Kryss av for alle som hører til.",
            "alternativer": alternativer, "fasit": riktige, "forklaring": _forklaring(m), "sitat": "",
            "type": "avkrysning", "stil": "alle elementene", "modell_id": m.id}


def rett_avkrysning(q: dict, valgt: list[str]) -> tuple[bool, list[str], list[str]]:
    """(riktig, de du glemte, de du krysset av for som ikke hører til)."""
    glemt = [a for a in q["fasit"] if a not in valgt]
    feil = [a for a in valgt if a not in q["fasit"]]
    return not glemt and not feil, glemt, feil


KJENN = [lag_alle_elementer, lag_hvilken_modell, lag_hvilket_element, lag_mangler, lag_betydning]


def lag_kjenn(m: Modell, alle: list[Modell], rng: random.Random) -> dict | None:
    for lag in rng.sample(KJENN, len(KJENN)):
        if q := lag(m, alle, rng):
            return q
    return None


# ---------- casene: språkmodellen skriver casen, Python kontrollerer den ----------

SYSTEM_CASE = """Du lager en kort eksamenscase i {fagnavn}. Du får én modell eller teori fra pensum.

Regler:
1. «case»: 3–5 setninger om en tenkt norsk bedrift eller organisasjon (finn på et navn). Beskriv en konkret
   situasjon der akkurat denne modellen er det naturlige verktøyet for å analysere eller løse problemet.
   Ta med nok detaljer til at studenten kan bruke elementene i modellen på casen.
2. Casen skal IKKE nevne navnet på modellen, forfatterne bak den eller navnene på elementene.
   Studenten skal selv kjenne igjen hvilken modell som passer.
3. «hvorfor»: én setning om hvorfor nettopp denne modellen passer til casen.
4. «modellsvar»: en kort analyse av casen med modellen (3–5 setninger), der elementene brukes på casen.
5. Bygg modellsvaret bare på modellbeskrivelsen du får. Ikke finn på elementer.
Skriv på norsk."""

SKJEMA_CASE = {
    "type": "object",
    "properties": {"case": {"type": "string"}, "hvorfor": {"type": "string"}, "modellsvar": {"type": "string"}},
    "required": ["case", "hvorfor", "modellsvar"],
}


def avslorte_ord(m: Modell) -> list[str]:
    """Ord som røper modellen hvis de står i casen: forkortelser (RFM, BCG), forfattere (Maslow),
    hele navnet og elementnavn på flere ord («sentral rute»). Vanlige ord som «pris» er lov."""
    ord_ = [m.navn.split("(")[0].strip()]
    ord_ += re.findall(r"\b[A-ZÆØÅ]{2,}\b", m.navn)                                  # RFM, BCG, SWOT
    store = re.findall(r"\b[A-ZÆØÅ][a-zæøåé]+'?", m.navn)
    ord_ += [o for o in store[1:] if len(o) > 3]                                        # (Kotler og Keller)
    # Første ord er et navn når det står i genitiv: «Maslows», «Porters», «Wallas'». Ikke «Produktets».
    if store and m.navn.startswith(store[0]) and re.search(r"(s|')$", store[0]) and not re.search(r"(ets|ens|nes)$", store[0]):
        ord_.append(store[0].rstrip("'").removesuffix("s") if len(store[0]) > 4 else store[0])
    ord_ += [o for o in re.findall(r"\(([^)]+)\)", m.navn) for o in re.split(r",| og ", o)
             if o.strip()[:1].isupper()]                                                # (Sen og Bhattacharya)
    ord_ += [e.navn for e in m.elementer if len(e.navn.split()) >= 2]
    vanlige = {"Fire", "Tre", "Seks", "Fem", "Sju", "Åtte", "Ti", "To", "Hva"}
    return [o.strip() for o in ord_ if o.strip() and o.strip() not in vanlige]


def case_avslorer(case: str, m: Modell) -> str | None:
    tekst = normaliser(case)
    for o in avslorte_ord(m):
        n = normaliser(o)
        if len(n) >= 2 and re.search(rf"\b{re.escape(n)}", tekst):
            return f"casen nevner «{o}»"
    return None


def lag_case(m: Modell) -> tuple[dict | None, str]:
    melding = (f"Modell: {m.navn}\nElementer:\n"
               + "\n".join(f"- {e.navn}" + (f": {e.forklaring}" if e.forklaring else "") for e in m.elementer)
               + f"\n\nFra notatene:\n{m.tekst[:2500]}")
    try:
        data = generer_json(SYSTEM_CASE.format(fagnavn=FAGNAVN.get(m.fag, m.fag)), melding, SKJEMA_CASE)
    except ValueError:
        return None, "ugyldig JSON"
    except TimeoutError:
        return None, "modellen brukte for lang tid"
    case = data.get("case", "").strip()
    if len(case.split()) < 25 or not data.get("modellsvar", "").strip():
        return None, "for kort case eller manglende modellsvar"
    if grunn := case_avslorer(case, m):
        return None, grunn
    return data, ""


def lag_velg(m: Modell, alle: list[Modell], rng: random.Random) -> tuple[dict | None, str]:
    """Casen + «Hvilken modell passer best?». De gale modellene er fra andre kapitler, så de passer ikke like godt."""
    andre = [a for a in _andre_modeller(m, alle, rng) if a.kapittel != m.kapittel]
    if len(andre) < 3:
        return None, "for få andre modeller å velge mellom"
    data, grunn = lag_case(m)
    if data is None:
        return None, grunn
    q = _flervalg(f"{data['case'].strip()}\n\nHvilken modell eller teori passer best for å analysere denne casen?",
                  m.navn, [a.navn for a in andre[:3]], m, "velg modell", rng,
                  forklaring=f"{data['hvorfor'].strip()} {_forklaring(m)}")
    return q, "" if q else "like alternativer"


def lag_bruk(m: Modell) -> tuple[dict | None, str]:
    """Casen + «Analyser casen med X». Nøkkelpunktene er elementene, så rettingen sjekker at du bruker dem."""
    if len(m.elementer) < 2:
        return None, "modellen har ingen elementer å rette mot"
    data, grunn = lag_case(m)
    if data is None:
        return None, grunn
    punkter = [f"{e.navn}: {_kort_forklaring(e.forklaring, 20)}" if e.forklaring else e.navn
               for e in m.elementer[:6]]
    return {"sporsmal": f"{data['case'].strip()}\n\nAnalyser casen med «{m.navn}». Bruk elementene i modellen.",
            "nokkelpunkter": punkter, "modellsvar": data["modellsvar"].strip(), "fasit": data["modellsvar"].strip(),
            "sitat": "", "type": "kortsvar", "stil": "bruk modellen", "modell_id": m.id}, ""


# ---------- strømmen til quiz-fanen ----------

def modell_strom(fag: str, tema: str | None, stil: str = "blandet", antall: int = 15, rng: random.Random | None = None):
    """Gir (spørsmål, bit, modell) ett om gangen. Hver modell brukes bare én gang per økt."""
    rng = rng or random.Random()
    alle = list(modeller(fag))
    omfang = i_omfang(fag, tema)
    rng.shuffle(omfang)
    laget = 0
    for m in omfang:
        if laget == antall:
            return
        type_ = BLANDET[laget % len(BLANDET)] if stil == "blandet" else stil
        if type_ == "kjenn":
            q, grunn = lag_kjenn(m, alle, rng), "ingen kjenn-spørsmål for denne modellen"
        elif type_ == "velg":
            q, grunn = lag_velg(m, alle, rng)
        else:
            q, grunn = lag_bruk(m)
        if q is None and type_ != "kjenn" and stil == "blandet":
            q, grunn = lag_kjenn(m, alle, rng), grunn      # casen feilet: ta et raskt spørsmål i stedet
        if q is None:
            print(f"  (hoppet over {m.navn}: {grunn})")
            continue
        laget += 1
        yield q, Bit(m.tekst, {"fil": m.fil}, 0.0), m


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Øv på modeller og teorier i terminalen (viser spørsmål og fasit)")
    ap.add_argument("fag", choices=list(FILER))
    ap.add_argument("--kap", type=int, help="bare ett kapittel")
    ap.add_argument("--type", choices=list(TYPER), default="kjenn")
    ap.add_argument("-n", type=int, default=5)
    a = ap.parse_args()
    for q, _, m in modell_strom(a.fag, f"kap. {a.kap}" if a.kap else None, a.type, a.n):
        print(f"\n[{q['stil']}] {m.kilde}\n{q['sporsmal']}")
        for bokstav, alt in zip("ABCDEFGH", q.get("alternativer", [])):
            riktig = alt in q["fasit"] if isinstance(q["fasit"], list) else alt == q["fasit"]
            print(f"  {bokstav if q['type'] == 'flervalg' else '☐'}) {alt}{'   ✓' if riktig else ''}")
        if q["type"] == "kortsvar":
            print("  Nøkkelpunkter:", *q["nokkelpunkter"], sep="\n   - ")
            print("  Modellsvar:", q["modellsvar"])
