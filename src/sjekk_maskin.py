"""Steg 4: sjekk minnet på Macen og foreslå en Ollama-modell som passer.

Tommelfingerregel: modellen bør ikke bruke mer enn ca. halvparten av minnet,
fordi macOS, nettleseren og embedding-modellen (ca. 1 GB) også trenger plass.

Kjør:  uv run python -m src.sjekk_maskin
"""

import subprocess

import ollama

from src.konfig import last_innstillinger

GB = 1024**3

# (minste totale minne i GB, modell, omtrentlig størrelse i GB, kommentar)
# Gemma 4 er laget for mange språk og fungerer godt på norsk i forhold til størrelsen.
FORSLAG = [
    (48, "gemma4:26b", 17, "stor og god, krever mye minne"),
    (24, "gemma4:12b", 8, "god kvalitet med god margin"),
    (16, "gemma4:e4b", 6.6, "trygt valg for 16 GB"),
    (16, "gemma4:12b", 8, "bedre svar, men trangt på 16 GB – lukk tunge programmer"),
    (8, "gemma4:e2b", 4.6, "liten, svakere på norsk"),
]


def totalt_minne_gb() -> float:
    return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / GB


def ledig_minne_gb() -> float:
    """Ledige + inaktive sider fra vm_stat. Inaktive sider kan macOS gi bort med en gang."""
    linjer = subprocess.check_output(["vm_stat"], text=True).splitlines()
    sidestorrelse = int(linjer[0].split("page size of ")[1].split()[0])
    verdier = {l.split(":")[0]: int(l.split(":")[1].strip().rstrip(".")) for l in linjer[1:] if ":" in l}
    sider = verdier.get("Pages free", 0) + verdier.get("Pages inactive", 0) + verdier.get("Pages speculative", 0)
    return sider * sidestorrelse / GB


def installerte_modeller() -> list[str] | None:
    try:
        return [m.model for m in ollama.list().models]
    except Exception:
        return None          # Ollama kjører ikke


if __name__ == "__main__":
    totalt, ledig = totalt_minne_gb(), ledig_minne_gb()
    print(f"Minne totalt: {totalt:.0f} GB   ledig nå: ca. {ledig:.1f} GB\n")

    passer = [f for f in FORSLAG if totalt >= f[0]]
    print("Modeller som passer denne maskinen:")
    for nr, (_, modell, storrelse, kommentar) in enumerate(passer[:2], start=1):
        merke = "  ← anbefalt" if nr == 1 else ""
        print(f"  {modell:<12} ca. {storrelse:>4} GB  {kommentar}{merke}")
    print(f"\nLast ned med:  ollama pull {passer[0][1]}")

    installert = installerte_modeller()
    valgt = last_innstillinger()["sprakmodell"]["ollama"]["modell"]
    print(f"\nI innstillinger.yaml står: {valgt}")
    if installert is None:
        print("Ollama svarer ikke. Start Ollama-appen (eller kjør `ollama serve`) og prøv igjen.")
    elif not installert:
        print("Ingen modeller er lastet ned ennå.")
    else:
        print("Lastet ned: " + ", ".join(installert))
        if not any(m == valgt or m == f"{valgt}:latest" for m in installert):
            print(f"Merk: {valgt} er ikke lastet ned. Kjør `ollama pull {valgt}`.")
