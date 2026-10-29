"""All kontakt med språkmodellen går gjennom generer().

Resten av koden vet ikke om svaret kommer fra Ollama eller Claude. For å bytte
endrer du bare `sprakmodell.leverandor` i config/innstillinger.yaml.

Kjør:  uv run python -m src.llm "Si hei på norsk"
"""

import json
import re
import sys

from src.konfig import last_innstillinger


def generer(system: str, melding: str, skjema: dict | None = None) -> str:
    """system = instruksen (hvordan modellen skal oppføre seg), melding = det brukeren sender.

    skjema: et JSON-skjema svaret må følge. Brukes av generer_json().
    """
    innst = last_innstillinger()["sprakmodell"]
    leverandor = innst["leverandor"]

    if leverandor == "ollama":
        return _ollama(system, melding, innst, skjema)
    if leverandor == "anthropic":
        if skjema:
            system += ("\n\nSvar BARE med gyldig JSON som følger dette skjemaet, uten annen tekst:\n"
                       + json.dumps(skjema, ensure_ascii=False))
        return _anthropic(system, melding, innst)
    raise ValueError(f"Ukjent leverandør i innstillinger.yaml: {leverandor!r} (bruk ollama eller anthropic)")


def generer_json(system: str, melding: str, skjema: dict) -> dict:
    """Som generer(), men svaret er strukturert data (dict) i stedet for fri tekst.

    Ollama tvinges til å følge skjemaet (structured outputs). Claude får skjemaet i
    instruksen. Eventuelle ```json-gjerder rundt svaret fjernes før tolkning.
    """
    tekst = generer(system, melding, skjema).strip()
    tekst = re.sub(r"^```(?:json)?\s*|\s*```$", "", tekst)
    return json.loads(tekst)


def _ollama(system: str, melding: str, innst: dict, skjema: dict | None = None) -> str:
    import ollama

    modell = innst["ollama"]["modell"]
    try:
        svar = ollama.chat(
            model=modell,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": melding},
            ],
            # Lav temperatur = mindre tilfeldighet. Vi vil ha saklige svar, ikke kreative.
            options={"temperature": innst["temperatur"]},
            # Tenkende modeller skriver skjult resonnering før svaret. Det koster tid.
            think=innst["ollama"].get("tenkning"),
            format=skjema,   # None = fri tekst, ellers må svaret følge JSON-skjemaet
        )
    except ollama.ResponseError as feil:
        if feil.status_code == 404:
            raise SystemExit(f"Modellen {modell} er ikke lastet ned. Kjør:  ollama pull {modell}") from None
        raise
    except ConnectionError:
        raise SystemExit("Får ikke kontakt med Ollama. Start Ollama-appen og prøv igjen.") from None
    return svar.message.content


def _anthropic(system: str, melding: str, innst: dict) -> str:
    import anthropic

    klient = anthropic.Anthropic()    # leser ANTHROPIC_API_KEY fra miljøet (.env lastes i konfig.py)
    svar = klient.messages.create(
        model=innst["anthropic"]["modell"],
        max_tokens=innst["anthropic"]["maks_tokens"],
        system=system,
        messages=[{"role": "user", "content": melding}],
    )
    return "".join(blokk.text for blokk in svar.content if blokk.type == "text")


if __name__ == "__main__":
    melding = " ".join(sys.argv[1:]) or "Si hei på norsk, i én setning."
    innst = last_innstillinger()["sprakmodell"]
    modell = innst[innst["leverandor"]]["modell"]
    print(f"Leverandør: {innst['leverandor']}   modell: {modell}\n")
    print(generer("Du er en hjelpsom assistent som svarer kort på norsk.", melding))
