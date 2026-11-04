"""Kvalitetskontroller som deles av alle øvingsmåtene (flervalg, kortsvar, flashcards).

Ingen av disse bruker språkmodellen. De er billige sjekker i ren Python som fanger
de vanligste feilene før et spørsmål vises for deg.
"""

import re

from src.indeks import embed_sporsmal

# Like spørsmål (samme stoff i notat og foil) har likhet ca. 0,96 med e5-vektorer, mens ulike
# spørsmål om samme tema ligger rundt 0,83–0,87 (målt 29.10.2026). Grensen ligger midt i gapet.
DUPLIKAT_GRENSE = 0.92


def normaliser(tekst: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”•·–—-]", " ", tekst.lower())).strip()


def sitat_finnes(sitat: str, kildetekst: str) -> bool:
    """Står sitatet i kilden? Små forskjeller i mellomrom og tegnsetting tillates.

    Dette er en billig kontroll mot oppdiktet fasit: kan ikke modellen vise hvor i
    teksten svaret står, stoler vi ikke på spørsmålet.
    """
    sitat, kilde = normaliser(sitat), normaliser(kildetekst)
    if len(sitat.split()) < 5:
        return False          # ett eller to ord beviser ikke noe
    if sitat in kilde:
        return True
    # Modellen endrer av og til et ord eller to. Godta hvis nesten alle ordene står i kilden.
    ord_ = sitat.split()
    return sum(o in kilde for o in ord_) / len(ord_) >= 0.9


# «i tabellen», «oppgave 3», «ifølge teksten», «ovenfor»: viser til noe studenten ikke ser
_HENVISNING = re.compile(r"\b((i|fra|se|av) (tabellen|figuren|oppgaven|caset|eksempelet|grafen)|"
                         r"(ifølge|basert på|i|fra|av) (teksten|tekstutdraget|kilden|notatet|foilen|lysbildet)|"
                         r"i denne (konteksten|sammenhengen)|i dette tilfellet|i forelesningen|på lysbildet|"
                         r"ifølge (modellen|figuren|forfatteren)|"
                         r"oppgave \d+|ovenfor|nedenfor)\b", re.I)
# «Hva er målet med å studere …», «Hva skal du kunne etter forelesningen?»: spør om kurset, ikke faget
_OM_KURSET = re.compile(r"\b(å studere|studere|læringsmål|forelesning\w*|kurset|emnet|pensum\w*|studenten|"
                       r"kapit+e?let|boken|boka)\b", re.I)
_FIRMA = re.compile(r"\b([A-ZÆØÅ][\wæøå-]*(?: [A-ZÆØÅ][\wæøå-]*)*) (AS|ASA|A/S)\b")


def viser_til_ukjent(sporsmal: str, kildetekst: str) -> str | None:
    """Spør spørsmålet om en bestemt oppgave eller case fra pensum som studenten ikke har foran seg?

    Eksempel: «Hva er den laveste prisen Virksomheten AS kan akseptere for ordren fra kunden i Danmark?»
    Tallene står i oppgaven, ikke i spørsmålet, så det kan ikke besvares uten boka. En oppdiktet
    case i selve spørsmålet (kortsvar, stil «case») er greit: da står firmanavnet ikke i kilden.
    Returnerer grunnen, eller None hvis spørsmålet kan stå alene.
    """
    if treff := _HENVISNING.search(sporsmal):
        return f"viser til «{treff.group()}», som studenten ikke ser"
    if treff := _OM_KURSET.search(sporsmal):
        return f"spør om kurset («{treff.group()}»), ikke om faget"
    for navn, form in _FIRMA.findall(sporsmal):
        if normaliser(navn) in normaliser(kildetekst):
            return f"spør om {navn} {form} fra en oppgave i pensum, uten opplysningene fra oppgaven"
    return None


_SMAAORD = {"hvilken", "hvilket", "hvilke", "innebærer", "betyr", "beskriver", "kalles", "hvordan", "hvorfor",
            "eller", "ikke", "også", "slik", "sammenheng", "forhold", "mellom", "denne", "dette", "disse", "mest"}
# «Hvilken type …», «Hva kalles …»: spørsmålet vil ha et navn på et begrep, ikke en beskrivelse
_SPOR_ETTER_NAVN = re.compile(r"^(hvilken|hvilket) (type|form|begrep|modell|strategi|metode|teori|tilnærming)\b|"
                              r"^hva kalles\b|^hva heter\b", re.I)


def _ord(tekst: str) -> list[str]:
    return [o for o in re.findall(r"[a-zæøå]{4,}", tekst.lower()) if o not in _SMAAORD]


def _stammer(tekst: str) -> set[str]:
    """Ordstammer (6 første bokstaver), så «kostnadsfordeling» og «kostnader», eller «markedsføringsmål»
    og «markedsføringens», regnes som samme ord."""
    return {o[:6] for o in _ord(tekst)}


