"""OCR av skannede PDF-sider med Apple Vision (innebygd i macOS, gratis og lokalt).

Brukes av innlesingen for PDF-sider som ikke har tekst og som ikke ligger i goodnotes/
(håndskrift er fase 1b). Resultatet lagres i data/ocr/, så hver side bare leses én gang.

Kjør (test én side):  uv run python -m src.ocr "pensum/MRK1001/eksamener/eksempelsvar/X.pdf" 1
"""

import io
import sys
from pathlib import Path

from src.konfig import data_mappe

SPRAK = ["nb-NO", "en-US"]      # norsk først; engelsk for fagbegreper og sitater
DPI = 200                        # høy nok oppløsning for vanlig skrift


def _cache_sti(fil: Path, side: int) -> Path:
    relativ = fil.resolve().relative_to(Path.cwd().resolve()) if fil.is_absolute() else fil
    return data_mappe() / "ocr" / relativ.with_suffix("") / f"s{side:03d}.txt"


def les_side(fil: Path, side: int) -> str:
    """Tekst fra side `side` (første side = 1). Hentes fra data/ocr/ hvis den er lest før."""
    cache = _cache_sti(fil, side)
    if cache.exists():
        return cache.read_text(encoding="utf-8")

    import pymupdf
    from ocrmac import ocrmac
    from PIL import Image

    with pymupdf.open(fil) as pdf:
        png = pdf[side - 1].get_pixmap(dpi=DPI).tobytes("png")
    linjer = ocrmac.OCR(Image.open(io.BytesIO(png)), language_preference=SPRAK,
                        recognition_level="accurate").recognize()
    # Vision gir (tekst, sikkerhet, [x, y, bredde, høyde]) med y målt nedenfra. Les ovenfra og ned.
    linjer.sort(key=lambda r: (-round(r[2][1], 2), r[2][0]))
    tekst = "\n".join(r[0] for r in linjer)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(tekst, encoding="utf-8")
    return tekst


def les_side_spalter(fil: Path, side: int) -> str:
    """Som les_side, men for sider satt i spalter (avisartikler i eksamenscasene): venstre spalte
    ovenfra og ned før høyre, og ord delt med bindestrek ved linjeslutt skjøtes. Lagres for seg."""
    cache = _cache_sti(fil, side).with_name(f"s{side:03d}_spalter.txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8")

    import re
    import pymupdf
    from ocrmac import ocrmac
    from PIL import Image

    with pymupdf.open(fil) as pdf:
        png = pdf[side - 1].get_pixmap(dpi=DPI).tobytes("png")
    linjer = ocrmac.OCR(Image.open(io.BytesIO(png)), language_preference=SPRAK,
                        recognition_level="accurate").recognize()
    # (tekst, sikkerhet, [x, y, bredde, høyde]), y målt nedenfra. Siden deles i bolker ovenfra og ned:
    # linjer over nesten hele bredden står for seg, og hver bolk med smale linjer leses spalte for spalte.
    # Spalteskillet i en bolk er der en loddrett linje krysser færrest tekstlinjer.
    def spalter(bolk):
        krysser = lambda r, b: r[2][0] < b - 0.01 and r[2][0] + r[2][2] > b + 0.01
        beste = None
        for b in (i / 100 for i in range(25, 80)):
            v = sum(r[2][0] + r[2][2] <= b + 0.01 for r in bolk)
            h = sum(r[2][0] >= b - 0.01 for r in bolk)
            if min(v, h) >= max(2, len(bolk) / 6):
                k = sum(krysser(r, b) for r in bolk)
                if beste is None or k < beste[0]:
                    beste = (k, b)
        if beste is None:
            return bolk
        b = beste[1]
        return [r for r in bolk if r[2][0] < b] + [r for r in bolk if r[2][0] >= b]

    rekke, bolk = [], []
    for r in sorted(linjer, key=lambda r: -r[2][1]):
        if r[2][2] > 0.6:                    # hel bredde
            rekke += spalter(bolk) + [r]
            bolk = []
        else:
            bolk.append(r)
    rekke += spalter(bolk)
    tekst = "\n".join(r[0] for r in rekke)
    tekst = re.sub(r"(\w)-\n(\w)", r"\1\2", tekst)       # «bordten-\nnisbord» → «bordtennisbord»

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(tekst, encoding="utf-8")
    return tekst


if __name__ == "__main__":
    fil, side = Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(les_side(fil, side))
