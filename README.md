# 📚 Pensumboten

En studiebot som svarer på spørsmål, lager quiz og flashcards og legger en leseplan, **bare ut fra mitt eget pensum**: foiler, notater, øvingsoppgaver og tidligere eksamener. Hvert svar har kilde med fil og side, og står svaret ikke i materialet, sier boten det i stedet for å gjette.

Jeg bygget den som økonomistudent ved NTNU for å lære hvordan RAG (retrieval-augmented generation) fungerer, og for å øve til eksamenene mine i markedsføring, organisasjon og ledelse og bedriftsøkonomi høsten 2026.

> **English summary:** A local study assistant built on retrieval-augmented generation. It answers questions with page-level citations from my own course material, refuses when the answer isn't there, generates verified quizzes and flashcards, and schedules an exam reading plan that adapts to what I master. Retrieval and prompts are written by hand (no LangChain chains), everything runs locally on a MacBook with Ollama, and quality is measured against a test set: correct source in the top 6 for 29 of 30 questions, and 6 of 6 out-of-scope questions correctly refused.

![Dagsplanen](docs/bilder/dagsplan.png)

## Hva den gjør

| | |
|---|---|
| **💬 Spør** | Chat mot pensum med kilde til fil og side. Forstår oppfølgingsspørsmål («hva med pull?», «forklar enklere»). Svarer «Finnes ikke i materialet» når svaret mangler. |
| **🎯 Quiz** | Flervalg og kortsvar laget fra pensum. Hvert spørsmål kontrolleres før du ser det. Kortsvar vurderes punkt for punkt mot kilden. |
| **🗂️ Flashcards** | Kort med repetisjon som kommer igjen med voksende mellomrom (vanskelig, greit, lett). |
| **📅 I dag** | Leseplan frem til eksamen: nærmest eksamen får mest tid, svake temaer kommer oftere, og øvingsmåten endrer seg fra gjenkjenning til fri forklaring jo nærmere eksamen. |
| **📈 Mestring** | Mestring per tema, oppdatert etter hvert svar, og brukt av planleggeren. |

<p>
  <img src="docs/bilder/chat.png" width="49%" alt="Chat med kilder">
  <img src="docs/bilder/kortsvar.png" width="49%" alt="Kortsvar med vurdering">
</p>
<p>
  <img src="docs/bilder/flashcards.png" width="49%" alt="Flashcards">
  <img src="docs/bilder/planforklaring.png" width="49%" alt="Forklaring av planen">
</p>

## Slik virker den

```
pensum/ (PDF, Word, Markdown)
   │  innlesing: tekst per side, OCR av skannede sider (Apple Vision)
   ▼
biter på ~1000 tegn med overlapp  ──►  embeddings (multilingual-e5-base)  ──►  Chroma (lokalt)
                                                                                │
spørsmål ──► (omskriving av oppfølgingsspørsmål) ──► vektorsøk, 30 kandidater ──┘
                                                         │
                                       reranker (bge-reranker-v2-m3) → 6 beste biter
                                                         │
                                 prompt med nummererte biter → språkmodell (Ollama)
                                                         │
                                   svar med [1][2] → kildeliste fra metadata (fil, side)
```

Noen valg som gjorde en målbar forskjell:

- **Kildene settes av koden, ikke av modellen.** Modellen viser bare til bitnumre `[1]`, og fil og side hentes fra metadata. Da kan den ikke finne på sidetall.
- **Reranker etter vektorsøket** løftet riktig kilde fra dypt nede på listen til topp 6.
- **Kontekst foran PDF-bitene** (fag · fil · foiltittel) bare i søkevektoren, ikke i teksten modellen leser.
- **Eksempelsvar holdes utenfor** som standard. A-besvarelser er ikke fasit, og presset riktige kilder ned.
- **Quizspørsmål kontrolleres i fire steg:** sitatet må stå ordrett i kilden, riktig svar kan ikke skille seg ut ved lengde, modellen må svare riktig på sitt eget spørsmål, og nesten like spørsmål filtreres bort.
- **Tall regnes ut i Python.** Planen og forklaringen av den bygger på kode, og språkmodellen bare formulerer.

## Resultater

Målt mot håndlagde testsett (`tester/testsett_*.yaml`) med `uv run python -m src.testsett --med-svar`:

| Fag | Riktig kilde blant 6 | MRR@20 | Felle-spørsmål avvist |
|---|---|---|---|
| Organisasjon og ledelse | 14 av 15 | 0,882 | 3 av 3 |
| Markedsføring | 15 av 15 | 0,967 | 3 av 3 |

Felle-spørsmålene handler om ting som ikke står i pensum (for eksempel Blue Ocean og NPS). Der skal svaret være «Finnes ikke i materialet». I tillegg tester 32 enhetstester planleggeren, repetisjonen og sikkerhetskopien.

## Teknologi

Python 3.13 · [uv](https://docs.astral.sh/uv/) · Ollama (`gemma4:e4b-it-qat`, kjører på en MacBook med 16 GB) · sentence-transformers · Chroma · Gradio · SQLite · PyMuPDF og Apple Vision (OCR) · pytest

All kontakt med språkmodellen går gjennom `src/llm.py`. Bytte til Claude API er én linje i `config/innstillinger.yaml` og en nøkkel i `.env`.

## Kom i gang

Krever macOS (OCR bruker Apple Vision), [uv](https://docs.astral.sh/uv/) og [Ollama](https://ollama.com).

```bash
git clone https://github.com/arnulfflo/pensumbot.git && cd pensumbot
uv sync
ollama pull gemma4:e4b-it-qat           # eller kjør: uv run python -m src.sjekk_maskin

# Legg egne filer i pensum/<FAG>/{foiler,notater,oppgaver,eksamener}/
# og fag, eksamensdatoer og temaer i config/innstillinger.yaml og config/eksamener.yaml
uv run python -m src.indeks              # les inn og bygg søkeindeksen
./start.sh                               # åpner appen på http://127.0.0.1:7860
```

Alt kan også brukes fra terminalen: `src.chat`, `src.quiz`, `src.flashcards`, `src.i_dag`, `src.planlegger` (se `--help` på hver).

## Personvern og opphavsrett

Alt kjører lokalt, og ingen tekst sendes ut av maskinen så lenge Ollama brukes. Pensum, notater, eksamener og andres besvarelser ligger i `pensum/` og er **ikke** med i dette repoet. Det samme gjelder `data/` (søkeindeks og fremgang) og `.env`.

## Laget med Claude Code

Jeg bygget prosjektet sammen med [Claude Code](https://claude.com/claude-code) som parprogrammerer, ett steg om gangen med testing mellom hvert. Commitene viser det. Målet var å forstå hva som skjer i hvert ledd, ikke bare å få noe som virker.

## Lisens

[MIT](LICENSE)