_EN_AV_FLERE = re.compile(r"\b(en|et|ett) (av (de|faktorene|årsakene)|(sentral|viktig|mulig|potensiell|typisk)\w* )?"
                          r"(argument|fare|faktor|årsak|fordel|ulempe|risiko|eksempel|grunn|utfordring)(en|et|er|ene)?\b"
                          r"|\b(en|et|ett) av (de|faktorene|årsakene)\b", re.I)
# «Markedsstrategien er …», «Kommunikasjonsmål er …»: hvert alternativ forklarer sitt eget begrep
_BEGREP_ER = re.compile(r"^\s*([A-ZÆØÅa-zæøå-]+(?: [a-zæøå-]+)?) (er|betyr|innebærer)\b")


def avslorer_svaret(sporsmal: str, riktig: str, gale: list[str]) -> str | None:
    """Kan svaret gjettes uten å kunne stoffet, eller passer ikke svarene til spørsmålet?

    1. Det riktige svaret gjentar ordene i spørsmålet: «… hos så mange forhandlere som mulig?» →
       «Selg overalt, hos så mange forhandlere som mulig». Gale svar som også gjentar spørsmålet, er
       greit, for da peker ikke ordene ut det riktige.
    2. Spørsmålet spør etter et navn («Hvilken type distribusjon …»), men svarene er beskrivelser.
    Returnerer grunnen, eller None hvis spørsmålet er greit.
    """
    i_sporsmal = _stammer(sporsmal)

    def andel(svar: str) -> float:
        ord_ = _stammer(svar)
        return len(ord_ & i_sporsmal) / len(ord_) if ord_ else 0.0

    riktig_andel = andel(riktig)
    if riktig_andel >= 0.99 or (riktig_andel >= 0.5 and riktig_andel >= max(map(andel, gale), default=0) + 0.25):
        return "det riktige svaret gjentar ordene i spørsmålet"
    if _SPOR_ETTER_NAVN.search(sporsmal.strip()) and len(riktig.split()) > 6:
        return "spørsmålet spør etter et navn, men svarene er beskrivelser"

    # Bare det riktige svaret starter med begrepet fra spørsmålet: «Kjøpsatferd klarlegger …» mot «Det …»
    def forste(svar):
        ord_ = re.findall(r"[a-zæøå]+", svar.lower())
        return ord_[0][:6] if ord_ and len(ord_[0]) >= 4 and ord_[0] not in _SMAAORD else ""
    if forste(riktig) and forste(riktig) in i_sporsmal and not any(forste(g) in i_sporsmal for g in gale):
        return "bare det riktige svaret starter med ordet fra spørsmålet"
    # Alternativene forklarer hvert sitt begrep, og spørsmålet nevner begrepet i det riktige
    begreper = [_BEGREP_ER.match(a) for a in [riktig, *gale]]
    navn = [b.group(1).lower() for b in begreper if b and _stammer(b.group(1))]
    if len(navn) >= 3 and len(set(navn)) >= 3 and begreper[0] and \
            _stammer(begreper[0].group(1)) and _stammer(begreper[0].group(1)) <= i_sporsmal:
        return "alternativene forklarer hvert sitt begrep, og spørsmålet nevner det riktige"
    # «Hva er en potensiell fare …?», «et sentralt argument …»: spør etter én av flere, og de gale svarene er
    # ofte de andre punktene fra samme liste i pensum, altså også riktige
    if _EN_AV_FLERE.search(sporsmal):
        return "spør etter én av flere ting, så flere svar kan være riktige"
    # «evne til å hemme/forhindre dette»: svaret viser til noe som bare sto i kildeteksten
    if re.search(r"\b(dette|denne|disse|ovennevnte|det nevnte)\s*[.!]?\s*$", riktig.strip(), re.I):
        return "svaret viser til noe som ikke står i spørsmålet («dette»)"
    # «Hva er forskjellen …?» med et svar på to–tre ord sier ikke hva forskjellen er
    if re.search(r"forskjell", sporsmal, re.I) and len(riktig.split()) <= 3:
        return "spør etter en forskjell, men svaret er for kort til å forklare den"
    return None


class Duplikatfilter:
    """Husker spørsmålene i en økt og sier fra om et nytt spørsmål likner et tidligere."""

    def __init__(self, tidligere: list[str] | None = None):
        """tidligere: tekster som allerede finnes (f.eks. kortene i databasen), som nye skal sammenlignes med."""
        self.vektorer = [embed_sporsmal(t) for t in tidligere or []]

    def er_duplikat(self, tekst: str) -> bool:
        vektor = embed_sporsmal(tekst)
        # Vektorene er normaliserte, så skalarproduktet er cosinuslikheten.
        if any(sum(x * y for x, y in zip(vektor, v)) > DUPLIKAT_GRENSE for v in self.vektorer):
            return True
        self.vektorer.append(vektor)
        return False
