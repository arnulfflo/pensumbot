"""Studieveilederen: en agent som ser på dataene dine og sier hva du bør øve på nå.

Du spør med vanlige ord, f.eks. «Hva bør jeg øve på i kveld? Jeg har to timer.» Modellen
bestemmer selv hvilke verktøy den bruker, akkurat som BØA-agenten (se agent.py):

  se_status    eksamensdatoer, dagens plan og hvor mange feilsvar og kort som venter
  se_mestring  mestring per tema i ett fag, svakest først
  lag_okt      setter opp en økt på N minutter. Python velger temaene (eksamen nær + lav
               mestring først) og regner minuttene, så summen alltid stemmer.

Veilederen bare leser. Den endrer aldri planen eller databasen; i appen får du «Øv nå»-knapper
for øktene den foreslår.

Sikringer i koden:
  - koden henter status først, så agenten alltid starter fra dataene dine
  - oppgir du tid og agenten ikke lager en økt, sendes den tilbake med riktig antall minutter
  - tall og fag i svaret må komme fra verktøyene eller spørsmålet ditt

Kjør:  uv run python -m src.veileder "Hva bør jeg øve på i kveld? Jeg har to timer."
"""

import argparse
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from src.agent import Steg, tall_i, tall_som_tekst
from src.database import koble
from src.llm import chat_med_verktoy
from src.planlegger import MODELLOVING_FRA, blokker_for, last_eksamener, med_modelloving, ovingsmate_for
from src.repetisjon import forfalte_sporsmal, mestring_per_tema

MAKS_STEG = 8
MAKS_TILBAKE = 2
MIN_BLOKK = 15            # kortere rester enn dette blir ikke egen blokk
KORT_FOR_BLOKK = 5        # så mange forfalte flashcards gir en egen kortblokk

SYSTEM = """Du er studieveileder for en norsk handelshøyskolestudent som øver til eksamen.

Du har tre verktøy som leser studentens egne data:
- se_status: eksamensdatoer, dagens plan og hva som venter på repetisjon.
- se_mestring: mestring per tema i ett fag.
- lag_okt: setter opp en økt på et gitt antall minutter.

Regler:
1. Har studenten sagt hvor lang tid hen har, bruk lag_okt med det antallet minutter.
2. Bruk bare tall, fag og temaer du har fått fra verktøyene. Ikke regn ut nye tall selv.
3. Svar med: kort hva som haster mest og hvorfor (eksamen nær, lav mestring, feilsvar som venter),
   deretter øktene i rekkefølge med tema og minutter, og én setning om hva studenten bør gjøre etterpå.
4. Er det ingenting å øve på, si det.
Svar på norsk, kort og vennlig, uten å nevne verktøyene. Skriv vanlig tekst, ikke tabeller."""

VERKTOY = [
    {"navn": "se_status",
     "beskrivelse": "Gir dagens dato, eksamensdatoene med dager igjen, dagens planlagte blokker, "
                    "og antall feilsvar og flashcards som venter på repetisjon per fag.",
     "parametre": {"type": "object", "properties": {}}},
    {"navn": "se_mestring",
     "beskrivelse": "Gir mestring (0–100 %) per tema i ett fag, svakest først, og temaer som aldri er øvd på.",
     "parametre": {"type": "object", "required": ["fag"],
                   "properties": {"fag": {"type": "string", "description": "Fagkode, f.eks. MRK1001"}}}},
    {"navn": "lag_okt",
     "beskrivelse": "Setter opp en øvingsøkt. Velger temaer og øvingsmåte ut fra eksamensdato, mestring og "
                    "repetisjoner, og regner ut minuttene.",
     "parametre": {"type": "object", "required": ["minutter"],
                   "properties": {"minutter": {"type": "integer", "description": "Hvor lang tid studenten har, i minutter"},
                                  "fag": {"type": "string", "description": "Valgfritt: bare dette faget, f.eks. BOA1100"}}}},
]


# ---------- verktøyene (rene oppslag og utregninger i Python) ----------

@dataclass
class Oktblokk:
    fag: str
    tema: str             # tom for «alle kort som skal repeteres» og feilsvar
    ovingsmate: str       # flashcards, flervalg, kortsvar, modeller, repetisjon, feilsvar
    minutter: int
    grunn: str


