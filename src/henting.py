"""Steg 3: finn bitene som ligger nærmest et spørsmål.

Dette er «R»-en i RAG. Ingen språkmodell er involvert her, bare vektorer og avstand.

Kjør:  uv run python -m src.henting "Hva er kontrollspenn?"
"""

import sys
from dataclasses import dataclass

from src.indeks import embed_sporsmal, hent_samling
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
    innst = last_innstillinger()
    fag = fag or innst["innlesing"]["fag"]
    k = k or innst["henting"]["antall_biter"]

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
    sporsmal = " ".join(sys.argv[1:]) or "Hva er kontrollspenn?"
    print(f"Spørsmål: {sporsmal}\n")
    for nr, bit in enumerate(hent(sporsmal), start=1):
        print(f"[{nr}] avstand {bit.avstand:.3f}  {bit.kilde}")
        print("    " + bit.tekst[:200].replace("\n", " ") + " ...\n")
