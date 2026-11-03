"""BØA-formlene: formelark og formeltrening, regnet ut i Python (ingen språkmodell).

BØA-eksamen er uten hjelpemidler, så formlene må sitte, og du må kunne snu dem. Hver formel her
er hentet fra pensum, med kilde. Treningen lager fem typer oppgaver:

  formel      «Hva er formelen for nullpunktomsetning?»       (flervalg)
  snu         «Snu NPO = FK/DG. Hva er FK?»                    (flervalg)
  regn        «FK = 300 000 og DG = 40 %. Finn NPO.»          (tall)
  hva_skjer   «VEK øker. Hva skjer med nullpunktet?»          (øker / synker / uendret)
  sammenheng  regn gjennom to–tre formler, f.eks. pris og VEK → DB → DG → NPO

Formlene snus med sympy (symbolsk algebra), og fasiten regnes ut i Python, så den er alltid riktig.
Tallene velges slik at de går opp uten kalkulator, som på eksamen.

Kjør:  uv run python -m src.formler                (formelarket i terminalen)
       uv run python -m src.formler --ov 10        (ti treningsoppgaver)
"""

import argparse
import random
import re
from dataclasses import dataclass, field

import sympy as sp
from sympy.printing.str import StrPrinter

FAG = "BOA1100"
L1 = "eksamener/losning/Del 1_Regnskap_Løsningsforslag eksamensoppgaver Bedriftsøkonomi med regnskap_Lang.pdf"
L2 = "eksamener/losning/Del 2_Kostnadsforståelse og kalkyler_Løsningsforslag eksamensoppgaver Bedriftsøkonomi med regnskap_Lang.pdf"
L3 = "eksamener/losning/Del 3_Kortsiktige beslutningsproblemer_Løsningsforslag eksamensoppgaver Bedriftsøkonomi med regnskap_Lang.pdf"
L4 = "eksamener/losning/Del 4_Langsiktige beslutningsproblemer_Løsningsforslag eksamensoppgaver Bedriftsøkonomi med regnskap_Lang.pdf"
LANGSIKTIG = "oppgaver/Langsiktige_beslutningproblemer_spm.docx"
REGNSKAP_FOIL = "foiler/goodnotes/for11_13_regnskap_periodisering_stud_2026.pdf"

# Temaene fra config/eksamener.yaml, så treningen teller med i mestringen og planen
KOSTNADER = "Kostnader og kostnadsbegreper"
NULLPUNKT = "Nullpunktsanalyser"
KALKULASJON = "Kalkulasjon"
KORTSIKTIG = "Kortsiktige beslutningsproblemer"
MARKED = "Markedstilpasning"
LANGSIKTIG_TEMA = "Langsiktige beslutningsproblemer og investeringsanalyse"
REGNSKAP = "Regnskap: innledning og balanseligningen"
PERIODISERING = "Periodisering og regnskapsoppsummering"
TEMAREKKEFOLGE = [KOSTNADER, NULLPUNKT, KALKULASJON, KORTSIKTIG, MARKED, LANGSIKTIG_TEMA, REGNSKAP, PERIODISERING]


@dataclass
class Variabel:
    tekst: str                   # «variable enhetskostnader»
    verdier: tuple = ()          # pene verdier å trekke fra i regneoppgaver
    prosent: bool = False        # vises som «40 %», regnes som 0,4
    negativ: bool = False        # kan være mindre enn null (resultat, elastisitet ...)
    enhet: str = "kr"


