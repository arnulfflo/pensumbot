"""Modeller og teorier i MRK og ORG, hentet fra dine egne modellnotater.

Notatene har én seksjon per modell:
  MRK1001/notater/Modeller og Teori markedsføring kap N.docx   fet linje per modell
  ORG1100/notater/ORG1100_kap-N.docx                          overskrift (nivå 3/4) per teori, med sidetall

Elementene i en modell er punktlisten under overskriften («Fysiologiske behov», «Sikkerhetsbehov» …).
Det er de du skal kunne bruke på en case, og det er dem spørsmålene og rettingen bygger på.
Hvilke seksjoner som er modeller (og ikke bare bakgrunn eller eksempler), står i config/modeller.yaml.

Kjør:  uv run python -m src.modeller MRK1001          (modellarket for faget)
       uv run python -m src.modeller ORG1100 --alle   (alle seksjoner, også de som ikke er med)
"""

import argparse
import re
from dataclasses import dataclass, field
from functools import cache

import yaml
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.innlesing import nfc
from src.konfig import ROT, pensum_mappe

FILER = {
    "MRK1001": ("notater/Modeller og Teori markedsføring kap {}.docx", range(1, 16)),
    "ORG1100": ("notater/ORG1100_kap-{}.docx", range(1, 19)),
}


@dataclass
class Element:
    navn: str              # «Fysiologiske behov»
    forklaring: str        # resten av punktet, kan være tom


@dataclass
class Modell:
    id: str                # «ORG1100-3-maslows-behovshierarki»
    fag: str
    kapittel: int
    navn: str              # «Maslows behovshierarki»
    overskrift: str        # slik den står i notatet
    fil: str               # relativ til faget
    side: str = ""         # «s. 97» (ORG) eller «Figur 6.4» (MRK) når notatet oppgir det
    tekst: str = ""        # hele seksjonen, brukes når casen lages og svaret rettes
    elementer: list[Element] = field(default_factory=list)
    med: bool = True       # står på modellarket (config/modeller.yaml kan ta den ut)

    @property
    def kilde(self) -> str:
        return f"{self.fag}/{self.fil}" + (f", {self.side}" if self.side else "")


# «Behov – det som er …», «Retning (valg): hva …», «Produktvariant = én …»
_SKILLE = re.compile(r"\s+[–—-]\s+|:\s|\s=\s|\s→\s")


def element(tekst: str, fra_oppsett: bool = False) -> Element:
    """«Behov – det som er nødvendig …» → Element("Behov", "det som er nødvendig …").

    fra_oppsett: elementer skrevet i config/modeller.yaml deles bare på første « – », så navn som
    «Rute 1: No frills» og «Psykodynamisk teori (Freud)» blir stående hele."""
    tekst = tekst.strip().rstrip(".")
    if fra_oppsett:
        navn, _, rest = tekst.partition(" – ")
        return Element(navn.strip(), rest.strip())
    if m := _SKILLE.search(tekst):
        hode, rest = tekst[:m.start()].strip(), tekst[m.end():].strip()
    else:
        hode, rest = tekst, ""
    # «Fysiologiske behov (mat, søvn, ren luft)»: parentesen er forklaring, ikke navn
    if (p := re.match(r"^(.+?)\s*\((.+)\)$", hode)) and len(p.group(1).split()) <= 6:
        hode, rest = p.group(1), (p.group(2) + (" – " + rest if rest else ""))
    if len(hode.split()) > 4 and (v := re.match(r"^(.{3,40}?) (er|bygger på|går ut på|betyr|innebærer) (.+)$", hode)) \
            and len(v.group(1).split()) <= 4:
        hode, rest = v.group(1), v.group(3) + (" – " + rest if rest else "")
    hode = re.sub(r"^(\d+\.|Rute \d+ –|Kvadrant \d+)\s*", "", hode).strip(" «»\"")
    return Element(hode[:1].upper() + hode[1:], rest)


