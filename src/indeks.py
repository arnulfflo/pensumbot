"""Steg 2: del dokumentene i biter, lag embeddings og lagre dem i Chroma.

Flyt:  Document (side/fil)  →  biter (ca. 1000 tegn)  →  vektor per bit  →  Chroma

Kjør:  uv run python -m src.indeks      (bygger samlingen helt på nytt)
"""

import re
import statistics
from collections import Counter
from functools import cache
from pathlib import Path

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

from src.innlesing import alle_fag, les_fag
from src.konfig import data_mappe, last_innstillinger

SAMLING = "pensum"


@cache
def embedding_modell() -> SentenceTransformer:
    """Lastes bare én gang. Første gang lastes modellen ned (ca. 1 GB)."""
    return SentenceTransformer(last_innstillinger()["embeddings"]["modell"])


# e5-modellene er trent med prefikser: «passage: » foran tekst som skal finnes,
# og «query: » foran spørsmålet. Uten dem blir treffene merkbart dårligere.
def embed_biter(tekster: list[str]) -> list[list[float]]:
    vektorer = embedding_modell().encode(
        ["passage: " + t for t in tekster], normalize_embeddings=True, show_progress_bar=True
    )
    return vektorer.tolist()


def embed_sporsmal(sporsmal: str) -> list[float]:
    return embedding_modell().encode("query: " + sporsmal, normalize_embeddings=True).tolist()


def chroma_klient() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(data_mappe() / "chroma"))


def hent_samling() -> chromadb.Collection:
    # embedding_function=None: vi lager vektorene selv, så Chroma skal ikke bruke sin egen modell.
    return chroma_klient().get_collection(SAMLING, embedding_function=None)


def del_i_biter(docs):
    innst = last_innstillinger()["chunking"]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=innst["storrelse"],
        chunk_overlap=innst["overlapp"],
        # Prøver å dele ved avsnitt først, så linjer, så setninger, så ord.
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    biter = splitter.split_documents(docs)   # metadata kopieres fra dokumentet til hver bit

    # Nummerer bitene per fil og side, så hver bit får en stabil, lesbar ID.
    teller = Counter()
    for bit in biter:
        nokkel = (bit.metadata["fag"], bit.metadata["fil"], bit.metadata.get("side", 0))
        bit.metadata["bit_nr"] = teller[nokkel]
        teller[nokkel] += 1
    return biter


def kontekst(bit) -> str:
    """F.eks. «MRK1001 · Forelesning 7 og 8 · 1.Push-strategi».

    En foilside med noen stikkord sier lite alene. Med denne linjen foran får vektoren
    med seg hvilken forelesning og hvilket tema den hører til. Språkmodellen ser den ikke.

    Brukes bare på PDF-sider. Målt 29.10.2026: på alle biter ble MRR litt dårligere
    (notattitlene er lange og like), bare på PDF-sider ble den bedre (MRK 0,813 → 0,872).
    """
    m = bit.metadata
    fil = re.sub(r"[-_]+", " ", Path(m["fil"]).stem)
    deler = [m["fag"], fil]
    if m.get("tittel") and m["tittel"].lower() != fil.lower():
        deler.append(m["tittel"])
    return " · ".join(deler)


def bit_id(bit) -> str:
    m = bit.metadata
    return f"{m['fag']}/{m['fil']}#{m.get('side', 0)}#{m['bit_nr']}"


def bygg_indeks():
    docs = [doc for fag in alle_fag() for doc in les_fag(fag)]
    biter = del_i_biter(docs)

    print(f"Lager embeddings for {len(biter)} biter ...")
    if last_innstillinger()["chunking"].get("kontekst"):
        vektorer = embed_biter([kontekst(b) + "\n" + b.page_content if "side" in b.metadata else b.page_content
                                for b in biter])
    else:
        vektorer = embed_biter([b.page_content for b in biter])

    klient = chroma_klient()
    if SAMLING in [s.name for s in klient.list_collections()]:
        klient.delete_collection(SAMLING)    # bygg helt på nytt, så ingenting dobles
    samling = klient.create_collection(
        SAMLING,
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},   # avstand = 1 − cosinuslikhet
    )
    samling.add(
        ids=[bit_id(b) for b in biter],
        documents=[b.page_content for b in biter],
        embeddings=vektorer,
        metadatas=[b.metadata for b in biter],
    )
    return biter, samling


def _skriv_statistikk(biter, samling):
    # Per-fil-oversikten finnes i `uv run python -m src.innlesing`. Her holder det med per fag.
    print(f"\n{'Fag':<10} {'Filer':>6} {'Biter':>6}")
    print("-" * 24)
    for fag in alle_fag():
        fagbiter = [b for b in biter if b.metadata["fag"] == fag]
        filer = {b.metadata["fil"] for b in fagbiter}
        print(f"{fag:<10} {len(filer):>6} {len(fagbiter):>6}")

    lengder = [len(b.page_content) for b in biter]
    print(f"\nBitlengde i tegn: min {min(lengder)}, median {statistics.median(lengder):.0f}, maks {max(lengder)}")

    # Sjekk at ingen bit er lengre enn modellen klarer å lese. Det som er over grensen, kuttes stille.
    modell = embedding_modell()
    tokens = [len(modell.tokenizer("passage: " + b.page_content)["input_ids"]) for b in biter]
    grense = modell.max_seq_length
    for_lange = sum(t > grense for t in tokens)
    print(f"Tokens per bit: median {statistics.median(tokens):.0f}, maks {max(tokens)} (grense {grense}), "
          f"{for_lange} biter over grensen")

    print(f"\nChroma-samlingen «{SAMLING}» har {samling.count()} biter, lagret i {data_mappe() / 'chroma'}")
    eksempel = samling.get(limit=1, include=["documents", "metadatas", "embeddings"])
    print("Eksempel på én rad:")
    print("  id:       ", eksempel["ids"][0])
    print("  metadata: ", eksempel["metadatas"][0])
    print("  vektor:   ", f"{len(eksempel['embeddings'][0])} tall, starter med",
          [round(float(x), 3) for x in eksempel["embeddings"][0][:4]])
    print("  tekst:    ", eksempel["documents"][0][:150].replace("\n", " "), "...")


if __name__ == "__main__":
    _skriv_statistikk(*bygg_indeks())
