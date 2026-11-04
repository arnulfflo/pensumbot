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
                         r"oppgave \d+|ovenfor|nedenfor)\b", re.I)
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
    for navn, form in _FIRMA.findall(sporsmal):
        if normaliser(navn) in normaliser(kildetekst):
            return f"spør om {navn} {form} fra en oppgave i pensum, uten opplysningene fra oppgaven"
    return None


_SMAAORD = {"hvilken", "hvilket", "hvilke", "innebærer", "betyr", "beskriver", "kalles", "hvordan", "hvorfor",
            "eller", "ikke", "også", "slik", "sammenheng", "forhold", "mellom", "denne", "dette", "disse", "mest"}
# «Hvilken type …», «Hva kalles …»: spørsmålet vil ha et navn på et begrep, ikke en beskrivelse
_SPOR_ETTER_NAVN = re.compile(r"^(hvilken|hvilket) (type|form|begrep|modell|strategi|metode|teori|tilnærming)\b|"
                              r"^hva kalles\b|^hva heter\b", re.I)


def _stammer(tekst: str) -> set[str]:
    """Ordstammer (8 første bokstaver), så «markedsføringsmål» og «markedsføringens» regnes som samme ord."""
    return {o[:8] for o in re.findall(r"[a-zæøå]{4,}", tekst.lower()) if o not in _SMAAORD}


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
    if riktig_andel >= 0.99 or (riktig_andel >= 0.5 and riktig_andel > max(map(andel, gale), default=0) + 0.25):
        return "det riktige svaret gjentar ordene i spørsmålet"
    if _SPOR_ETTER_NAVN.search(sporsmal.strip()) and len(riktig.split()) > 6:
        return "spørsmålet spør etter et navn, men svarene er beskrivelser"
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
