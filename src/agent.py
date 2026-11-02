"""BØA-agenten: en språkmodell som selv velger verktøy for å løse bedriftsøkonomi-oppgaver.

Forskjellen fra resten av boten: i svar.py bestemmer koden rekkefølgen (søk → svar). Her
bestemmer modellen selv hva den gjør neste, i en løkke:

    oppgave → modellen velger handling → koden utfører den → resultatet tilbake → ... → svar

Handlingene:
  sok_i_pensum  søker i BØA-pensumet (samme søk og reranker som chatten)
  regn_ut       en trygg kalkulator i Python. Modellen skal aldri regne selv, for språkmodeller
                gjør regnefeil, og på BØA-eksamen må tallene stemme.

Sikringer i koden, fordi en liten lokal modell er en ustø agent (målt: den hoppet over verktøyene,
skrev verktøykall som vanlig tekst og regnet i hodet):
  - koden søker først med spørsmålet, så agenten alltid starter fra pensum (den kan søke mer selv)
  - verktøykall skrevet som tekst, f.eks. regn_ut{uttrykk: "..."}, fanges opp og kjøres likevel
  - før svaret vises, sjekkes det at tall og kilder faktisk kommer fra verktøyene

Kjør:  uv run python -m src.agent "Faste kostnader er 450 000, pris 250 og variable kostnader 130 per enhet. Hva er nullpunktet?"
"""

import argparse
import ast
import operator
import re
from dataclasses import dataclass, field

from src.henting import Bit, hent
from src.llm import chat_med_verktoy

FAG = "BOA1100"
MAKS_STEG = 10         # sikring: agenten kan ikke gå i løkke for alltid
MAKS_TILBAKE = 2       # så mange ganger kontrollen kan sende agenten tilbake før svaret leveres med en merknad

SYSTEM = """Du er hjelpelærer i bedriftsøkonomi (BØA1100) for en student som skal ta eksamen uten kalkulator.

Du har to verktøy:
- sok_i_pensum: slår opp i studentens pensum (foiler, notater, oppgaver).
- regn_ut: regner ut et uttrykk nøyaktig.

Regler:
1. Bruk pensum til å finne riktig formel eller metode. Tekstbitene kan inneholde andre oppgaver; løs bare studentens oppgave.
2. ALL regning skal gjøres med regn_ut, også enkle stykker og summer. Ikke regn noe i hodet.
   Send gjerne hele uttrykket på én gang, for eksempel «450000 / (250 - 130)».
3. Et svar på en regneoppgave har tre deler: formelen fra pensum med kilde, utregningen med tallene satt inn,
   og svaret. Svar på ALLE delene av oppgaven.
4. Vis til tekstbitene med nummeret, for eksempel [1] eller [2][3].
5. Finner du ikke metoden i pensum, si det, og ikke finn på en egen.
Svar på norsk, kort og ryddig, uten å nevne verktøyene. Skriv vanlig tekst, ikke LaTeX, og ikke be om unnskyldning."""

VERKTOY = [
    {"navn": "sok_i_pensum",
     "beskrivelse": "Søker i BØA-pensumet og gir de mest relevante tekstbitene, nummerert. "
                    "Bruk for begreper, formler, metoder og oppsett.",
     "parametre": {"type": "object", "required": ["sporsmal"],
                   "properties": {"sporsmal": {"type": "string", "description": "Hva du leter etter, f.eks. «nullpunkt formel»"}}}},
    {"navn": "regn_ut",
     "beskrivelse": "Regner ut et matematisk uttrykk nøyaktig. Bruk ALLTID dette for tall. "
                    "Støtter + - * / ** og parenteser, f.eks. «450000 / (250 - 130)».",
     "parametre": {"type": "object", "required": ["uttrykk"],
                   "properties": {"uttrykk": {"type": "string", "description": "Uttrykket som skal regnes ut"}}}},
]
ARGUMENT = {"sok_i_pensum": "sporsmal", "regn_ut": "uttrykk"}


# ---------- verktøy 1: trygg kalkulator ----------