V = Variabel
VARIABLER: dict[str, Variabel] = {
    "pris": V("pris per enhet eks. mva.", (100, 120, 150, 200, 250, 300, 400, 500, 600, 800, 1000)),
    "VEK": V("variable enhetskostnader", (40, 50, 60, 75, 80, 100, 120, 150, 200, 240, 300, 400)),
    "DB": V("dekningsbidrag per enhet", (20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 150, 200)),
    "DG": V("dekningsgrad", (0.2, 0.25, 0.3, 0.4, 0.5, 0.6), prosent=True),
    "FK": V("faste kostnader", (60_000, 100_000, 120_000, 150_000, 200_000, 240_000, 300_000, 400_000, 600_000)),
    "x": V("antall solgte enheter", (500, 1000, 2000, 2500, 3000, 4000, 5000, 6000, 8000, 10_000), enhet="enheter"),
    "R": V("resultat", negativ=True),
    "MR": V("målsatt resultat", (50_000, 60_000, 100_000, 120_000, 150_000, 200_000, 300_000)),
    "NPE": V("nullpunkt i antall enheter", enhet="enheter"),
    "NPO": V("nullpunktomsetning", (200_000, 300_000, 400_000, 500_000, 600_000, 750_000)),
    "MO": V("målsatt omsetning"),
    "OMS": V("forventet omsetning", (500_000, 600_000, 800_000, 1_000_000, 1_200_000, 1_500_000, 2_000_000)),
    "SM": V("sikkerhetsmargin", prosent=True),
    "TK": V("totale kostnader"),
    "TK0": V("totale kostnader ved lav aktivitet", (100_000, 150_000, 200_000, 250_000, 300_000)),
    "TK1": V("totale kostnader ved høy aktivitet"),
    "x0": V("lav aktivitet", (1000, 2000, 3000, 4000), enhet="enheter"),
    "x1": V("høy aktivitet", (5000, 6000, 8000, 10_000), enhet="enheter"),
    "SK": V("selvkost per enhet", (400, 500, 600, 800, 1000, 1200, 1500, 2000)),
    "P": V("fortjenestepåslag i % av selvkost", (0.1, 0.2, 0.25, 0.5), prosent=True),
    "FP": V("fortjenesteprosent i % av prisen", (0.1, 0.2, 0.25, 0.5), prosent=True),
    "MVA": V("mva-sats", (0.25,), prosent=True),
    "PI": V("pris inkl. mva."),
    "TS": V("tilleggssats", prosent=True),
    "IK": V("indirekte kostnader i avdelingen", (20_000, 30_000, 50_000, 60_000, 100_000, 120_000)),
    "FG": V("fordelingsgrunnlag", (100_000, 200_000, 240_000, 300_000, 400_000, 500_000)),
    "BF": V("bruttofortjeneste i %", prosent=True),
    "VK": V("varekostnad per enhet", (40, 60, 75, 80, 90, 120, 150, 300)),
    "OI": V("ordreinntekt", (20_000, 30_000, 50_000, 60_000, 75_000, 100_000)),
    "RK": V("beslutningsrelevante kostnader for ordren", (15_000, 25_000, 40_000, 45_000, 60_000, 80_000)),
    "DBO": V("dekningsbidrag fra ordren", negativ=True),
    "EP": V("priselastisitet", (-0.5, -1, -1.5, -2, -2.5, -3), negativ=True, enhet=""),
    "PE": V("relativ prisendring", (-0.2, -0.1, -0.05, 0.05, 0.1, 0.2), prosent=True, negativ=True),
    "ME": V("relativ mengdeendring", prosent=True, negativ=True),
    "a": V("a i priskurven p = a − b · x", (60, 100, 400, 1000, 2000, 4000)),
    "b": V("b i priskurven p = a − b · x", (0.01, 0.02, 0.05, 0.1, 0.2, 0.5), enhet=""),
    "XOPT": V("optimal mengde", enhet="enheter"),
    "AV": V("anskaffelsesverdi", (100_000, 150_000, 200_000, 250_000, 500_000, 1_000_000)),
    "RV": V("restverdi", (0, 10_000, 20_000, 50_000, 100_000)),
    "N": V("levetid i år", (2, 4, 5, 8, 10), enhet="år"),
    "AVS": V("årlig avskrivning"),
    "IBV": V("bokført verdi ved periodens begynnelse", (100_000, 200_000, 400_000, 500_000, 1_000_000)),
    "SATS": V("saldoavskrivningssats", (0.1, 0.2, 0.25, 0.3), prosent=True),
    "SAVS": V("årets saldoavskrivning"),
    "SS": V("salgssum eks. mva.", (20_000, 30_000, 50_000, 80_000, 100_000)),
    "BV": V("bokført verdi", (10_000, 25_000, 36_000, 40_000, 60_000)),
    "G": V("gevinst eller tap", negativ=True),
    "AM": V("anleggsmidler", (100_000, 200_000, 300_000, 500_000, 800_000)),
    "OM": V("omløpsmidler", (50_000, 100_000, 150_000, 200_000, 300_000)),
    "EK": V("egenkapital", negativ=True),
    "LG": V("langsiktig gjeld", (100_000, 150_000, 200_000, 300_000)),
    "KG": V("kortsiktig gjeld", (40_000, 50_000, 80_000, 100_000)),
    "AK": V("arbeidskapital", negativ=True),
    "IBL": V("IB varelager", (50_000, 70_000, 100_000, 120_000)),
    "KJOP": V("varekjøp eks. mva.", (200_000, 250_000, 300_000, 400_000)),
    "VF": V("vareforbruk", (220_000, 260_000, 300_000, 350_000)),
    "UBL": V("UB varelager"),
    "INNT": V("periodens inntekt eks. mva.", (80_000, 100_000, 200_000, 400_000)),
    "IBKF": V("IB kundefordringer inkl. mva.", (10_000, 20_000, 25_000, 50_000)),
    "UBKF": V("UB kundefordringer inkl. mva.", (5_000, 15_000, 18_000, 30_000)),
    "INNB": V("periodens innbetaling"),
    "KOST": V("periodens kostnad eks. mva.", (40_000, 80_000, 100_000, 200_000)),
    "IBLG": V("IB leverandørgjeld inkl. mva.", (10_000, 20_000, 30_000)),
    "UBLG": V("UB leverandørgjeld inkl. mva.", (5_000, 15_000, 25_000)),
    "UTB": V("periodens utbetaling"),
    "I0": V("investering i år 0", (200, 300, 400, 500, 600, 1000)),
    "X1": V("kontantstrøm år 1", (110, 220, 330, 440, 550)),
    "X2": V("kontantstrøm år 2", (121, 242, 363, 484, 605)),
    "r": V("avkastningskrav", (0.1,), prosent=True),
    "NNV": V("netto nåverdi", negativ=True),
    "K": V("beløp i dag", (100, 200, 500, 1000)),
    "n": V("antall år", (1, 2), enhet="år"),
    "SV": V("sluttverdi"),
    "RM": V("rente per periode", (0.01, 0.02, 0.05, 0.1), prosent=True),
    "M": V("antall perioder per år", (2,), enhet=""),
    "REFF": V("effektiv årsrente", prosent=True),
    "X": V("årlig innbetalingsoverskudd", (20, 25, 40, 50, 100)),
    "TBT": V("tilbakebetalingstid", enhet="år"),
    "RF": V("risikofri rente", (0.02, 0.03, 0.04, 0.05), prosent=True),
    "RP": V("risikotillegg", (0.02, 0.03, 0.04, 0.05, 0.06), prosent=True),
    "A": V("annuitet"),
}
S = {navn: sp.Symbol(navn) for navn in VARIABLER}