def _aktive_fag(eksamener: dict, idag: date, repetisjonsdager: int) -> dict[str, int]:
    """{fag: dager igjen} for fag med eksamen fremover. Rett før en eksamen gjelder bare det faget (som planleggeren)."""
    igjen = {f: (d - idag).days for f, d in eksamener.items() if d > idag}
    naer = [f for f, n in igjen.items() if n <= repetisjonsdager]
    return {f: igjen[f] for f in naer[:1]} if naer else igjen


def _kort_som_venter(db, fag: str) -> int:
    naa = datetime.now().isoformat(timespec="seconds")
    return db.execute(
        "SELECT COUNT(*) FROM sporsmal s WHERE s.ovingsmate = 'flashcard' AND s.fag = ? AND"
        " (SELECT f.neste_repetisjon FROM forsok f WHERE f.sporsmal_id = s.id ORDER BY f.id DESC LIMIT 1) <= ?",
        (fag, naa)).fetchone()[0]


def se_status(db, idag: date | None = None) -> str:
    idag = idag or date.today()
    eksamener, _, innst = last_eksamener()
    linjer = [f"I dag er {idag:%d.%m.%Y}."]
    for fag, dato in sorted(eksamener.items(), key=lambda x: x[1]):
        dager = (dato - idag).days
        if dager <= 0:
            continue
        feil = len(forfalte_sporsmal(db, fag))
        linjer.append(f"{fag}: eksamen {dato:%d.%m} om {dager} dager. {feil} feilsvar og "
                      f"{_kort_som_venter(db, fag)} flashcards venter på repetisjon.")
    blokker = [b for b in blokker_for(db, idag) if b["fag"] != "-"]
    if blokker:
        linjer.append(f"Dagens plan ({innst['blokk_minutter']} min per blokk):")
        tegn = {"fullfort": "ferdig", "hoppet_over": "hoppet over", "planlagt": "ikke gjort"}
        linjer += [f"- {b['fag']} {b['ovingsmate']}: {b['tema']} ({tegn[b['status']]})" for b in blokker]
    else:
        linjer.append("Ingenting er planlagt i dag.")
    return "\n".join(linjer)


def se_mestring(db, fag: str) -> str:
    eksamener, temaer, _ = last_eksamener()
    fag = fag.strip().upper().replace("Ø", "O")
    if fag not in temaer:
        return f"Ukjent fag «{fag}». Fagene er {', '.join(sorted(temaer))}."
    rader = {r["tema"]: r for r in db.execute("SELECT * FROM temaer WHERE fag = ? AND forsok > 0", (fag,))}
    ovd = sorted((r for r in rader.values()), key=lambda r: r["mestring"])
    linjer = [f"{fag}, mestring per tema (svakest først):"]
    linjer += [f"- {r['tema']}: {round(r['mestring'] * 100)} % etter {r['forsok']} forsøk" for r in ovd]
    aldri = [t for t in temaer[fag] if t not in rader]
    if aldri:
        linjer.append(f"Aldri øvd på ({len(aldri)}): " + "; ".join(aldri))
    return "\n".join(linjer)