_OPERATORER = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
               ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def regn(uttrykk: str) -> float:
    """Regner ut uttrykket uten eval(): bare tall, + - * / ** %, og parenteser er lov.

    Tåler norsk skrivemåte: «450 000» (mellomrom i tall), «1,5» (desimalkomma) og «25 %».
    """
    tekst = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", uttrykk)          # 450 000 → 450000
    tekst = re.sub(r"(?<=\d),(?=\d)", ".", tekst)                        # 1,5 → 1.5
    tekst = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", tekst)           # 25 % → (25/100)
    tekst = tekst.replace("×", "*").replace("·", "*").replace("−", "-").replace("^", "**")

    def verdi(node):
        if isinstance(node, ast.Expression):
            return verdi(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORER:
            venstre, hoyre = verdi(node.left), verdi(node.right)
            if isinstance(node.op, ast.Pow) and abs(hoyre) > 100:
                raise ValueError("for stor eksponent")
            return _OPERATORER[type(node.op)](venstre, hoyre)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORER:
            return _OPERATORER[type(node.op)](verdi(node.operand))
        raise ValueError(f"ikke lov i en utregning: {ast.dump(node)[:40]}")

    return verdi(ast.parse(tekst.strip(), mode="eval"))


def tall_som_tekst(x: float) -> str:
    """2750.0 → «2 750», 0.4166666 → «0,4167»."""
    if abs(x - round(x)) < 1e-9:
        return f"{round(x):,}".replace(",", " ")
    return f"{x:,.4f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")


# ---------- agenten ----------

@dataclass
class Steg:
    verktoy: str
    inn: str
    ut: str


@dataclass
class Agentsvar:
    sporsmal: str
    tekst: str
    steg: list[Steg] = field(default_factory=list)
    biter: list[Bit] = field(default_factory=list)      # alle biter fra søkene, nummerert [1], [2], ...


def _utfor(handling: str, inndata: str, biter: list[Bit]) -> str:
    """Utfører én handling og returnerer resultatet modellen får se."""
    if handling == "regn_ut":
        try:
            return f"{inndata} = {tall_som_tekst(regn(inndata))}"
        except (ValueError, SyntaxError, ZeroDivisionError) as feil:
            return f"Kunne ikke regne ut «{inndata}»: {feil}. Skriv uttrykket med tall og + - * / ( )."
    if handling == "sok_i_pensum":
        deler = []
        for bit in hent(inndata, fag=FAG, k=4):
            if bit not in biter:
                biter.append(bit)
            deler.append(f"[{biter.index(bit) + 1}] ({bit.kilde})\n{bit.tekst}")
        return "\n\n".join(deler) or "Fant ingenting i pensum om dette."
    return f"Ukjent handling «{handling}». Velg sok_i_pensum, regn_ut eller svar."


def _mangler(svar: Agentsvar, tekst: str) -> str | None:
    """Kontroll i koden før agenten får levere: har den faktisk brukt verktøyene den skal?

    Instruksen alene er ikke nok. En liten modell kan skrive «[1]» uten å ha søkt, eller regne i hodet.
    Returnerer en beskjed tilbake til modellen, eller None hvis svaret kan leveres.
    """
    if "sok_i_pensum" not in {s.verktoy for s in svar.steg}:
        return "Du har ikke søkt i pensum ennå. Bruk sok_i_pensum før du svarer, og vis til bitene du får."
    if feil := kontrollregn(svar, tekst):
        return feil
    ugyldige = sorted({int(n) for n in re.findall(r"\[(\d+)\]", tekst)} - set(range(1, len(svar.biter) + 1)))
    if ugyldige:
        return f"Du viser til {ugyldige}, men du har bare fått tekstbitene 1–{len(svar.biter)}. Vis bare til biter du har fått."
    if ukjente := ukjente_tall(svar, tekst):
        return (f"Tallene {', '.join(tall_som_tekst(x) for x in ukjente)} i svaret kommer ikke fra oppgaven, pensum "
                "eller en utregning. Vis utregningen, eller regn dem ut med regn_ut.")
    return None


_UTTRYKK = re.compile(r"-?\(?\d[\d \u00a0.,()+\-*/×^]*[\d)]")
_ER_LIK = re.compile(r"\s*=\s*(-?\d{1,3}(?:[ \u00a0]\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?)")


