"""Steg 3: finn bitene som ligger nærmest et spørsmål.

Dette er «R»-en i RAG. Ingen språkmodell er involvert her, bare vektorer og avstand.

Kjør:  uv run python -m src.henting "Hva er kontrollspenn?"
       uv run python -m src.henting --fag MRK1001 "Hva er segmentering?"
"""

import argparse
from dataclasses import dataclass

from src.indeks import embed_sporsmal, hent_samling
from src.innlesing import standardfag
from src.konfig import last_innstillinger


@dataclass
class Bit:
    tekst: str
    metadata: dict
    avstand: float      # cosinusavstand: 0 = samme mening, høyere = mer ulikt

    @property
    def kilde(self) -> str:
        """F.eks. «foiler/Modul-2.pdf, s. 15» eller «notater/kap-13.docx»."""
        side = self.metadata.get("side")
        return f"{self.metadata['fil']}, s. {side}" if side else self.metadata["fil"]


def hent(sporsmal: str, fag: str | None = None, k: int | None = None) -> list[Bit]:
    fag = fag or standardfag()
    k = k or last_innstillinger()["henting"]["antall_biter"]

    svar = hent_samling().query(
        query_embeddings=[embed_sporsmal(sporsmal)],
        n_results=k,
        where={"fag": fag},          # metadatafilter: søk bare i dette faget
    )
    # Chroma svarer med én liste per spørsmål. Vi sendte ett, så vi tar [0].
    return [
        Bit(tekst, meta, avstand)
        for tekst, meta, avstand in zip(svar["documents"][0], svar["metadatas"][0], svar["distances"][0])
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vis bitene som hentes for et spørsmål.")
    parser.add_argument("--fag", help="fag å søke i (standard: standardfag i innstillingene)")
    parser.add_argument("sporsmal", nargs="+")
    args = parser.parse_args()
    sporsmal = " ".join(args.sporsmal)
    print(f"Spørsmål: {sporsmal}   (fag: {args.fag or standardfag()})\n")
    for nr, bit in enumerate(hent(sporsmal, fag=args.fag), start=1):
        print(f"[{nr}] avstand {bit.avstand:.3f}  {bit.kilde}")
        print("    " + bit.tekst[:200].replace("\n", " ") + " ...\n")