@dataclass
class Formel:
    id: str
    navn: str
    tema: str
    lhs: str                    # variabelen formelen gir
    rhs: sp.Expr
    kilde: str                  # fil i BOA1100-pensumet, med side
    bruk: str                   # én setning om når den brukes
    visning: str = ""           # formelen slik den står i pensum (ellers skrives den fra sympy)
    ikke_snu: tuple = ()        # variabler som ikke kan løses ut pent (renten i NNV ...)
    regnes: bool = True         # False: for tung å regne uten kalkulator, bare formel og snu
    trekk: str | None = None    # variabelen som regnes ut når tallene lages (standard: lhs)

    @property
    def likning(self) -> sp.Eq:
        return sp.Eq(S[self.lhs], self.rhs)

    @property
    def variabler(self) -> list[str]:
        return [self.lhs] + sorted(str(s) for s in self.rhs.free_symbols)


def F(id_, navn, tema, lhs, rhs, kilde, bruk, **ekstra):
    return Formel(id_, navn, tema, lhs, rhs, kilde, bruk, **ekstra)


s = S
FORMLER = [
    F("tk", "Totale kostnader", KOSTNADER, "TK", s["VEK"] * s["x"] + s["FK"], f"{L2}, s. 39",
      "Kostnadsfunksjonen: variable kostnader per enhet ganger mengde, pluss de faste.", visning="TK = VEK · x + FK"),
    F("topunkt", "Variable enhetskostnader fra to aktivitetsnivåer", KOSTNADER, "VEK",
      (s["TK1"] - s["TK0"]) / (s["x1"] - s["x0"]), f"{L2}, s. 26",
      "Når du kjenner totale kostnader ved to aktiviteter: økningen i kostnad delt på økningen i mengde.",
      trekk="TK1", visning="VEK = (TK1 − TK0)/(x1 − x0)", ikke_snu=("x0", "x1")),
    F("db", "Dekningsbidrag per enhet", NULLPUNKT, "DB", s["pris"] - s["VEK"], f"{L2}, s. 9",
      "Det hver solgte enhet bidrar med til å dekke de faste kostnadene."),
    F("dg", "Dekningsgrad", NULLPUNKT, "DG", s["DB"] / s["pris"], f"{L2}, s. 20",
      "Dekningsbidraget i prosent av prisen."),
    F("resultat", "Resultat", NULLPUNKT, "R", s["DB"] * s["x"] - s["FK"], f"{L3}, s. 21",
      "Samlet dekningsbidrag minus faste kostnader."),
    F("npe", "Nullpunkt i antall enheter", NULLPUNKT, "NPE", s["FK"] / s["DB"], f"{L2}, s. 9",
      "Hvor mange enheter som må selges for å gå i null."),
    F("npo", "Nullpunktomsetning (nullpunkt i kroner)", NULLPUNKT, "NPO", s["FK"] / s["DG"], f"{L3}, s. 2",
      "Hvor stor omsetningen må være for å gå i null."),
    F("mo", "Målsatt omsetning", NULLPUNKT, "MO", (s["FK"] + s["MR"]) / s["DG"], f"{L3}, s. 2",
      "Omsetningen som gir et bestemt resultat. Nullpunktet er spesialtilfellet der målsatt resultat er 0."),
    F("sm", "Sikkerhetsmargin (sikkerhetsgrad)", NULLPUNKT, "SM", (s["OMS"] - s["NPO"]) / s["OMS"], f"{L2}, s. 17",
      "Hvor mye omsetningen kan falle før bedriften går i underskudd, i prosent av forventet omsetning."),
    F("pris_dg", "Pris fra variable kostnader og dekningsgrad", KALKULASJON, "pris", s["VEK"] / (1 - s["DG"]),
      f"{L2}, s. 15", "Prisen som gir ønsket dekningsgrad. Det er DG-formelen snudd."),
    F("pris_paslag", "Pris med fortjenestepåslag på selvkost", KALKULASJON, "pris", s["SK"] * (1 + s["P"]),
      f"{L2}, s. 48", "Påslaget regnes i prosent av selvkost."),
    F("pris_margin", "Pris med fortjenesteprosent av prisen", KALKULASJON, "pris", s["SK"] / (1 - s["FP"]),
      f"{L2}, s. 18", "Fortjenesten regnes i prosent av prisen, ikke av selvkost. Lett å blande med påslag."),
    F("mva", "Pris inkludert mva.", KALKULASJON, "PI", s["pris"] * (1 + s["MVA"]), f"{L2}, s. 36",
      "Mva. legges på prisen eks. mva. Bedriftens inntekt er prisen eks. mva."),
    F("ts", "Tilleggssats", KALKULASJON, "TS", s["IK"] / s["FG"], f"{L2}, s. 37",
      "Indirekte kostnader fordeles på produktene i prosent av et fordelingsgrunnlag."),
    F("bf", "Bruttofortjeneste i %", KALKULASJON, "BF", (s["pris"] - s["VK"]) / s["pris"], f"{L2}, s. 42",
      "Fortjenesten før andre kostnader, i prosent av salgsprisen."),
    F("dbo", "Dekningsbidrag fra en tilleggsordre", KORTSIKTIG, "DBO", s["OI"] - s["RK"], f"{L3}, s. 35",
      "Ved ledig kapasitet: aksepter ordren hvis DB ordre > 0. Bare kostnader som endres av ordren er relevante."),
    F("ep", "Priselastisitet", MARKED, "EP", s["ME"] / s["PE"], f"{L3}, s. 24",
      "Relativ mengdeendring delt på relativ prisendring. Under −1 er etterspørselen elastisk."),
    F("xopt", "Optimal mengde (lineær priskurve)", MARKED, "XOPT", (s["a"] - s["VEK"]) / (2 * s["b"]),
      f"{L3}, s. 33",
      "Fra GI = GK: grenseinntekten a − 2b · x er dobbelt så bratt som priskurven. Sett lik VEK og løs for x."),
    F("lin_avs", "Lineær avskrivning", PERIODISERING, "AVS", (s["AV"] - s["RV"]) / s["N"], f"{REGNSKAP_FOIL}, s. 7",
      "Like store avskrivninger hvert år over levetiden."),
    F("saldo", "Saldoavskrivning", PERIODISERING, "SAVS", s["IBV"] * s["SATS"], f"{L1}, s. 33",
      "Fast prosent av bokført verdi ved periodens begynnelse, så avskrivningene blir mindre hvert år."),
    F("gevinst", "Gevinst eller tap ved salg av anleggsmiddel", PERIODISERING, "G", s["SS"] - s["BV"], f"{L1}, s. 18",
      "Salgssum eks. mva. minus bokført verdi."),
    F("ub_lager", "Utgående varelager", PERIODISERING, "UBL", s["IBL"] + s["KJOP"] - s["VF"], f"{L1}, s. 11",
      "Det du hadde, pluss det du kjøpte, minus det du brukte."),
    F("innbetaling", "Periodens innbetaling fra kunder", PERIODISERING, "INNB",
      s["INNT"] * (1 + s["MVA"]) + s["IBKF"] - s["UBKF"], f"{L1}, s. 15",
      "Inntekt inkl. mva., pluss det kundene skyldte ved start, minus det de skylder ved slutt.", ikke_snu=("MVA",)),
    F("utbetaling", "Periodens utbetaling til leverandører", PERIODISERING, "UTB",
      s["KOST"] * (1 + s["MVA"]) + s["IBLG"] - s["UBLG"], f"{L1}, s. 12",
      "Kostnad inkl. mva., pluss det du skyldte ved start, minus det du skylder ved slutt.", ikke_snu=("MVA",)),
    F("balanse", "Balanseligningen", REGNSKAP, "EK", s["AM"] + s["OM"] - s["LG"] - s["KG"], f"{L1}, s. 9",
      "Eiendeler = egenkapital + gjeld, altså AM + OM = EK + LG + KG.", visning="AM + OM = EK + LG + KG"),
    F("ak", "Arbeidskapital", REGNSKAP, "AK", s["OM"] - s["KG"], f"{L1}, s. 33",
      "Omløpsmidler minus kortsiktig gjeld."),
    F("nnv", "Netto nåverdi (to år)", LANGSIKTIG_TEMA, "NNV",
      -s["I0"] + s["X1"] / (1 + s["r"]) + s["X2"] / (1 + s["r"]) ** 2, f"{LANGSIKTIG}",
      "Lønnsom hvis NNV > 0. Generelt: NNV = −I₀ + X₁/(1+r) + X₂/(1+r)² + … + Xₙ/(1+r)ⁿ.",
      ikke_snu=("r", "X1", "X2"), visning="NNV = −I0 + X1/(1 + r) + X2/(1 + r)^2"),
    F("sv", "Sluttverdi (rentesrente)", LANGSIKTIG_TEMA, "SV", s["K"] * (1 + s["r"]) ** s["n"], f"{L4}, s. 24",
      "Hva et beløp i dag er verdt om n år. Snudd: nåverdi = SV/(1+r)ⁿ.", ikke_snu=("r", "n")),
    F("annuitet", "Annuitet", LANGSIKTIG_TEMA, "A",
      s["K"] * s["r"] * (1 + s["r"]) ** s["n"] / ((1 + s["r"]) ** s["n"] - 1), f"{L4}, s. 25",
      "Det like årlige beløpet som har samme nåverdi som K.", ikke_snu=("r", "n"), regnes=False),
    F("eff", "Effektiv årsrente", LANGSIKTIG_TEMA, "REFF", (1 + s["RM"]) ** s["M"] - 1, f"{LANGSIKTIG}",
      "Rente per periode gjort om til årsrente, med rentesrente.", ikke_snu=("M",)),
    F("tbt", "Tilbakebetalingstid (like innbetalinger)", LANGSIKTIG_TEMA, "TBT", s["I0"] / s["X"], f"{L4}, s. 19",
      "Hvor mange år det tar å tjene inn investeringen. Sier ingenting om lønnsomhet etter det."),
    F("krav", "Avkastningskrav", LANGSIKTIG_TEMA, "r", s["RF"] + s["RP"], f"{LANGSIKTIG}",
      "Risikofri rente pluss et tillegg for risiko."),
]
FORMEL = {f.id: f for f in FORMLER}