def kontrollregn(svar: Agentsvar, tekst: str) -> str | None:
    """Koden regner selv ut hvert regnestykke i svaret, f.eks. «600000 / (400 - 250) = 4000».

    En liten modell bruker ikke alltid kalkulatoren. Da sjekker koden regningen i stedet: hvert
    uttrykk regnes ut i Python og legges i steg-listen («kontrollregning»). Står det «= tall» etter
    uttrykket, må tallet stemme. Returnerer en beskjed hvis noe er feil regnet.
    """
    for treff in _UTTRYKK.finditer(tekst):
        uttrykk = treff.group().strip()
        if not re.search(r"\d\s*[-+*/×^]\s*[\d(]", uttrykk):
            continue                               # ikke et regnestykke (dato, tall alene)
        try:
            verdi = regn(uttrykk)
        except (ValueError, SyntaxError, ZeroDivisionError):
            continue
        if not any(s.inn == uttrykk for s in svar.steg):
            svar.steg.append(Steg("kontrollregning", uttrykk, f"{uttrykk} = {tall_som_tekst(verdi)}"))
        if likhet := _ER_LIK.match(tekst, treff.end()):
            pastatt = next(iter(tall_i(likhet.group(1))), None)
            if pastatt is not None and abs(abs(pastatt) - abs(verdi)) > max(0.6, 0.005 * abs(verdi)):
                return (f"Regnefeil: {uttrykk} er {tall_som_tekst(verdi)}, ikke {likhet.group(1)}. "
                        "Rett utregningen, eller bruk regn_ut.")
    return None


_TALL = re.compile(r"\d{1,3}(?:[ \u00a0]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def tall_i(tekst: str) -> set[float]:
    """Alle tall i en tekst, på norsk eller engelsk form: «450 000», «0,375», «37.5»."""
    tekst = re.sub(r"\[\d+\]", "", tekst)                  # kildenumre er ikke tall i utregningen
    return {float(t.replace(" ", "").replace("\u00a0", "").replace(",", ".")) for t in _TALL.findall(tekst)}


def ukjente_tall(svar: Agentsvar, tekst: str) -> list[float]:
    """Tall i svaret som verken står i oppgaven, i pensumbitene eller i en utregning fra regn_ut.

    Små heltall (punktnummer, «2 enheter») og x·100 / x/100 av kjente tall (prosent) er lov.
    """
    kjente = tall_i(svar.sporsmal) | {x for b in svar.biter for x in tall_i(b.tekst)}
    kjente |= {x for s in svar.steg if s.verktoy in ("regn_ut", "kontrollregning") for x in tall_i(s.ut)}
    kjente |= {x * 100 for x in kjente} | {x / 100 for x in kjente}
    return sorted(x for x in tall_i(tekst)
                  if x > 10 or x != int(x)
                  if not any(abs(x - k) <= 1e-6 * max(1, abs(k)) for k in kjente))


_LATEX = {r"\times": "×", r"\cdot": "·", r"\div": "/", r"\approx": "≈", r"\%": "%", r"\,": " "}


def uten_latex(tekst: str) -> str:
    """Små modeller skriver LaTeX selv om de blir bedt om å la være: «120 $\\times$ 5000» → «120 × 5000»."""
    for kode, tegn in _LATEX.items():
        tekst = tekst.replace(kode, tegn)
    tekst = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1) / (\2)", tekst)
    tekst = re.sub(r"\\text\{([^{}]*)\}", r"\1", tekst)
    return re.sub(r"\$\$?([^$]*)\$?\$", r"\1", tekst)


# regn_ut(120 * 0.15), regn_ut{uttrykk: "120 + 80"}, sok_i_pensum("nullpunkt") – én per linje
_TEKSTKALL = re.compile(r"(sok_i_pensum|regn_ut)\s*[({]\s*(?:\w+\s*[:=]\s*)?[\"«']?(.+?)[\"»']?\s*[)}][\]`*.]*\s*$", re.M)


def _kall_i_tekst(tekst: str) -> list[dict]:
    """Verktøykall som modellen skrev som tekst i stedet for å kalle, f.eks. regn_ut{uttrykk: "120 + 80"}."""
    return [{"id": f"tekst{i}", "navn": navn, "argumenter": {ARGUMENT[navn]: arg}}
            for i, (navn, arg) in enumerate(_TEKSTKALL.findall(tekst))]


