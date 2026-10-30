"""Steg 1: les pensumfiler og gjør dem om til Document-objekter med metadata.

Én Document per PDF-side, og én per docx- eller md-fil. Oppdelingen i mindre
biter skjer først i indeks.py, slik at du kan se råteksten her først.

Kjør:  uv run python -m src.innlesing                 (alle fag)
       uv run python -m src.innlesing --fag MRK1001   (ett fag, med utdrag)
"""

import argparse
import logging
import re
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
        # For eksamener: andre mappenivå sier om det er oppgave, løsning eller eksempelsvar.
        # Chroma godtar ikke None, så andre filer får tom streng.
        "del": relativ.parts[1] if relativ.parts[0] == "eksamener" and len(relativ.parts) > 2 else "",
    }


def finn_tittel(tekst: str) -> str:
    """Første linje med et ord i, f.eks. foiltittelen. Hopper over datoer og sidetall."""
    for linje in tekst.splitlines():
        if re.search(r"[A-Za-zÆØÅæøå]{3,}", linje):
            return linje.strip()[:100]
    return ""


def fjern_stoy(tekst: str) -> str:
    """Fjerner tekst som står på mange sider (som NTNU-slagordet) og ikke sier noe om innholdet."""
    for stoy in last_innstillinger()["innlesing"].get("fjern_tekst") or []:
        tekst = tekst.replace(stoy, "")
    return tekst.strip()


def _les_pdf(fil: Path, meta: dict, min_tegn: int) -> tuple[list[Document], int]:
    sider = PyPDFLoader(str(fil)).load()        # én Document per side
    docs = []
    for side in sider:
        tekst = fjern_stoy(side.page_content)
        if len(tekst) < min_tegn:
            continue                            # tom side, eller bare bilde/håndskrift
        # PyPDFLoader teller fra 0. Vi lagrer sidetallet slik PDF-leseren viser det.
        docs.append(Document(page_content=tekst, metadata={
            **meta, "side": side.metadata["page"] + 1, "tittel": finn_tittel(tekst)}))
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
    meta["tittel"] = finn_tittel(tekst)
    return ([Document(page_content=tekst, metadata=meta)] if len(tekst) >= min_tegn else []), 1


def finn_filer(fag_mappe: Path, typer: list[str]) -> list[Path]:
    filer = []
    for type_ in typer:
        for fil in sorted((fag_mappe / type_).rglob("*")):
            if fil.is_file() and fil.suffix.lower() in FILTYPER and not fil.name.startswith(("~$", ".")):
                filer.append(fil)
    return filer


def alle_fag() -> list[str]:
    return last_innstillinger()["innlesing"]["fag"]


def standardfag() -> str:
    return last_innstillinger()["innlesing"]["standardfag"]


def les_fag(fag: str, typer: list[str] | None = None) -> list[Document]:
    docs, _ = _les_fag_med_statistikk(fag, typer)
    return docs


def _les_fag_med_statistikk(fag, typer=None):
    innst = last_innstillinger()["innlesing"]
    typer = typer or innst["typer"]
    fag_mappe = pensum_mappe() / fag
    docs, statistikk = [], []
    for fil in finn_filer(fag_mappe, typer):
        fil_docs, antall_sider = les_fil(fil, fag_mappe, innst["min_tegn_per_side"])
        docs.extend(fil_docs)
        statistikk.append((nfc(fil.relative_to(fag_mappe).as_posix()), len(fil_docs), antall_sider,
                           sum(len(d.page_content) for d in fil_docs)))
    return docs, statistikk


def skriv_rapport(fag: str, docs, statistikk):
    print(f"\n### {fag}")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vis hva som leses inn fra pensum/.")
    parser.add_argument("--fag", help="bare dette faget (standard: alle i innstillingene)")
    args = parser.parse_args()

    for fag in [args.fag] if args.fag else alle_fag():
        docs, statistikk = _les_fag_med_statistikk(fag)
        skriv_rapport(fag, docs, statistikk)

    if args.fag:
        eksempel = next((d for d in docs if d.metadata.get("goodnotes")), docs[0])
        print("\nEksempel på ett dokument:")
        print(eksempel.metadata)
        print(eksempel.page_content[:500])
