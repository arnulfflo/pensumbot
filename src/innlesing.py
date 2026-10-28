"""Steg 1: les pensumfiler og gjør dem om til Document-objekter med metadata.

Én Document per PDF-side, og én per docx- eller md-fil. Oppdelingen i mindre
biter skjer først i indeks.py, slik at du kan se råteksten her først.

Kjør:  uv run python -m src.innlesing
"""

import logging
import unicodedata
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from src.konfig import last_innstillinger, pensum_mappe

# pypdf skriver mange ufarlige advarsler om GoodNotes-filer.
logging.getLogger("pypdf").setLevel(logging.ERROR)

FILTYPER = {".pdf", ".docx", ".md"}


def nfc(tekst: str) -> str:
    """macOS kan lagre «å» som a + ring (NFD). NFC gjør at like navn alltid er like."""
    return unicodedata.normalize("NFC", tekst)


def _metadata(fil: Path, fag_mappe: Path) -> dict:
    relativ = fil.relative_to(fag_mappe)
    return {
        "fag": fag_mappe.name,
        "type": relativ.parts[0],               # første mappenivå: foiler, notater ...
        "fil": nfc(relativ.as_posix()),         # f.eks. foiler/goodnotes/Uke-34.pdf
        "goodnotes": "goodnotes" in relativ.parts[:-1],
    }


def _les_pdf(fil: Path, meta: dict, min_tegn: int) -> tuple[list[Document], int]:
    sider = PyPDFLoader(str(fil)).load()        # én Document per side
    docs = []
    for side in sider:
        tekst = side.page_content.strip()
        if len(tekst) < min_tegn:
            continue                            # tom side, eller bare bilde/håndskrift
        # PyPDFLoader teller fra 0. Vi lagrer sidetallet slik PDF-leseren viser det.
        docs.append(Document(page_content=tekst, metadata={**meta, "side": side.metadata["page"] + 1}))
    return docs, len(sider)


def _docx_tekst(fil: Path) -> str:
    """Går gjennom avsnitt og tabeller i rekkefølge og beholder litt struktur."""
    linjer = []
    for del_ in DocxDocument(str(fil)).iter_inner_content():
        if isinstance(del_, Table):
            for rad in del_.rows:
                celler = [c.text.strip() for c in rad.cells]
                linjer.append(" | ".join(c for c in celler if c))
            continue
        tekst = del_.text.strip()
        if not tekst:
            continue
        stil = (del_.style.name or "") if del_.style is not None else ""
        if stil.startswith("Heading") or stil.startswith("Title"):
            linjer.append("\n" + tekst)         # tom linje før overskrift = naturlig skille for splitteren
        elif del_._p.pPr is not None and del_._p.pPr.numPr is not None:
            linjer.append("- " + tekst)         # punktliste
        else:
            linjer.append(tekst)
    return "\n".join(linjer).strip()


def les_fil(fil: Path, fag_mappe: Path, min_tegn: int) -> tuple[list[Document], int]:
    """Returnerer (dokumenter, antall sider i filen). docx og md regnes som én side."""
    meta = _metadata(fil, fag_mappe)
    if fil.suffix.lower() == ".pdf":
        return _les_pdf(fil, meta, min_tegn)
    if fil.suffix.lower() == ".docx":
        tekst = _docx_tekst(fil)
    else:
        tekst = fil.read_text(encoding="utf-8").strip()
    # docx og md har ikke sidetall, så de får ikke noe "side"-felt.
    return ([Document(page_content=tekst, metadata=meta)] if len(tekst) >= min_tegn else []), 1


def finn_filer(fag_mappe: Path, typer: list[str]) -> list[Path]:
    filer = []
    for type_ in typer:
        for fil in sorted((fag_mappe / type_).rglob("*")):
            if fil.is_file() and fil.suffix.lower() in FILTYPER and not fil.name.startswith(("~$", ".")):
                filer.append(fil)
    return filer


def les_fag(fag: str | None = None, typer: list[str] | None = None) -> list[Document]:
    docs, _ = _les_fag_med_statistikk(fag, typer)
    return docs


def _les_fag_med_statistikk(fag=None, typer=None):
    innst = last_innstillinger()["innlesing"]
    fag = fag or innst["fag"]
    typer = typer or innst["typer"]
    fag_mappe = pensum_mappe() / fag
    docs, statistikk = [], []
    for fil in finn_filer(fag_mappe, typer):
        fil_docs, antall_sider = les_fil(fil, fag_mappe, innst["min_tegn_per_side"])
        docs.extend(fil_docs)
        statistikk.append((nfc(fil.relative_to(fag_mappe).as_posix()), len(fil_docs), antall_sider,
                           sum(len(d.page_content) for d in fil_docs)))
    return docs, statistikk


if __name__ == "__main__":
    docs, statistikk = _les_fag_med_statistikk()

    print(f"{'Fil':<62} {'Sider m/tekst':>14} {'Tegn':>8}")
    print("-" * 86)
    for fil, med_tekst, totalt, tegn in statistikk:
        print(f"{fil[:62]:<62} {f'{med_tekst}/{totalt}':>14} {tegn:>8}")
    print("-" * 86)
    print(f"{len(statistikk)} filer, {len(docs)} dokumenter, {sum(s[3] for s in statistikk)} tegn\n")

    for fil, med_tekst, totalt, _ in statistikk:
        if med_tekst == 0:
            print(f"ADVARSEL: ingen tekst i {fil} (bare håndskrift eller bilder?)")
        elif med_tekst < totalt:
            print(f"Merk: {totalt - med_tekst} av {totalt} sider uten tekst i {fil}")

    eksempel = next(d for d in docs if d.metadata.get("goodnotes"))
    print("\nEksempel (en GoodNotes-side):")
    print(eksempel.metadata)
    print(eksempel.page_content[:500])
