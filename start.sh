#!/bin/zsh
# Starter Pensumboten. Brukes av kommandoen «pensum» og av ikonet på skrivebordet.
#  - starter Ollama hvis den ikke kjører
#  - åpner bare nettleseren hvis appen allerede er i gang

cd "$(dirname "$0")" || exit 1
ADRESSE="http://127.0.0.1:7860"

if curl -s -o /dev/null "$ADRESSE"; then
  echo "Pensumboten kjører allerede. Åpner $ADRESSE"
  open "$ADRESSE"
  exit 0
fi

if ! curl -s -o /dev/null http://127.0.0.1:11434; then
  echo "Starter Ollama ..."
  open -a Ollama
  for i in {1..30}; do
    curl -s -o /dev/null http://127.0.0.1:11434 && break
    sleep 1
  done
fi

echo "Starter Pensumboten. Lukk dette vinduet eller trykk Ctrl+C for å stoppe."
exec "$HOME/.local/bin/uv" run python -m src.app
