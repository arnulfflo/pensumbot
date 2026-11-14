"""All kontakt med språkmodellen går gjennom generer().

Resten av koden vet ikke om svaret kommer fra Ollama eller Claude. For å bytte
endrer du bare `sprakmodell.leverandor` i config/innstillinger.yaml.

Kjør:  uv run python -m src.llm "Si hei på norsk"
"""

import json
import re
import sys

from src.konfig import last_innstillinger


class SprakmodellFeil(RuntimeError):
    """Språkmodellen kan ikke brukes: Ollama er ikke startet, eller modellen er ikke lastet ned.

    Meldingen er skrevet til brukeren. Appen viser den i stedet for å henge, og i terminalen skrives
    den uten feilsporing (se src/__init__.py)."""


def _ollama_feil(feil: Exception, modell: str) -> Exception:
    """Gjør en feil fra Ollama om til en feil resten av koden kjenner."""
    import httpx
    import ollama

    if isinstance(feil, ollama.ResponseError) and feil.status_code == 404:
        return SprakmodellFeil(f"Modellen {modell} er ikke lastet ned. Kjør:  ollama pull {modell}")
    if isinstance(feil, (ConnectionError, httpx.ConnectError)):
        return SprakmodellFeil("Får ikke kontakt med Ollama. Start Ollama-appen og prøv igjen.")
    if isinstance(feil, httpx.TimeoutException):
        return TimeoutError(f"{modell} svarte ikke innen tidsgrensen")
    return feil


def generer(system: str, melding: str, skjema: dict | None = None, temperatur: float | None = None) -> str:
    """system = instruksen (hvordan modellen skal oppføre seg), melding = det brukeren sender.

    skjema: et JSON-skjema svaret må følge. Brukes av generer_json().
    temperatur: overstyrer innstillingen, f.eks. høyere for nye caser som skal være forskjellige.
    """
    innst = dict(last_innstillinger()["sprakmodell"])
    if temperatur is not None:
        innst["temperatur"] = temperatur
    leverandor = innst["leverandor"]

    if leverandor == "ollama":
        return _ollama(system, melding, innst, skjema)
    if leverandor == "anthropic":
        if skjema:
            system += ("\n\nSvar BARE med gyldig JSON som følger dette skjemaet, uten annen tekst:\n"
                       + json.dumps(skjema, ensure_ascii=False))
        return _anthropic(system, melding, innst)
    raise ValueError(f"Ukjent leverandør i innstillinger.yaml: {leverandor!r} (bruk ollama eller anthropic)")


def generer_json(system: str, melding: str, skjema: dict, temperatur: float | None = None) -> dict:
    """Som generer(), men svaret er strukturert data (dict) i stedet for fri tekst.

    Ollama tvinges til å følge skjemaet (structured outputs). Claude får skjemaet i
    instruksen. Eventuelle ```json-gjerder rundt svaret fjernes før tolkning.
    """
    tekst = generer(system, melding, skjema, temperatur).strip()
    tekst = re.sub(r"^```(?:json)?\s*|\s*```$", "", tekst)
    return json.loads(tekst)


def _ollama(system: str, melding: str, innst: dict, skjema: dict | None = None) -> str:
    import httpx
    import ollama

    modell = innst["ollama"]["modell"]
    # Tidsgrense: et kall som henger, skal gi en feil i stedet for å stoppe hele programmet.
    klient = ollama.Client(timeout=innst["ollama"].get("tidsgrense_sekunder", 90))
    try:
        svar = klient.chat(
            model=modell,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": melding},
            ],
            # Lav temperatur = mindre tilfeldighet. Vi vil ha saklige svar, ikke kreative.
            # num_predict: øvre grense for svarets lengde, så modellen aldri kan gå i løkke.
            options={"temperature": innst["temperatur"], "num_predict": innst["ollama"].get("maks_tokens", 1500)},
            # Tenkende modeller skriver skjult resonnering før svaret. Det koster tid.
            think=innst["ollama"].get("tenkning"),
            format=skjema,   # None = fri tekst, ellers må svaret følge JSON-skjemaet
        )
    except (ollama.ResponseError, ConnectionError, httpx.HTTPError) as feil:
        raise _ollama_feil(feil, modell) from None
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