def _rens_navn(overskrift: str) -> tuple[str, str]:
    """«Figur 1.13 – Marketing mix («konkurransemidlene»)» → («Marketing mix», «Figur 1.13»)."""
    navn, side = overskrift.strip(), []
    if m := re.search(r"\((s\. [\d–-]+)\)", navn):
        side.append(m.group(1))
    if m := re.search(r"(Figur|Tabell) \d+\.\d+", navn):
        side.append(m.group())
    navn = re.sub(r"^(Figur|Tabell) \d+\.\d+\s*[–—-]\s*", "", navn)
    navn = re.sub(r"\s*[–—-]\s*(Figur|Tabell) \d+\.\d+.*$", "", navn)
    navn = re.sub(r"\s*\((s\.|Figur|Tabell|\d+\.\d)[^)]*\)", "", navn)
    navn = re.sub(r"^\d+(\.\d+)+\s*", "", navn).rstrip(":").strip()
    return navn, ", ".join(side)


def _er_liste(p) -> bool:
    ppr = p._p.pPr
    return (ppr is not None and ppr.numPr is not None) or p.style.name.startswith("List")


def _er_overskrift(p, fag: str) -> bool:
    if fag == "ORG1100":
        return p.style.name in ("Heading 2", "Heading 3", "Heading 4")
    deler = [r for r in p.runs if r.text.strip()]
    return bool(deler) and all(r.bold for r in deler) and not _er_liste(p) and len(p.text) < 120


def _slug(tekst: str) -> str:
    return re.sub(r"[^a-z0-9æøå]+", "-", tekst.lower()).strip("-")[:50]


@cache
def _oppsett() -> dict:
    sti = ROT / "config" / "modeller.yaml"
    return yaml.safe_load(sti.read_text(encoding="utf-8")) if sti.exists() else {}


def seksjoner(fag: str) -> list[Modell]:
    """Alle seksjonene i modellnotatene, i kapittelrekkefølge. Også de som ikke er modeller."""
    mal, kapitler = FILER[fag]
    oppsett = _oppsett().get(fag) or {}
    ekstra = oppsett.get("ankere") or {}      # avsnitt som starter en modell uten å være overskrift
    ut = []
    for kap in kapitler:
        fil = mal.format(kap)
        sti = pensum_mappe() / fag / fil
        if not sti.exists():
            continue
        naa = None
        dok = DocxDocument(sti)
        for blokk in dok.element.body.iterchildren():
            if blokk.tag.endswith("}tbl"):
                if naa is not None:
                    _legg_til_tabell(naa, Table(blokk, dok))
                continue
            if not blokk.tag.endswith("}p"):
                continue
            p = Paragraph(blokk, dok)
            tekst = nfc(p.text.strip())
            if not tekst:
                continue
            if p.style.name in ("Title", "Heading 1"):
                naa = None                     # «2. Sentrale begreper»: slutten på modelldelen
                continue
            anker = next((a for a in ekstra if tekst.startswith(a)), None)
            if _er_overskrift(p, fag) or anker:
                overskrift = anker or tekst
                navn, side = _rens_navn(overskrift)
                naa = Modell(id=f"{fag}-{kap}-{_slug(navn)}", fag=fag, kapittel=kap, navn=navn,
                             overskrift=overskrift, fil=nfc(fil), side=side, tekst=tekst)
                ut.append(naa)
                continue
            if naa is None:
                continue
            # «Figur 13.1 (Andreassen, 2008), s. 459–460»: linjen under overskriften sier hvor i boka den står
            if naa.tekst == naa.overskrift and not naa.side and len(tekst) < 130 and \
                    re.match(r"^(Figur|Tabell|s\. \d|\d+\.\d|Innledning|Sammendrag|[A-ZÆØÅ][\wæøå-]+-modellen, figur)", tekst):
                naa.side = tekst
                continue
            naa.tekst += "\n" + tekst
            # Bare punkter på øverste nivå er elementer. Underpunkter er detaljer om elementet.
            ppr = p._p.pPr
            niva = ppr.numPr.ilvl.val if ppr is not None and ppr.numPr is not None and ppr.numPr.ilvl is not None else 0
            if _er_liste(p) and niva == 0 and not tekst.endswith(":"):
                naa.elementer.append(element(tekst))
    return ut