def lag_okt(db, minutter: int, fag: str | None = None, idag: date | None = None) -> list[Oktblokk]:
    """Velger blokker for en økt på `minutter`. Summen av minuttene blir aldri mer enn det.

    Rekkefølge: feilsvar som venter (i det mest presserende faget), flashcards som venter, så temaer
    etter prioritet = vekt for faget (1 / dager til eksamen) × (1,2 − mestring). Temaer som aldri
    er øvd på har mestring 0,5. Temaer du har øvd på i dag teller halvt, temaer i dagens plan
    som ikke er gjort teller 1,5 ganger. Ellers likt: kapittelrekkefølgen.
    """
    idag = idag or date.today()
    eksamener, temaer, innst = last_eksamener()
    blokk = innst["blokk_minutter"]
    aktive = _aktive_fag(eksamener, idag, innst["repetisjonsdager"])
    if fag:
        fag = fag.strip().upper().replace("Ø", "O")
        aktive = {f: n for f, n in aktive.items() if f == fag}
    if not aktive or minutter < MIN_BLOKK:
        return []
    mestring = mestring_per_tema(db)
    sist = {(r["fag"], r["tema"]): r["sist_ovd"] for r in db.execute("SELECT fag, tema, sist_ovd FROM temaer")}
    i_planen = {(b["fag"], b["tema"]) for b in blokker_for(db, idag) if b["status"] == "planlagt"}
    igjen, okt = minutter, []

    def legg_til(f, tema, mate, lengde, grunn):
        nonlocal igjen
        lengde = min(lengde, igjen)
        if lengde >= MIN_BLOKK:
            okt.append(Oktblokk(f, tema, mate, lengde, grunn))
            igjen -= lengde

    etter_hast = sorted(aktive, key=aktive.get)
    for f in etter_hast:
        if feil := len(forfalte_sporsmal(db, f)):
            legg_til(f, "", "feilsvar", min(blokk, max(MIN_BLOKK, 3 * feil)),
                     f"{feil} feilsvar venter, eksamen om {aktive[f]} dager")
            break
    for f in etter_hast:
        if (antall := _kort_som_venter(db, f)) >= KORT_FOR_BLOKK:
            legg_til(f, "", "flashcards", MIN_BLOKK, f"{antall} flashcards venter på repetisjon")
            break

    kandidater = []
    for f, dager in aktive.items():
        for tema in temaer[f]:
            m = mestring.get((f, tema), 0.5)
            poeng = (1.2 - m) / max(dager, 1)
            if (sist.get((f, tema)) or "")[:10] == idag.isoformat():
                poeng /= 2
            if (f, tema) in i_planen:
                poeng *= 1.5
            grunn = (f"mestring {round(m * 100)} %" if (f, tema) in mestring else "aldri øvd på") + \
                    f", eksamen om {dager} dager"
            kandidater.append((-poeng, len(kandidater), f, tema, grunn))
    from src.modeller import FILER as modellfag
    nr = {}                 # blokker per fag så langt, så annenhver blir modelløving (som i planen)
    for *_, f, tema, grunn in sorted(kandidater):
        if igjen < MIN_BLOKK:
            break
        mate = ovingsmate_for(aktive[f], innst["repetisjonsdager"])
        if aktive[f] <= MODELLOVING_FRA:
            mate = med_modelloving(mate, nr.get(f, 0), f in modellfag)
        nr[f] = nr.get(f, 0) + 1
        legg_til(f, tema, mate, blokk, grunn)
    return okt


def okt_som_tekst(okt: list[Oktblokk], minutter: int) -> str:
    if not okt:
        return f"Fant ingenting å sette opp på {minutter} minutter (minst {MIN_BLOKK} minutter, og bare fag med eksamen fremover)."
    linjer = [f"Økt på {sum(b.minutter for b in okt)} av {minutter} minutter:"]
    for nr, b in enumerate(okt, start=1):
        hva = b.tema or {"feilsvar": "feilsvar på nytt", "flashcards": "alle kort som skal repeteres"}[b.ovingsmate]
        linjer.append(f"{nr}. {b.fag} {b.ovingsmate}, {b.minutter} min: {hva} ({b.grunn})")
    return "\n".join(linjer)


# ---------- tid i spørsmålet ----------

_TALLORD = {"en": 1, "ett": 1, "én": 1, "to": 2, "tre": 3, "fire": 4, "fem": 5, "seks": 6, "sju": 7, "syv": 7,
            "åtte": 8, "halvannen": 1.5, "halv": 0.5}
_TID = re.compile(r"\b(\d+(?:[.,]\d+)?|" + "|".join(sorted(_TALLORD, key=len, reverse=True)) +
                  r")\s*(timer|time|t|minutter|minutt|min)\b", re.I)


def minutter_i(tekst: str) -> int | None:
    """«to timer» → 120, «1,5 time» → 90, «45 min» → 45, «en halvtime» → 30. None hvis ingen tid er oppgitt."""
    if re.search(r"\bhalvtime\b", tekst, re.I):
        return 30
    if not (treff := _TID.search(tekst)):
        return None
    tall, enhet = treff.group(1).lower(), treff.group(2).lower()
    verdi = _TALLORD.get(tall) or float(tall.replace(",", "."))
    return round(verdi * (60 if enhet.startswith("t") else 1))