# Begreper som er lette å blande. Brukes til gale alternativer.
NABOER = {"DG": "DB", "DB": "DG", "NPO": "NPE", "NPE": "NPO", "P": "FP", "FP": "P", "MO": "NPO",
          "TK": "FK", "FK": "TK", "OMS": "MO", "SK": "pris", "VK": "VEK", "VEK": "VK"}


# ---------- skrive formler og tall slik de står i pensum ----------

class _Skriver(StrPrinter):
    """Som sympy sin str(), men med positive ledd først: «pris − VEK», ikke «−VEK + pris»."""

    def _print_Add(self, expr, order=None):
        ledd = sorted(expr.args, key=lambda a: (a.could_extract_minus_sign(), a.is_number))
        tekst = self._print(ledd[0])
        for a in ledd[1:]:
            if a.could_extract_minus_sign():
                tekst += " − " + self.parenthesize(-a, 40)
            else:
                tekst += " + " + self.parenthesize(a, 40)
        return tekst


def _uten_minus(e: sp.Expr) -> tuple[int, sp.Expr]:
    return (-1, -e) if e.could_extract_minus_sign() else (1, e)


def _brok(e: sp.Expr) -> tuple[sp.Expr, sp.Expr]:
    """Én brøk med minus flyttet dit det gir færrest minustegn: −VEK/(DG − 1) → VEK/(1 − DG)."""
    teller, nevner = sp.fraction(sp.together(e))
    fortegn_t, teller = _uten_minus(sp.factor_terms(teller))
    fortegn_n, nevner = _uten_minus(nevner)
    if fortegn_t * fortegn_n < 0:
        if isinstance(nevner, sp.Add):
            nevner = -nevner
        elif isinstance(teller, sp.Add):
            teller = -teller
        elif isinstance(teller, sp.Mul) and any(isinstance(a, sp.Add) for a in teller.args):
            deler = list(teller.args)
            i = next(i for i, a in enumerate(deler) if isinstance(a, sp.Add))
            deler[i] = -deler[i]
            teller = sp.Mul(*deler, evaluate=False)
        else:
            teller = sp.Mul(-1, teller, evaluate=False)
    return teller, nevner