# ---------- verktøybruk (agenter) ----------
#
# En agent er en løkke der modellen selv velger verktøy. Samtalen lagres i et nøytralt format,
# så agenten virker likt med Ollama og Claude:
#   {"rolle": "bruker", "tekst": ...}
#   {"rolle": "assistent", "tekst": ..., "kall": [{"id", "navn", "argumenter"}]}
#   {"rolle": "verktoy", "id": ..., "navn": ..., "resultat": ...}
# Verktøy beskrives som {"navn", "beskrivelse", "parametre": JSON-skjema}.

def chat_med_verktoy(system: str, samtale: list[dict], verktoy: list[dict]) -> dict:
    """Ett steg i en agent. Returnerer {"tekst": ..., "kall": [...]}; tom «kall» betyr at modellen vil svare."""
    innst = last_innstillinger()["sprakmodell"]
    if innst["leverandor"] == "ollama":
        return _ollama_verktoy(system, samtale, verktoy, innst)
    if innst["leverandor"] == "anthropic":
        return _anthropic_verktoy(system, samtale, verktoy, innst)
    raise ValueError(f"Ukjent leverandør i innstillinger.yaml: {innst['leverandor']!r}")


def _ollama_verktoy(system, samtale, verktoy, innst) -> dict:
    import httpx
    import ollama

    meldinger = [{"role": "system", "content": system}]
    for m in samtale:
        if m["rolle"] == "bruker":
            meldinger.append({"role": "user", "content": m["tekst"]})
        elif m["rolle"] == "assistent":
            meldinger.append({"role": "assistant", "content": m["tekst"] or "",
                              "tool_calls": [{"function": {"name": k["navn"], "arguments": k["argumenter"]}}
                                             for k in m["kall"]]})
        else:
            meldinger.append({"role": "tool", "content": m["resultat"], "tool_name": m["navn"]})
    klient = ollama.Client(timeout=innst["ollama"].get("tidsgrense_sekunder", 90))
    try:
        svar = klient.chat(
            model=innst["ollama"]["modell"], messages=meldinger,
            tools=[{"type": "function", "function": {"name": v["navn"], "description": v["beskrivelse"],
                                                     "parameters": v["parametre"]}} for v in verktoy],
            options={"temperature": innst["temperatur"], "num_predict": innst["ollama"].get("maks_tokens", 1500)},
            think=innst["ollama"].get("tenkning"),
        )
    except (ollama.ResponseError, ConnectionError, httpx.HTTPError) as feil:
        raise _ollama_feil(feil, innst["ollama"]["modell"]) from None
    kall = [{"id": f"kall{i}", "navn": k.function.name, "argumenter": dict(k.function.arguments or {})}
            for i, k in enumerate(svar.message.tool_calls or [])]
    return {"tekst": svar.message.content or "", "kall": kall}


def _anthropic_verktoy(system, samtale, verktoy, innst) -> dict:
    import anthropic

    meldinger = []
    for m in samtale:
        if m["rolle"] == "bruker":
            meldinger.append({"role": "user", "content": m["tekst"]})
        elif m["rolle"] == "assistent":
            innhold = [{"type": "text", "text": m["tekst"]}] if m["tekst"] else []
            innhold += [{"type": "tool_use", "id": k["id"], "name": k["navn"], "input": k["argumenter"]} for k in m["kall"]]
            meldinger.append({"role": "assistant", "content": innhold})
        else:
            blokk = {"type": "tool_result", "tool_use_id": m["id"], "content": m["resultat"]}
            # Claude vil ha alle verktøysvar etter ett steg samlet i én brukermelding.
            if meldinger and meldinger[-1]["role"] == "user" and isinstance(meldinger[-1]["content"], list):
                meldinger[-1]["content"].append(blokk)
            else:
                meldinger.append({"role": "user", "content": [blokk]})
    svar = anthropic.Anthropic().messages.create(
        model=innst["anthropic"]["modell"], max_tokens=innst["anthropic"]["maks_tokens"], system=system,
        messages=meldinger,
        tools=[{"name": v["navn"], "description": v["beskrivelse"], "input_schema": v["parametre"]} for v in verktoy],
    )
    return {"tekst": "".join(b.text for b in svar.content if b.type == "text"),
            "kall": [{"id": b.id, "navn": b.name, "argumenter": dict(b.input)} for b in svar.content if b.type == "tool_use"]}


if __name__ == "__main__":
    melding = " ".join(sys.argv[1:]) or "Si hei på norsk, i én setning."
    innst = last_innstillinger()["sprakmodell"]
    modell = innst[innst["leverandor"]]["modell"]
    print(f"Leverandør: {innst['leverandor']}   modell: {modell}\n")
    print(generer("Du er en hjelpsom assistent som svarer kort på norsk.", melding))
