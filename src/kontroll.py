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