def _ren(tekst: str) -> str:
    tekst = tekst.replace("**", "^").replace("*", " · ").replace("-", "−")
    return re.sub(r"\((\w+) \+ 1\)", r"(1 + \1)", tekst)


def _skriv_brok(e: sp.Expr) -> str:
    p = _Skriver().doprint
    teller, nevner = _brok(e)
    t = p(teller)
    if nevner == 1:
        return _ren(t)
    if isinstance(teller, sp.Add):
        t = f"({t})"
    n = p(nevner)
    if isinstance(nevner, (sp.Add, sp.Mul)):
        n = f"({n})"
    return _ren(f"{t}/{n}")


def skriv(e: sp.Expr) -> str:
    """Formelen som tekst, slik den ville stått i pensum: «(FK + MR)/DG», «VEK/(1 − DG)»."""
    samlet = _skriv_brok(e)
    utvidet = sp.expand(e, deep=False)
    if isinstance(utvidet, sp.Add) and len({sp.fraction(a)[1] for a in utvidet.args} - {1}) > 1:
        e = utvidet
    if isinstance(e, sp.Add):
        ledd = sorted(e.args, key=lambda a: (a.could_extract_minus_sign(), a.is_number))
        deler = [_skriv_brok(ledd[0])] + [(" − " + _skriv_brok(-a)) if a.could_extract_minus_sign()
                                          else (" + " + _skriv_brok(a)) for a in ledd[1:]]
        nevnere = {sp.fraction(a)[1] for a in e.args} - {1}
        if len(nevnere) > 1:                               # NNV: ledd med ulike nevnere leses best hver for seg
            return "".join(deler)
    return samlet


def formel_tekst(f: Formel) -> str:
    return f.visning or f"{f.lhs} = {skriv(f.rhs)}"


def tall(verdi: float, navn: str | None = None) -> str:
    """750000 → «750 000», 0.4 for en prosentvariabel → «40 %»."""
    v = VARIABLER.get(navn) if navn else None
    if v and v.prosent:
        p = round(verdi * 100, 2)
        return f"{p:g} %".replace(".", ",").replace("-", "−")
    if abs(verdi - round(verdi)) < 1e-9:
        return f"{round(verdi):,}".replace(",", " ").replace("-", "−")
    return f"{verdi:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",").replace("-", "−")


def med_enhet(verdi: float, navn: str) -> str:
    v = VARIABLER[navn]
    if v.prosent or not v.enhet:
        return tall(verdi, navn)
    return f"{tall(verdi, navn)} {v.enhet}" if v.enhet != "kr" else f"kr {tall(verdi, navn)}"


def losninger(f: Formel, mal: str) -> sp.Expr:
    """Formelen løst for `mal`, f.eks. NPO = FK/DG løst for FK gir NPO · DG."""
    if mal == f.lhs:
        return f.rhs
    svar = [l for l in sp.solve(f.likning, S[mal]) if l.is_real is not False]
    if not svar:
        raise ValueError(f"{f.id} kan ikke løses for {mal}")
    return svar[0]


def omforminger(f: Formel) -> list[tuple[str, str]]:
    """Alle måtene formelen kan snus på: [(variabel, «FK = NPO · DG»), ...]."""
    ut = []
    for mal in f.variabler[1:]:
        if mal in f.ikke_snu:
            continue
        try:
            ut.append((mal, f"{mal} = {skriv(losninger(f, mal))}"))
        except (ValueError, NotImplementedError):
            continue
    return ut


# ---------- pene tall ----------

def _pent(verdi, navn: str) -> bool:
    if not isinstance(verdi, (int, float)) or verdi != verdi:
        return False
    v = VARIABLER[navn]
    if not v.negativ and verdi <= 0 and navn not in ("RV",):
        return False
    if v.prosent:
        return abs(round(verdi * 1000) - verdi * 1000) < 1e-6 and (v.negativ or verdi < 1)
    if abs(verdi) >= 100:
        return abs(verdi - round(verdi)) < 1e-6
    return abs(verdi * 100 - round(verdi * 100)) < 1e-6


def _rimelig(verdier: dict) -> bool:
    """Tall som henger sammen i virkeligheten: variable kostnader under selvkost, men ikke latterlig lave."""
    if "VEK" in verdier and "SK" in verdier and not verdier["SK"] / 4 < verdier["VEK"] < verdier["SK"]:
        return False
    if "VK" in verdier and "SK" in verdier and not verdier["VK"] < verdier["SK"]:
        return False
    if "VK" in verdier and "VEK" in verdier and verdier["VK"] > verdier["VEK"]:
        return False                           # varekostnaden er en del av de variable kostnadene
    grenser = {"DG": (0.1, 0.8), "BF": (0.1, 0.9), "SM": (0.05, 0.8), "TS": (0.05, 1.5), "P": (0.05, 1), "FP": (0.05, 0.6)}
    return all(lav <= verdier[k] <= hoy for k, (lav, hoy) in grenser.items() if k in verdier)


