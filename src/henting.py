"""Steg 3: finn bitene som passer best til et spørsmål.

Dette er «R»-en i RAG, og den skjer i to trinn:
  1. Vektorsøk i Chroma: rask og grov, henter mange kandidater (f.eks. 30).
  2. Reranker: en cross-encoder leser spørsmålet og hver kandidat sammen og
     gir en relevansscore. De k beste går videre til språkmodellen.

Vektorsøket sammenligner to ferdige vektorer som er laget hver for seg. Rerankeren
ser begge tekstene samtidig, så den er mer presis, men for treg til å lese alle
bitene i databasen. Derfor kombineres de.

Kjør:  uv run python -m src.henting "Hva er kontrollspenn?"
       uv run python -m src.henting --fag MRK1001 "Hva er segmentering?"
"""

import argparse
from dataclasses import dataclass
from functools import cache

from sentence_transformers import CrossEncoder

from src.indeks import embed_sporsmal, hent_samling, kontekst
from src.innlesing import standardfag
from src.konfig import last_innstillinger


@dataclass
class Bit:
    tekst: str
    metadata: dict
    avstand: float              # cosinusavstand: 0 = samme mening, høyere = mer ulikt
    score: float | None = None  # rerankerens relevans: 0–1, høyere = mer relevant

    @property
    def kilde(self) -> str:
        """F.eks. «foiler/Modul-2.pdf, s. 15» eller «notater/kap-13.docx»."""
        side = self.metadata.get("side")
        return f"{self.metadata['fil']}, s. {side}" if side else self.metadata["fil"]


@cache
def reranker_modell(navn: str) -> CrossEncoder:
    """Lastes bare én gang. Første gang lastes modellen ned.

    Halv presisjon (float16) halverer minnet og gjør den raskere. Det betyr mye på en
    Mac med 16 GB, der språkmodellen også skal ligge i minnet samtidig.
    """
    import torch

    halv = last_innstillinger()["henting"].get("halv_presisjon")
    return CrossEncoder(navn, model_kwargs={"torch_dtype": torch.float16 if halv else torch.float32})


def vektorsok(sporsmal: str, fag: str, n: int, typer: list[str] | None = None) -> list[Bit]:
    # Metadatafilter: bare dette faget, eventuelt bare noen typer (foiler, notater ...), og aldri
    # eksamensdeler som er utelatt i innstillingene (eksempelsvar er ikke fasit).
    vilkar = [{"fag": fag}]
    if typer:
        vilkar.append({"type": {"$in": typer}})
    if utelat := last_innstillinger()["henting"].get("utelat_deler"):
        vilkar.append({"del": {"$nin": utelat}})
    hvor = vilkar[0] if len(vilkar) == 1 else {"$and": vilkar}
    svar = hent_samling().query(
        query_embeddings=[embed_sporsmal(sporsmal)],
        n_results=n,
        where=hvor,
    )
    # Chroma svarer med én liste per spørsmål. Vi sendte ett, så vi tar [0].
    return [
        Bit(tekst, meta, avstand)
        for tekst, meta, avstand in zip(svar["documents"][0], svar["metadatas"][0], svar["distances"][0])
    ]


def rerank(sporsmal: str, biter: list[Bit], navn: str) -> list[Bit]:
    # Samme kontekstlinje som ved embedding, så rerankeren også vet hvilken foil det er.
    tekster = [kontekst(b) + "\n" + b.tekst if "side" in b.metadata else b.tekst for b in biter]
    scorer = reranker_modell(navn).predict([(sporsmal, t) for t in tekster], activation_fn=_sigmoid)
    for bit, score in zip(biter, scorer):
        bit.score = float(score)
    return sorted(biter, key=lambda b: b.score, reverse=True)


def hent(sporsmal: str, fag: str | None = None, k: int | None = None,
         bruk_reranker: bool = True, typer: list[str] | None = None) -> list[Bit]:
    """typer: bare disse typene (f.eks. uten eksamener). None = alle."""
    innst = last_innstillinger()["henting"]
    fag = fag or standardfag()
    k = k or innst["antall_biter"]

    if not (bruk_reranker and innst.get("reranker")):
        return vektorsok(sporsmal, fag, k, typer)
    kandidater = vektorsok(sporsmal, fag, max(k, innst["kandidater"]), typer)
    return rerank(sporsmal, kandidater, innst["reranker"])[:k]


def _sigmoid(x):
    import torch
    return torch.sigmoid(x)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vis bitene som hentes for et spørsmål.")
    parser.add_argument("--fag", help="fag å søke i (standard: standardfag i innstillingene)")
    parser.add_argument("--uten-reranker", action="store_true", help="bare vektorsøk")
    parser.add_argument("sporsmal", nargs="+")
    args = parser.parse_args()
    sporsmal = " ".join(args.sporsmal)
    print(f"Spørsmål: {sporsmal}   (fag: {args.fag or standardfag()})\n")
    for nr, bit in enumerate(hent(sporsmal, fag=args.fag, bruk_reranker=not args.uten_reranker), start=1):
        score = f"score {bit.score:.3f}  " if bit.score is not None else ""
        print(f"[{nr}] {score}avstand {bit.avstand:.3f}  {bit.kilde}")
        print("    " + bit.tekst[:200].replace("\n", " ") + " ...\n")