_FAGORD = {"BOA1100": r"bøa|boa|bedriftsøkonomi|økonomistyring", "MRK1001": r"mrk|markedsføring",
           "ORG1100": r"org|organisasjon|ledelse", "MET1001": r"met|metode"}


def fag_i(tekst: str) -> str | None:
    """Faget studenten nevner: «45 min til BØA» → BOA1100. None hvis ingen eller flere fag nevnes."""
    funnet = {f for f, ord_ in _FAGORD.items() if re.search(rf"\b({ord_})", tekst, re.I)}
    return funnet.pop() if len(funnet) == 1 else None


# ---------- agenten ----------

@dataclass
class Veiledersvar:
    sporsmal: str
    tekst: str
    steg: list[Steg] = field(default_factory=list)
    okt: list[Oktblokk] = field(default_factory=list)     # økten fra siste lag_okt, til «Øv nå»-knapper


def _utfor(db, navn: str, argumenter: dict, svar: Veiledersvar) -> tuple[str, str]:
    """Kjører ett verktøy. Returnerer (resultat til modellen, kort tekst til steg-listen)."""
    if navn == "se_status":
        return se_status(db), "eksamener, dagens plan og repetisjoner"
    if navn == "se_mestring":
        ut = se_mestring(db, str(argumenter.get("fag", "")))
        return ut, f"{ut.count(chr(10) + '- ')} temaer"
    if navn == "lag_okt":
        try:
            minutter = int(float(str(argumenter.get("minutter", "")).replace(",", ".")))
        except ValueError:
            return "minutter må være et tall, f.eks. 120.", "ugyldig antall minutter"
        svar.okt = lag_okt(db, minutter, str(argumenter.get("fag") or "") or None)
        return okt_som_tekst(svar.okt, minutter), f"{len(svar.okt)} blokker, {sum(b.minutter for b in svar.okt)} min"
    return f"Ukjent verktøy «{navn}». Velg se_status, se_mestring eller lag_okt.", "ukjent verktøy"


def ukjente_tall(svar: Veiledersvar, resultater: list[str], tekst: str) -> list[float]:
    """Tall i svaret som ikke står i spørsmålet eller i noe verktøyet ga. Minutter ↔ timer (×60, ÷60) er lov."""
    kjente = tall_i(svar.sporsmal) | {x for r in resultater for x in tall_i(r)}
    kjente |= {float(n) for r in resultater for n in re.findall(r"\d+", r)}      # dag og måned i «23.11»
    kjente |= {x * 60 for x in kjente} | {x / 60 for x in kjente}
    return sorted(x for x in tall_i(tekst)
                  if x > 10 or x != int(x)
                  if not any(abs(x - k) <= 1e-6 * max(1, abs(k)) for k in kjente))


def _mangler(svar: Veiledersvar, resultater: list[str], tekst: str) -> str | None:
    """Kontroll før svaret leveres. Returnerer en beskjed til modellen, eller None."""
    tid = minutter_i(svar.sporsmal)
    fag = fag_i(svar.sporsmal)
    okter = [s for s in svar.steg if s.verktoy == "lag_okt"]
    if tid and not okter:
        return f"Studenten har {tid} minutter. Bruk lag_okt med minutter={tid}{f' og fag={fag}' if fag else ''} før du svarer."
    if tid and fag and fag not in okter[-1].inn:
        return f"Studenten vil øve på {fag}. Bruk lag_okt med minutter={tid} og fag={fag}."
    eksamener = last_eksamener()[0]
    if ukjente_fag := sorted(set(re.findall(r"\b[A-ZÆØÅ]{3}\d{4}\b", tekst)) - set(eksamener)):
        return f"Fagene {', '.join(ukjente_fag)} finnes ikke. Fagene er {', '.join(sorted(eksamener))}."
    if ukjente := ukjente_tall(svar, resultater, tekst):
        return (f"Tallene {', '.join(tall_som_tekst(x) for x in ukjente)} kommer ikke fra dataene. "
                "Bruk bare tallene verktøyene ga.")
    return None


# se_status(), se_mestring(MRK1001), lag_okt(120, BOA1100), lag_okt{minutter: 90} – skrevet som tekst
_TEKSTKALL = re.compile(r"\b(se_status|se_mestring|lag_okt)\s*[({]([^)}]*)[)}]")


