"""Kjøres før alle moduler i src/.

Hugging Face-bibliotekene spør nettet om nye modellversjoner hver gang en modell lastes.
Henger nettet, henger hele programmet (funnet 30.10.2026: quizen ventet på SSL_read).
Modellene ligger lokalt etter første nedlasting, så vi kjører offline som standard.

Skal du laste ned en ny modell (f.eks. etter å ha byttet modell i innstillinger.yaml):
    HF_HUB_OFFLINE=0 uv run python -m src.indeks
"""

import logging
import os
import sys

# Må settes før sentence_transformers/huggingface_hub importeres, de leser verdien ved import.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Ellers skrives «Could not reach the Hub ... Using cached» for hver modell. Det er forventet offline.
# huggingface_hub setter sitt eget loggnivå ved import, så det må styres med miljøvariabelen.
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")   # «Loading weights»-linjene fra transformers
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
for navn in ("sentence_transformers", "transformers", "huggingface_hub",
             "torch.distributed.elastic.multiprocessing.redirects"):   # «Redirects are not supported in MacOs»
    logging.getLogger(navn).setLevel(logging.ERROR)


def _pen_feil(type_, feil, spor):
    """I terminalen: «Start Ollama-appen» som én linje, ikke som en lang feilsporing."""
    if type_.__name__ == "SprakmodellFeil":
        print(feil, file=sys.stderr)       # Python avslutter selv med feilkode 1 etterpå
        return
    sys.__excepthook__(type_, feil, spor)


sys.excepthook = _pen_feil