def verdier_for(f: Formel, rng: random.Random, forsok: int = 400) -> dict[str, float] | None:
    """Trekker pene verdier for alle variablene i formelen, slik at likningen går opp."""
    uten_verdier = [v for v in f.variabler[1:] if not VARIABLER[v].verdier]
    trekk = f.trekk or (uten_verdier[0] if uten_verdier else f.lhs)    # regn ut den som ikke har faste verdier
    frie = [v for v in f.variabler if v != trekk]
    los = sp.lambdify([S[v] for v in frie], losninger(f, trekk) if trekk != f.lhs else f.rhs)
    for _ in range(forsok):
        valgt = {v: rng.choice(VARIABLER[v].verdier) for v in frie}
        try:
            verdi = float(los(*valgt.values()))
        except (ZeroDivisionError, OverflowError, ValueError, TypeError):
            continue
        if _pent(verdi, trekk) and _rimelig(valgt):
            return {**valgt, trekk: verdi}
    return None


# ---------- oppgavene ----------

@dataclass
class Oppgave:
    type: str                      # formel, snu, regn, hva_skjer, sammenheng
    tema: str
    tekst: str
    fasit: str | float             # alternativet som er riktig, eller tallet
    alternativer: list[str] = field(default_factory=list)
    mal: str | None = None         # variabelen svaret gjelder (for prosent og enhet)
    forklaring: str = ""
    kilder: list[str] = field(default_factory=list)

    @property
    def tallsvar(self) -> bool:
        return not self.alternativer


TYPER = {"formel": "Hvilken formel?", "snu": "Snu formelen", "regn": "Regn ut", "hva_skjer": "Hva skjer hvis?",
         "sammenheng": "Sammenheng på tvers"}


def _gale_uttrykk(e: sp.Expr, mal: str) -> list[sp.Expr]:
    """Typiske feil: brøken snudd, feil fortegn, ganget i stedet for delt, et begrep byttet med naboen."""
    teller, nevner = sp.fraction(sp.together(e))
    kandidater = []
    if nevner != 1:
        kandidater += [nevner / teller, teller * nevner]
    for del_ in (teller, nevner):
        if isinstance(del_, sp.Add):
            for ledd in del_.args:
                ny = del_ - 2 * ledd                       # ett ledd med motsatt fortegn
                kandidater.append((ny / nevner) if del_ is teller else (teller / ny))
    for sym in e.free_symbols:
        if (nabo := NABOER.get(str(sym))) and nabo != mal:
            kandidater.append(e.subs(sym, S[nabo]))
    if nevner == 1 and isinstance(teller, sp.Mul):
        faktorer = [a for a in teller.args if a.free_symbols]
        if len(faktorer) >= 2:
            kandidater.append(faktorer[0] / sp.Mul(*faktorer[1:]))
    return kandidater


def _tullete(k: sp.Expr) -> bool:
    """Gale svar ingen ville valgt: alt negativt, eller «SK/(−FP − 1)»."""
    teller, nevner = sp.fraction(sp.together(k))
    return teller.could_extract_minus_sign() or nevner.could_extract_minus_sign()


def _alternativer(riktig: sp.Expr, mal: str, rng: random.Random, reserve: list[sp.Expr] = ()) -> list[sp.Expr] | None:
    valgt = [riktig]
    for k in [*rng.sample(_gale_uttrykk(riktig, mal), k=len(_gale_uttrykk(riktig, mal))), *reserve]:
        if S[mal] in k.free_symbols or k.free_symbols == set() or _tullete(k):
            continue
        if all(sp.simplify(k - v) != 0 for v in valgt) and skriv(k) not in {skriv(v) for v in valgt}:
            valgt.append(k)
        if len(valgt) == 4:
            rng.shuffle(valgt)
            return valgt
    return None


def lag_formel(f: Formel, rng: random.Random) -> Oppgave | None:
    reserve = [g.rhs for g in FORMLER if g.lhs != f.lhs and g.rhs.free_symbols & f.rhs.free_symbols]
    alt = _alternativer(f.rhs, f.lhs, rng, reserve)
    if not alt:
        return None
    tekster = [f"{f.lhs} = {skriv(a)}" for a in alt]
    riktig = f"{f.lhs} = {skriv(f.rhs)}"
    forklaring = f"**{f.navn}:** {formel_tekst(f)}\n\n{f.bruk}\n\n{_ordliste(f.variabler)}"
    return Oppgave("formel", f.tema, f"Hva er formelen for {VARIABLER[f.lhs].tekst} ({f.lhs})?", riktig, tekster,
                   forklaring=forklaring, kilder=[f.kilde])


def lag_snu(f: Formel, rng: random.Random) -> Oppgave | None:
    mulige = [m for m, _ in omforminger(f)]
    if not mulige:
        return None
    mal = rng.choice(mulige)
    riktig = losninger(f, mal)
    alt = _alternativer(riktig, mal, rng)
    if not alt:
        return None
    tekster = [f"{mal} = {skriv(a)}" for a in alt]
    forklaring = (f"Start med **{formel_tekst(f)}** og få {mal} alene på venstre side:\n\n"
                  f"**{mal} = {skriv(riktig)}**\n\n{_ordliste(f.variabler)}")
    return Oppgave("snu", f.tema, f"Snu formelen {formel_tekst(f)}. Hva er {mal} ({VARIABLER[mal].tekst})?",
                   f"{mal} = {skriv(riktig)}", tekster, mal=mal, forklaring=forklaring, kilder=[f.kilde])


def _innsatt(uttrykk: sp.Expr, verdier: dict) -> str:
    """«FK/DG» med tallene satt inn: «300 000 / 0,4»."""
    tekst = skriv(uttrykk)
    for navn in sorted(verdier, key=len, reverse=True):
        v = verdier[navn]
        t = tall(v).replace(" ", " ") if not VARIABLER[navn].prosent else f"{v:g}".replace(".", ",")
        tekst = re.sub(rf"(?<![\w]){re.escape(navn)}(?![\w])", f"({t})" if v < 0 else t, tekst)
    return tekst.replace(" ", " ")