def _legg_til_tabell(naa: Modell, tabell: Table):
    """Tabellen blir tekst i seksjonen. Har seksjonen ingen punktliste, er første kolonne elementene
    («Legitim makt | Stilling, posisjon eller rolle»). En 2×2-matrise (tom første celle) gir ingen elementer."""
    rader = [[nfc(c.text.strip()) for c in r.cells] for r in tabell.rows]
    naa.tekst += "\n" + "\n".join(" | ".join(r) for r in rader)
    if naa.elementer or not rader or not rader[0][0]:
        return
    for rad in rader[1:]:
        if rad[0]:
            navn = re.sub(r"^[A-Z] — ", "", rad[0])        # «N — Nevrotisisme» → «Nevrotisisme»
            navn = re.sub(r"\s*\([^)]*\)?$", "", navn)
            naa.elementer.append(Element(navn, "; ".join(c for c in rad[1:] if c)))


@cache
def modeller(fag: str) -> tuple[Modell, ...]:
    """Modellene på modellarket: seksjonene config/modeller.yaml tar med, med navn og elementer derfra."""
    regler = (_oppsett().get(fag) or {}).get("modeller") or {}
    alle = seksjoner(fag)
    valgt = []
    for nokkel, regel in regler.items():
        treff = [i for i, s in enumerate(alle) if s.overskrift.startswith(nokkel)]
        if not treff:
            continue                       # fanges av testen test_alle_modellene_finnes
        # «Ulike konkurranseformer (Tabell 2.2)» står to ganger i notatet: ta den med innhold
        i = max(treff, key=lambda j: (len(alle[j].elementer), len(alle[j].tekst)))
        m, regel = alle[i], regel or {}
        for neste in alle[i + 1:i + 1 + regel.get("med_neste", 0)]:
            m.tekst += "\n" + neste.tekst
        if regel.get("navn"):
            m.navn = regel["navn"]
        if regel.get("elementer"):
            m.elementer = [element(e, fra_oppsett=True) for e in regel["elementer"]]
        m.id = f"{fag}-{m.kapittel}-{_slug(m.navn)}"
        valgt.append((i, m))
    return tuple(m for _, m in sorted(valgt, key=lambda x: x[0]))


def manglende_nokler(fag: str) -> list[str]:
    """Nøkler i config/modeller.yaml som ikke finnes i notatene (f.eks. hvis du har endret en overskrift)."""
    regler = (_oppsett().get(fag) or {}).get("modeller") or {}
    overskrifter = [s.overskrift for s in seksjoner(fag)]
    return [k for k in regler if not any(o.startswith(k) for o in overskrifter)]


def modell(modell_id: str) -> Modell:
    fag = modell_id.split("-")[0]
    return next(m for m in modeller(fag) if m.id == modell_id)


def for_kapittel(fag: str, kapittel: int | None) -> list[Modell]:
    return [m for m in modeller(fag) if kapittel is None or m.kapittel == kapittel]


def kapittel_i(tema: str) -> int | None:
    """«Motivasjon og arbeidsprestasjon (kap. 3)» → 3."""
    m = re.search(r"kap\.?\s*(\d+)", tema or "")
    return int(m.group(1)) if m else None


def modellark(fag: str, kapittel: int | None = None) -> str:
    """Markdown med modellene (alle, eller ett kapittel), med elementer og kilde."""
    linjer, kap = [], None
    for m in for_kapittel(fag, kapittel):
        if m.kapittel != kap:
            kap = m.kapittel
            linjer.append(f"\n### Kapittel {kap}\n")
        linjer.append(f"**{m.navn}**" + (f" · {m.side}" if m.side else ""))
        for e in m.elementer:
            linjer.append(f"- {e.navn}" + (f": {e.forklaring}" if e.forklaring else ""))
        linjer.append("")
    return "\n".join(linjer)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Vis modellene fra modellnotatene")
    ap.add_argument("fag", choices=list(FILER))
    ap.add_argument("--alle", action="store_true", help="alle seksjoner, også de som ikke er modeller")
    a = ap.parse_args()
    if a.alle:
        for s in seksjoner(a.fag):
            print(f"{s.kapittel:>2} | {s.overskrift[:70]:<70} | {len(s.elementer)} | "
                  + "; ".join(e.navn[:28] for e in s.elementer[:8]))
    else:
        print(modellark(a.fag))
        if mangler := manglende_nokler(a.fag):
            print("\nFinnes ikke i notatene:", *mangler, sep="\n  ")
