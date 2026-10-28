"""Leser config/innstillinger.yaml og .env.

Resten av koden henter innstillinger herfra i stedet for å lese filene selv,
slik at alle verdier som kan justeres, står på ett sted.
"""

from pathlib import Path

import yaml
from dotenv import load_dotenv

ROT = Path(__file__).resolve().parent.parent

load_dotenv(ROT / ".env")


def last_innstillinger() -> dict:
    with open(ROT / "config" / "innstillinger.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def pensum_mappe() -> Path:
    return ROT / last_innstillinger()["pensum_mappe"]


def data_mappe() -> Path:
    return ROT / last_innstillinger()["data_mappe"]