def lag_regn(f: Formel, rng: random.Random) -> Oppgave | None:
    if not f.regnes:
        return None
    verdier = verdier_for(f, rng)
    if not verdier:
        return None
    mulige = [f.lhs] + [m for m, _ in omforminger(f)]
    mal = rng.choice(mulige)
    gitt = {k: v for k, v in verdier.items() if k != mal}
    losning = losninger(f, mal)
    linjer = ", ".join(f"{VARIABLER[k].tekst} ({k}) = {med_enhet(v, k)}" for k, v in gitt.items())
    forklaring = (f"Formel: **{formel_tekst(f)}**" + (f", snudd: **{mal} = {skriv(losning)}**" if mal != f.lhs else "") +
                  f"\n\n{mal} = {_innsatt(losning, gitt)} = **{med_enhet(verdier[mal], mal)}**")
    return Oppgave("regn", f.tema, f"Gitt: {linjer}. Finn {VARIABLER[mal].tekst} ({mal}).", verdier[mal], mal=mal,
                   forklaring=forklaring, kilder=[f.kilde])


# ---------- sammenhenger på tvers av formlene ----------

def kjeder(maks_lengde: int = 3) -> list[list[Formel]]:
    """Formler der svaret fra én er et tall i den neste, f.eks. DB → DG → NPO."""
    ut = []

    def videre(kjede):
        if len(kjede) >= 2:
            ut.append(list(kjede))
        if len(kjede) == maks_lengde:
            return
        brukt = {g.lhs for g in kjede} | {str(x) for g in kjede for x in g.rhs.free_symbols}
        for g in FORMLER:
            if S[kjede[-1].lhs] in g.rhs.free_symbols and g.lhs not in brukt and g.regnes and g.id != "balanse":
                videre(kjede + [g])

    for f in FORMLER:
        if f.regnes and f.id != "balanse":
            videre([f])
    return ut


def _kjedeverdier(kjede: list[Formel], rng: random.Random, forsok: int = 400) -> dict | None:
    for _ in range(forsok):
        verdier = {}
        ok = True
        for i, f in enumerate(kjede):
            for v in f.variabler[1:]:
                if v not in verdier:
                    if not VARIABLER[v].verdier:
                        ok = False
                        break
                    verdier[v] = rng.choice(VARIABLER[v].verdier)
            if not ok:
                break
            try:
                verdi = float(f.rhs.subs({S[k]: v for k, v in verdier.items()}))
            except (TypeError, ZeroDivisionError):
                ok = False
                break
            if not _pent(verdi, f.lhs):
                ok = False
                break
            verdier[f.lhs] = verdi
        if ok and _rimelig(verdier):
            return verdier
    return None


def lag_sammenheng(kjede: list[Formel], rng: random.Random) -> Oppgave | None:
    verdier = _kjedeverdier(kjede, rng)
    if not verdier:
        return None
    mellom = {f.lhs for f in kjede}
    gitt = {k: v for k, v in verdier.items() if k not in mellom}
    mal = kjede[-1].lhs
    linjer = ", ".join(f"{VARIABLER[k].tekst} ({k}) = {med_enhet(v, k)}" for k, v in gitt.items())
    steg = []
    kjent = dict(gitt)
    for nr, f in enumerate(kjede, start=1):
        steg.append(f"{nr}. {f.navn}: {f.lhs} = {_innsatt(f.rhs, {k: kjent[k] for k in f.variabler[1:]})} "
                    f"= **{med_enhet(verdier[f.lhs], f.lhs)}**")
        kjent[f.lhs] = verdier[f.lhs]
    rekke = " → ".join(f.lhs for f in kjede)
    forklaring = f"Sammenhengen er {rekke}. Regn ett steg om gangen:\n\n" + "\n".join(steg)
    return Oppgave("sammenheng", kjede[-1].tema, f"Gitt: {linjer}. Finn {VARIABLER[mal].tekst} ({mal}).", verdier[mal],
                   mal=mal, forklaring=forklaring, kilder=[f.kilde for f in kjede])


def lag_hva_skjer(kjede: list[Formel], rng: random.Random) -> Oppgave | None:
    """«Hvis VEK øker, hva skjer med NPO?» Retningen finnes ved å regne, ikke ved å gjette."""
    verdier = _kjedeverdier(kjede, rng)
    if not verdier:
        return None
    mellom = {f.lhs for f in kjede}
    mulige = [k for k in verdier if k not in mellom]
    if not mulige:
        return None
    endres = rng.choice(mulige)
    mal = kjede[-1].lhs
    start = next(i for i, f in enumerate(kjede) if S[endres] in f.rhs.free_symbols)
    kjede = kjede[start:]                     # formlene før er uten betydning for spørsmålet
    mellom = {f.lhs for f in kjede}

    def regn(gitt):
        kjent = dict(gitt)
        for f in kjede:
            kjent[f.lhs] = float(f.rhs.subs({S[k]: kjent[k] for k in f.variabler[1:]}))
        return kjent[mal]

    gitt = {k: v for k, v in verdier.items() if k not in mellom}
    for_ = regn(gitt)
    etter = regn({**gitt, endres: gitt[endres] * 1.1 if gitt[endres] else 0.05})
    retning = "øker" if etter > for_ + 1e-9 else "synker" if etter < for_ - 1e-9 else "uendret"
    rekke = " → ".join([endres] + [f.lhs for f in kjede])
    forklaring = (f"{'  |  '.join(formel_tekst(f) for f in kjede)}\n\nFølg sammenhengen {rekke}: når {endres} øker, "
                  f"{'øker' if retning == 'øker' else 'synker' if retning == 'synker' else 'endres ikke'} {mal}. "
                  f"Eksempel: {mal} går fra {med_enhet(for_, mal)} til {med_enhet(etter, mal)} når {endres} øker med 10 %.")
    return Oppgave("hva_skjer", kjede[-1].tema,
                   f"Hvis {VARIABLER[endres].tekst} ({endres}) øker og alt annet er likt, hva skjer med "
                   f"{VARIABLER[mal].tekst} ({mal})?",
                   retning, ["øker", "synker", "uendret"], forklaring=forklaring, kilder=[f.kilde for f in kjede])