def kjor_agent(sporsmal: str, vis_steg=None) -> Agentsvar:
    """vis_steg(steg): kalles etter hvert steg, så terminal og app kan vise hva agenten gjør."""
    resultat = Agentsvar(sporsmal, "")
    utfort: dict[tuple, str] = {}                  # verktøykall som allerede er kjørt

    def kjor(kall: dict) -> str:
        navn, arg = kall["navn"], str(kall["argumenter"].get(ARGUMENT.get(kall["navn"], ""), "")).strip()
        nokkel = (navn, arg)
        if nokkel not in utfort:                   # samme kall to ganger: samme svar, uten å vise det igjen
            utfort[nokkel] = _utfor(navn, arg, resultat.biter)
            kort = utfort[nokkel] if navn != "sok_i_pensum" else \
                f"{len(re.findall(r'^\[\d+\] \(', utfort[nokkel], re.M))} tekstbiter"
            resultat.steg.append(Steg(navn, arg, kort))
            if vis_steg:
                vis_steg(resultat.steg[-1])
        return utfort[nokkel]

    # Første søk gjøres av koden, så agenten alltid starter fra pensum.
    forste = {"id": "start", "navn": "sok_i_pensum", "argumenter": {"sporsmal": sporsmal}}
    samtale = [{"rolle": "bruker", "tekst": sporsmal},
               {"rolle": "assistent", "tekst": "", "kall": [forste]},
               {"rolle": "verktoy", "id": "start", "navn": "sok_i_pensum", "resultat": kjor(forste)}]

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

        svar["tekst"] = uten_latex(svar["tekst"])
        beskjed = _mangler(resultat, svar["tekst"])          # modellen vil svare: kontroller først
        tilbake = sum(s.verktoy == "kontroll" for s in resultat.steg)
        if beskjed is None or tilbake >= MAKS_TILBAKE:
            resultat.tekst = svar["tekst"].strip()
            if beskjed:                            # ærlig merknad i stedet for en evig løkke
                resultat.tekst += f"\n\n(Kontrollen er ikke helt fornøyd: {beskjed.split('.')[0]}.)"
            return resultat
        resultat.steg.append(Steg("kontroll", "", beskjed))
        if vis_steg:
            vis_steg(resultat.steg[-1])
        samtale.append({"rolle": "assistent", "tekst": svar["tekst"], "kall": []})
        samtale.append({"rolle": "bruker", "tekst": beskjed + " Bruk verktøyet nå, ikke skriv om det."})
    resultat.tekst = "Agenten brukte for mange steg uten å bli ferdig. Prøv å dele opp oppgaven."
    return resultat


def kildeliste(svar: Agentsvar) -> list[str]:
    """Bitene svaret viser til med [n], i formatet BOA1100/fil, s. N."""
    numre = sorted({int(n) for n in re.findall(r"\[(\d+)\]", svar.tekst)})
    return [f"[{n}] {FAG}/{svar.biter[n - 1].kilde}" for n in numre if 1 <= n <= len(svar.biter)]


def vis_steg_i_terminal(steg: Steg):
    if steg.verktoy == "regn_ut":
        print(f"  🧮 regner:  {steg.ut}")
    elif steg.verktoy == "kontroll":
        print(f"  ↩  sendt tilbake: {steg.ut}")
    elif steg.verktoy == "kontrollregning":
        print(f"  ✔  kontrollregnet av koden: {steg.ut}")

    else:
        print(f"  🔎 søker:   «{steg.inn}» → {steg.ut}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BØA-agenten: søker i pensum og regner med kalkulator.")
    parser.add_argument("sporsmal", nargs="+")
    sporsmal = " ".join(parser.parse_args().sporsmal)
    print(f"\n## {sporsmal}\n\nAgenten jobber:")
    svar = kjor_agent(sporsmal, vis_steg_i_terminal)
    print(f"\n{svar.tekst}\n")
    if kilder := kildeliste(svar):
        print("Kilder:\n  " + "\n  ".join(kilder))