def _kall_i_tekst(tekst: str) -> list[dict]:
    kall = []
    for i, (navn, inni) in enumerate(_TEKSTKALL.findall(tekst)):
        argumenter = {}
        if fag := re.search(r"[A-ZÆØÅ]{3}\d{4}", inni):
            argumenter["fag"] = fag.group()
        if navn == "lag_okt" and (tall := re.search(r"\d+", inni.replace(argumenter.get("fag", ""), ""))):
            argumenter["minutter"] = int(tall.group())
        kall.append({"id": f"tekst{i}", "navn": navn, "argumenter": argumenter})
    return kall


def kjor_veileder(sporsmal: str, vis_steg=None, db=None) -> Veiledersvar:
    """vis_steg(steg): kalles etter hvert steg, så terminal og app kan vise hva veilederen gjør."""
    db = db or koble()
    resultat = Veiledersvar(sporsmal, "")
    utfort: dict[tuple, str] = {}

    def kjor(kall: dict) -> str:
        nokkel = (kall["navn"], tuple(sorted((k, str(v)) for k, v in kall["argumenter"].items())))
        if nokkel not in utfort:
            utfort[nokkel], kort = _utfor(db, kall["navn"], kall["argumenter"], resultat)
            inn = ", ".join(str(v) for v in kall["argumenter"].values())
            resultat.steg.append(Steg(kall["navn"], inn, kort))
            if vis_steg:
                vis_steg(resultat.steg[-1])
        return utfort[nokkel]

    # Koden henter status først, så veilederen alltid starter fra dataene dine.
    forste = {"id": "start", "navn": "se_status", "argumenter": {}}
    samtale = [{"rolle": "bruker", "tekst": sporsmal},
               {"rolle": "assistent", "tekst": "", "kall": [forste]},
               {"rolle": "verktoy", "id": "start", "navn": "se_status", "resultat": kjor(forste)}]

    for _ in range(MAKS_STEG):
        try:
            svar = chat_med_verktoy(SYSTEM, samtale, VERKTOY)
        except TimeoutError:
            continue
        kall = svar["kall"] or _kall_i_tekst(svar["tekst"])
        if kall:
            samtale.append({"rolle": "assistent", "tekst": "" if not svar["kall"] else svar["tekst"], "kall": kall})
            for k in kall:
                samtale.append({"rolle": "verktoy", "id": k["id"], "navn": k["navn"], "resultat": kjor(k)})
            continue

        beskjed = _mangler(resultat, list(utfort.values()), svar["tekst"])
        tilbake = sum(s.verktoy == "kontroll" for s in resultat.steg)
        if beskjed is None or tilbake >= MAKS_TILBAKE:
            resultat.tekst = svar["tekst"].strip()
            if beskjed:
                resultat.tekst += f"\n\n(Kontrollen er ikke helt fornøyd: {beskjed.split('.')[0]}.)"
            return resultat
        resultat.steg.append(Steg("kontroll", "", beskjed))
        if vis_steg:
            vis_steg(resultat.steg[-1])
        samtale.append({"rolle": "assistent", "tekst": svar["tekst"], "kall": []})
        samtale.append({"rolle": "bruker", "tekst": beskjed + " Bruk verktøyet nå, ikke skriv om det."})
    resultat.tekst = "Veilederen brukte for mange steg uten å bli ferdig. Prøv å spørre enklere."
    return resultat


def vis_steg_i_terminal(steg: Steg):
    ikon = {"se_status": "📋", "se_mestring": "📈", "lag_okt": "🗓️", "kontroll": "↩"}.get(steg.verktoy, "·")
    print(f"  {ikon} {steg.verktoy}({steg.inn}) → {steg.ut}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Studieveilederen: hva bør du øve på nå?")
    parser.add_argument("sporsmal", nargs="*", default=["Hva bør jeg øve på i dag?"])
    sporsmal = " ".join(parser.parse_args().sporsmal)
    print(f"\n## {sporsmal}\n\nVeilederen jobber:")
    svar = kjor_veileder(sporsmal, vis_steg_i_terminal)
    print(f"\n{svar.tekst}\n")
    if svar.okt:
        print(okt_som_tekst(svar.okt, sum(b.minutter for b in svar.okt)))