def ny_oppgave(type_: str = "blandet", tema: str | None = None, rng: random.Random | None = None) -> Oppgave:
    rng = rng or random.Random()
    formler = [f for f in FORMLER if not tema or f.tema == tema] or FORMLER
    kjedeliste = [k for k in kjeder() if not tema or any(f.tema == tema for f in k)]
    for _ in range(50):
        t = rng.choice(list(TYPER)) if type_ == "blandet" else type_
        if t in ("sammenheng", "hva_skjer") and not kjedeliste:
            t = "regn"
        if t == "formel":
            oppg = lag_formel(rng.choice(formler), rng)
        elif t == "snu":
            oppg = lag_snu(rng.choice(formler), rng)
        elif t == "regn":
            oppg = lag_regn(rng.choice(formler), rng)
        elif t == "sammenheng":
            oppg = lag_sammenheng(rng.choice(kjedeliste), rng)
        else:
            kjede = rng.choice(kjedeliste + [[f] for f in formler if f.regnes])
            oppg = lag_hva_skjer(kjede, rng)
        if oppg:
            return oppg
    raise RuntimeError("Fant ingen oppgave. Prøv et annet tema eller en annen type.")


def les_tall(tekst: str, mal: str | None = None) -> float | None:
    """«750 000», «kr 750 000», «40 %», «0,4», «−2,5» → tall. Prosent kan skrives som 40 eller 0,4."""
    t = tekst.lower().replace("kr", "").replace(" ", " ").replace("−", "-").replace("–", "-").strip()
    prosent = "%" in t
    t = t.replace("%", "").replace(" ", "")
    if t.count(",") == 1 and t.count(".") >= 1:
        t = t.replace(".", "")                               # 1.500,5
    t = t.replace(",", ".")
    try:
        verdi = float(t)
    except ValueError:
        return None
    if mal and VARIABLER[mal].prosent and (prosent or abs(verdi) > 1):
        verdi /= 100
    return verdi


def sjekk(oppg: Oppgave, svar: str) -> bool:
    if not oppg.tallsvar:
        return svar.strip() == str(oppg.fasit)
    verdi = les_tall(svar, oppg.mal)
    return verdi is not None and abs(verdi - oppg.fasit) <= max(0.01 if not VARIABLER[oppg.mal].prosent else 0.0005,
                                                                 0.005 * abs(oppg.fasit))


def _ordliste(navn: list[str]) -> str:
    return " · ".join(f"{n} = {VARIABLER[n].tekst}" for n in navn)


# ---------- formelarket ----------

def formelark() -> list[tuple[str, list[dict]]]:
    """[(tema, [{navn, formel, bruk, variabler, snudd, kilde, henger_sammen}]), ...] i eksamensrekkefølge."""
    ut = []
    for tema in TEMAREKKEFOLGE:
        rader = []
        for f in (f for f in FORMLER if f.tema == tema):
            naboer = sorted({g.navn for g in FORMLER if g is not f and
                             (S[f.lhs] in g.rhs.free_symbols or S[g.lhs] in f.rhs.free_symbols)})
            rader.append({"navn": f.navn, "formel": formel_tekst(f), "bruk": f.bruk, "variabler": _ordliste(f.variabler),
                          "snudd": [t for _, t in omforminger(f)], "kilde": f"{FAG}/{f.kilde}", "henger_sammen": naboer})
        if rader:
            ut.append((tema, rader))
    return ut


if __name__ == "__main__":
    from src.terminal import les

    parser = argparse.ArgumentParser(description="BØA-formelark og formeltrening.")
    parser.add_argument("--ov", type=int, metavar="ANTALL", help="tren på formlene i terminalen")
    parser.add_argument("--type", choices=["blandet", *TYPER], default="blandet")
    args = parser.parse_args()
    if not args.ov:
        for tema, rader in formelark():
            print(f"\n=== {tema} ===")
            for r in rader:
                print(f"\n{r['navn']}:  {r['formel']}\n  {r['bruk']}\n  {r['variabler']}")
                if r["snudd"]:
                    print("  Snudd: " + " | ".join(r["snudd"]))
                print(f"  Kilde: {r['kilde']}")
    else:
        riktige = 0
        for nr in range(1, args.ov + 1):
            o = ny_oppgave(args.type)
            print(f"\n{nr}. [{TYPER[o.type]} · {o.tema}]\n   {o.tekst}")
            for b, a in zip("ABCD", o.alternativer):
                print(f"   {b}) {a}")
            svar = les("   Svar: ")
            if svar == "q":
                break
            if o.alternativer and len(svar) == 1 and svar.upper() in "ABCD"[:len(o.alternativer)]:
                svar = o.alternativer["ABCD".index(svar.upper())]
            ok = sjekk(o, svar)
            riktige += ok
            fasit = med_enhet(o.fasit, o.mal) if o.tallsvar else o.fasit
            print(f"   {'✓ Riktig' if ok else f'✗ Riktig svar: {fasit}'}\n   {o.forklaring}\n   Kilde: {', '.join(o.kilder)}")
        print(f"\n{riktige} riktige.")
