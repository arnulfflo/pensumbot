# RAG-pensumbot med eksamensplanlegger

Oct 27, 2026 · @Arnulf Stefanussen Flo

## Sammendrag

Et studieverktøy som svarer på spørsmål og lager quiz ut fra mine egne notater, foiler, oppgaver og pensum, og som lager en leseplan frem mot eksamen som justerer seg etter hva jeg faktisk kan.

De to delene henger sammen: planleggeren bestemmer hva jeg skal jobbe med i dag, quizen tester det, og resultatene styrer neste dags plan. Det er denne koblingen et vanlig Claude-prosjekt ikke har.

Hovedgrunnen til å bygge det er å lære RAG, API-er og datahåndtering i praksis. Et Claude-prosjekt med filene lastet opp er reserveløsningen hvis byggingen tar for lang tid før eksamen.

## Gjøremål

Prosjektmappen er klar i `~/AI/pensumbot`, og pensum for ORG, MRK og BØA er kopiert inn. Neste steg: API-nøkkel og testsett, så Claude Code.

**Gjort**

- [x] Prosjektmappe med mappestruktur, SPEC.md og config-filer
- [x] Pensum, notater og eksamener kopiert fra OneDrive (originalene er urørt)
- [x] GoodNotes-filer samlet i `goodnotes/`-mapper, og instruks for håndskrift i `config/transkripsjon.txt`

**Nå, før Claude Code**

- [ ] Lag API-nøkkel i console.anthropic.com og sett en månedlig utgiftsgrense
- [ ] Kjør `cp .env.example .env` og lim inn nøkkelen i `.env`
- [ ] Bekreft fag for fase 1 (anbefalt: ORG1100)
- [ ] Skriv 10 testspørsmål og 2–3 felle-spørsmål i `tester/testsett_ORG1100.yaml`
- [ ] Kjør `git init` og `claude`, slå på plan-modus (Shift+Tab) og lim inn startprompten under Faser og byggeplan

**Fase 1 – grunnmur (ORG1100)**

- [ ] Innlesing av PDF, docx og md med metadata
- [ ] Chunking og embeddings i Chroma
- [ ] Spørsmål og svar med kilde
- [ ] Testscript: minst 8 av 10 riktige kilder

**Fase 1b – håndskrift**

- [ ] Transkriber én GoodNotes-fil og les gjennom resultatet
- [ ] Sjekk kostnaden i Console før resten kjøres
- [ ] Les inn transkripsjonene med `kilde: håndskrift`

**Fase 2 – quiz**

- [ ] Les inn eksamener med filter, så løsninger og eksempelsvar ikke lekker inn i oppgaver
- [ ] Flervalg, kortsvar og flashcards lagret i SQLite

**Fase 3 – eksamensplanlegger**

- [ ] Fyll inn eksamensdatoer og temaer i `config/eksamener.yaml` (sjekk emneoversikt-filene)
- [ ] Dagsplan og kommandoen `i dag`

**Fase 4 – kobling og repetisjon**

- [ ] Mestring styrer planen, feilsvar kommer igjen, og resten av øvingsmåtene legges til

**Fase 5 – flere fag og grensesnitt**

- [ ] MRK1001 og BOA1100 inn, med OCR av den skannede A-besvarelsen i MRK
- [ ] Gradio-grensesnitt

**Materiale å skaffe (legg det i OneDrive, så kopieres det inn)**

- [ ] Norsk Tipping-casen til ORG-eksamen høsten 2025
- [ ] Oppgavetekstene til BØA-eksamenene 2016–2025
- [ ] Løsningsforslag eller sensorveiledning for ORG og MRK
- [ ] A-besvarelse i BØA
- [ ] Pensumbøker som PDF uten kopisperre, hvis tilgjengelig

## Mål og ikke-mål

**Mål**

- Svare på spørsmål kun ut fra mitt eget materiale, med kilde (fil og side) på hvert svar.
- Si tydelig «finnes ikke i materialet» i stedet for å gjette.
- Lage quiz per fag og tema, gjerne i samme stil som tidligere eksamensoppgaver.
- Huske hva jeg svarer feil på, og gi meg det igjen senere.
- Lage en leseplan til eksamen som justeres når jeg henger etter eller sliter med et tema.

**Ikke-mål (foreløpig)**

- Deling med medstudenter. Pensumbøker kan ikke deles på grunn av opphavsrett.
- Løse matteoppgaver. Til MET1001/SØK1001 er en vanlig Claude-chat bedre.
- Nettside eller mobilapp. Terminal først, enkelt grensesnitt senere.
- Lese håndskrevne notater i første versjon.

## Funksjoner

Fire moduler som deler samme database. De to første er kjernen; planleggeren og repetisjonen bygges oppå.

### 1. Spørsmål og svar

Jeg skriver et spørsmål, for eksempel «Hva er forskjellen på Mintzbergs konfigurasjoner?», og velger eventuelt fag.

- Henter de 5–8 mest relevante tekstbitene fra databasen.
- Claude svarer kun ut fra disse bitene, med kildehenvisning: `ORG1100/foiler/F05.pdf, s. 12`.
- Hvis bitene ikke dekker spørsmålet: svarer «finnes ikke i materialet» og viser hva som var nærmest.
- Svaret vises med spørsmålet som overskrift og teksten under.

### 2. Quiz og andre øvingsmåter

Jeg velger fag, tema og antall spørsmål.

- Typer: flervalg, sant/usant, og kortsvar der Claude vurderer svaret mitt mot kilden.
- Hvis tidligere eksamener ligger i `eksamener/`, kan quizen lage oppgaver i samme stil.
- Hvert spørsmål lagres med fasit, kilde og om jeg svarte riktig.
- Etter quizen: poengsum per tema og hvilke temaer som er svake.

**Andre øvingsmåter**

Alle bruker samme henting og kildekrav som quizen, og resultatene lagres i de samme tabellene. Da tar mestringen og planen hensyn til dem.

| Øvingsmåte | Slik fungerer det | Passer best til |
| --- | --- | --- |
| Flashcards | Begrep på forsiden, definisjon og kilde på baksiden. Jeg vurderer selv (igjen / vanskelig / greit / lett), og det styrer når kortet kommer igjen. | Begreper og definisjoner i alle fag |
| Forklar med egne ord | Jeg forklarer et begrep som til en medstudent. Claude sammenligner med kilden og peker på hull og feil. | ORG1100, MRK1001 |
| Hvorfor-spørsmål | «Hvorfor gjelder dette?» og «hva skjer hvis …?», for å koble fakta til forståelse. | Modeller og teorier |
| Sammenlign begreper | To beslektede begreper side om side; jeg forklarer forskjellen. | Begreper som er lette å blande |
| Anvend på en case | Kort case om en bedrift der jeg bruker en modell fra pensum. | MRK1001, ORG1100 |
| Eksamensoppgave | Langsvarsoppgave i stil med tidligere eksamener, med tidtaker. Tilbakemelding ut fra kildene, og ut fra sensorveiledning hvis den finnes. | Alle fag med skriftlig eksamen |

Forskning på læringsteknikker peker på at det å hente frem svaret selv og spre øvingen over tid virker bedre enn omlesing og markering. Derfor bygges omlesing ikke inn som egen modus.

Planleggeren velger øvingsmåte etter hvor nær eksamen er: tidlig flashcards og forklaring, de siste ukene eksamensoppgaver og blandet øving.

Begrensning: Claudes vurdering av fritekstsvar er en indikasjon, ikke en karakter. Hvordan sensor vurderer, er UKJENT uten sensorveiledning.

### 3. Eksamensplanlegger

Jeg legger inn eksamensdato, temaliste per fag og hvor mange timer jeg har per dag.

- Lager en plan dag for dag frem til eksamen, med repetisjonsdager mot slutten.
- Temaer med lav mestring (fra quizen) får mer tid; temaer jeg kan godt, får mindre.
- Hopper jeg over en dag, fordeles det som gjenstår på nytt i stedet for at planen sprekker.
- Selve utregningen gjøres i Python, ikke av Claude, slik at timer og datoer alltid stemmer. Claude brukes bare til å forklare planen.
- Kommandoen `i dag` viser dagens temaer og starter en kort quiz på dem.

### 4. Repetisjon av feilsvar

- Spørsmål jeg svarer feil på, kommer igjen etter 1, 3 og 7 dager (enkel spaced repetition).
- Svarer jeg riktig, øker intervallet; feil igjen, starter det på nytt.
- Mestringsscoren per tema oppdateres og sendes tilbake til planleggeren.

## Arkitektur og dataflyt

Flyt (diagrammet ligger i Claude-dokumentet):

1. Innlesing, én gang per fag: pensumfiler → innlesing (tekst, fil og side) → chunking og embeddings → Chroma.
2. Bruk, hver gang jeg spør: jeg spør → henting av 5–8 nærmeste biter fra Chroma → Claude API (bare fra bitene) → svar eller quiz med kilde.
3. Oppfølging: resultatene lagres i SQLite (quiz og mestring) → planleggeren lager dagsplan i Python → dagens temaer går tilbake til «jeg spør».

Øverste rad kjøres én gang per fag. Midtre rad kjøres hver gang jeg spør. Nederste rad lukker sløyfen: quizresultater oppdaterer mestringen, og planleggeren velger neste dags temaer ut fra den.

## Datamodell og mappestruktur

To lagre: Chroma for teksten (søk etter mening) og SQLite for alt som skal telles og regnes (quiz, mestring, plan).

**Mapper**

```
~/AI/pensumbot/
  SPEC.md  .env  .env.example  .gitignore
  config/
    innstillinger.yaml   # modell, chunking, antall biter
    eksamener.yaml       # datoer og temaer (fase 3)
    transkripsjon.txt    # instruks for håndskrift
  tester/
    testsett_mal.yaml
  src/                   # koden, lages av Claude Code
  data/                  # chroma/ og studie.db, lages automatisk
  pensum/
    ORG1100/
      foiler/
        goodnotes/       # foiler med håndskrift over
      notater/
        goodnotes/
      oppgaver/
      eksamener/
        oppgaver/        # f.eks. 2025H_ORG1100_oppgavetekst.md
        losning/         # løsningsforslag og sensorveiledning
        eksempelsvar/    # A-besvarelser
    MRK1001/
    BOA1100/
    MET1001/
```

Mappe- og filnavn uten æ, ø og å. `type` hentes fra første mappenivå under faget, så `foiler/goodnotes/F1.pdf` er `type = foiler`.

A-besvarelser i `eksempelsvar/` viser hvordan et toppsvar er bygd opp, men er ikke fasit. De holdes unna oppgavelaging på samme måte som løsningene.

**Tidligere eksamener og løsninger** er det mest verdifulle materialet. De brukes til tre ting:

- **Oppgaver i riktig stil:** quiz og eksamensoppgaver lages etter mønster fra ekte eksamener.
- **Vurdering mot fasit:** svarene mine sammenlignes med løsningsforslag eller sensorveiledning, ikke bare med pensum.
- **Hva som ofte kommer:** temaer som går igjen på flere eksamener, får mer vekt i planleggeren.

Oppgaver og løsninger ligger i hver sin mappe, med år og semester i filnavnet. Løsningene hentes aldri inn når boten lager en oppgave, bare når den vurderer svaret mitt. Ellers lekker fasiten inn i spørsmålet. Dette håndheves med et metadatafilter i Chroma. Hver løsning merkes som offisiell (fra emneansvarlig) eller uoffisiell (fra studenter), fordi uoffisielle løsningsforslag kan inneholde feil.

**Chroma: én rad per tekstbit**

| Felt | Eksempel |
| --- | --- |
| tekst | «Mintzberg beskriver fem konfigurasjoner …» |
| fag | ORG1100 |
| type | foiler / notater / oppgaver / eksamener |
| fil | F05.pdf |
| side | 12 |
| tema | Organisasjonsstruktur (settes ved innlesing) |

**SQLite-tabeller**

| Tabell | Innhold |
| --- | --- |
| temaer | fag, tema, mestring (0–1), sist øvd |
| sporsmal | spørsmål eller kort, fasit, kilde, fag, tema, øvingsmåte (quiz, flashcard, forklaring, case, eksamen …) |
| forsok | spørsmål-id, dato, riktig/feil eller egenvurdering, tilbakemelding, neste repetisjon |
| plan | dato, fag, tema, øvingsmåte, planlagte minutter, fullført |
| eksamener | fag, dato, timer tilgjengelig per dag |

Temalisten per fag skrives inn for hånd i `eksamener.yaml`, gjerne fra emnebeskrivelsen eller pensumlisten. Den bør ikke gjettes av Claude.

## Teknologivalg

Alt kjører lokalt på egen maskin, bortsett fra kallene til Claude API.

| Del | Valg | Hvorfor |
| --- | --- | --- |
| Språk | Python | Enklest for alle bibliotekene under; Claude Code håndterer det godt |
| Rammeverk | LangChain (gjeldende versjon) til loaders og splitters | Lært i RAG-kurset; henting og prompt skrives selv i fase 1 for å forstå dem |
| Lese PDF/docx | PyPDFLoader, python-docx | Gir tekst med sidetall |
| Chunking | RecursiveCharacterTextSplitter, ca. 500–800 ord med litt overlapp | Lært i kurset; størrelse justeres mot testsettet |
| Embeddings | sentence-transformers, flerspråklig modell | Gratis, lokalt, takler norsk og engelsk |
| Vektordatabase | Chroma | Samme som i kurset; lagres som filer, ingen server |
| Strukturerte data | SQLite | Innebygd i Python, presise tall |
| Språkmodell | Claude API (kan byttes) | Svar, quiz og vurdering av kortsvar |
| Grensesnitt | Terminal, senere Gradio | Lært i kurset; gir knapper og felt uten webkunnskap |
| Byggeverktøy | Claude Code | Planlegger, skriver og forklarer koden |

Kostnad: API-kall koster per bruk. Eksakt pris per måned avhenger av bruk og er UKJENT til jeg har testet en uke. Sett en utgiftsgrense i Anthropic Console fra start.

**Bytte språkmodell:** alle kall til språkmodellen går gjennom én funksjon, og modellen velges i en konfigurasjonsfil. Da kan Claude byttes ut uten å skrive om resten av koden.

- **Gratis lokalt:** åpne modeller via Ollama på egen maskin. Ingen kostnad, og ingenting sendes ut. Til gjengjeld svakere på norsk, tregere, og oftere feil fasit i quiz.
- **Gratisnivå hos leverandører:** noen API-er har hatt gratisnivåer med grenser på antall kall. Gjeldende vilkår, og om dataene brukes til trening, må sjekkes før bruk.
- **Studenttilgang via NTNU:** UKJENT, verdt å sjekke.
- **Forslag:** lokal modell mens jeg utvikler og tester, sterkere modell til quiz og vurdering, der en feil koster mest.

## Kobling til RAG-kurset

Nesten hver fase har en direkte motpart i RAG-kurset, så prosjektet fungerer som praktisk oppgave for kurset.

| Fra kurset | Brukes til | Fase |
| --- | --- | --- |
| RAG-pipeline og «Hva er RAG» | Grunnforståelse av flyten | 1 |
| PyPDFLoader, RecursiveCharacterTextSplitter | Innlesing og chunking | 1 |
| Chroma, retrievers, avstandsmål | Lagring og henting | 1 |
| Metadatafiltrering i Chroma (`where`) | Søk i ett fag; holde løsninger unna oppgavelaging | 1–2 |
| «Common RAG Pipeline Pitfalls» | Sjekkliste ved testing | 1 |
| PromptTemplate, few-shot, chain-of-thought | Quiz i eksamensstil, vurdering av svar | 2, 4 |
| JsonOutputParser | Quizspørsmål som strukturert data til SQLite | 2 |
| Gradio | Grensesnitt | 5 |
| Tool og agenter | Planleggeren som verktøy boten kan kalle | Etter 5 |
| MCP | Pensumbasen som verktøy Claude kan bruke direkte | Etter 5 |

Kurset bruker IBM watsonx og Granite, og låser LangChain til versjon 0.2. Watsonx byttes ut med Claude eller en gratis modell og lokale embeddings, og nyere LangChain-versjoner avviker fra kurskoden.

Hoppes over foreløpig: Flask, multi-agent-rammeverk (AutoGen, CrewAI, BeeAI), Pinecone, Haystack og fine-tuning. LangChain og LlamaIndex blandes ikke.

## Faser og byggeplan

Én fase ferdig og testet før neste starter. Hver fase skal gi noe jeg kan bruke til studiene.

1. **Grunnmur (ett fag).** Samle ORG1100 eller MRK1001 i mappestrukturen. Bygg innlesing, chunking, embeddings og spørsmål/svar i terminalen.
   - Ferdig når: 8 av 10 testspørsmål får riktig svar med riktig kilde.
2. **Quiz.** Flervalg, kortsvar og flashcards fra ett valgt tema, lagret i SQLite. De andre øvingsmåtene legges til i fase 4.
   - Ferdig når: jeg har tatt tre quizer og resultatene ligger i databasen.
3. **Eksamensplanlegger.** Les `eksamener.yaml`, lag dagsplan, kommandoen `i dag`.
   - Ferdig når: planen fordeler seg riktig på nytt når jeg markerer en dag som hoppet over.
4. **Kobling og repetisjon.** Quizresultater oppdaterer mestring; svake temaer får mer tid i planen; feilsvar kommer igjen.
   - Ferdig når: et tema jeg feiler på, dukker opp oftere i planen uken etter.
5. **Flere fag og grensesnitt.** Legg til resten av fagene og et enkelt Gradio-grensesnitt.

**Stoppregel:** hvis fase 1 ikke gir nyttige svar etter to helger, bruker jeg et Claude-prosjekt med filene frem til eksamen og bygger videre etterpå. Studietid går foran byggetid.

**Første prompt til Claude Code**

```
Jeg vil bygge en RAG-app i Python for å studere. Den skal svare på spørsmål og lage quiz ut fra mine egne notater, foiler, oppgaver og eksamener, og senere lage en leseplan frem mot eksamen som justerer seg etter hva jeg kan. Hele spesifikasjonen står i SPEC.md – les den først, så du vet hvor prosjektet skal, men bygg bare fase 1 nå.

Fase 1 gjelder faget ORG1100.

Mappestruktur: pensum/<fag>/<type>/... der type er første mappenivå under faget (foiler, notater, oppgaver, eksamener). Undermapper som heter goodnotes/ inneholder PDF-er med håndskrift over trykt tekst. I fase 1 leser du bare den trykte teksten fra dem, som vanlige filer. Transkripsjon av håndskrift kommer senere.

Fase 1 skal:
- lese inn PDF (med LangChain sin PyPDFLoader), docx og md fra pensum/ORG1100/foiler, notater og oppgaver (eksamener tas i fase 2)
- lagre fag, type, fil, side og om filen ligger i goodnotes/ som metadata
- chunke med RecursiveCharacterTextSplitter, lage flerspråklige sentence-transformers-embeddings og lagre i lokal Chroma i data/
- svare på spørsmål via Claude API kun ut fra hentede biter, med kilde (fil og side), og si «finnes ikke i materialet» når svaret ikke finnes
- lese innstillinger fra config/innstillinger.yaml og API-nøkkelen fra .env
- ha et script som kjører tester/testsett_ORG1100.yaml og viser hvor mange som fikk riktig kilde

Skriv henting og prompt selv, uten ferdige LangChain-kjeder. Bruk gjeldende versjoner av bibliotekene og et virtuelt Python-miljø.

Jeg bygger dette for å lære RAG. Lag en plan først, forklar hvert steg og hvorfor du velger som du gjør, og spør meg om det som er uklart før du skriver kode. Ta ett steg om gangen og la meg teste før du går videre.
```

**Prompt for fase 1b (håndskrift), når fase 1 fungerer**

```
Legg til et transkripsjonssteg i innlesingen for PDF-ene i alle mapper som heter goodnotes/: gjør hver side om til bilde med PyMuPDF, send den til Claude API med instruksen i config/transkripsjon.txt, og lagre svaret per side i data/transkripsjoner/, slik at ingen side transkriberes to ganger. Hopp over sider som returnerer INGEN. Les inn transkripsjonene som egne biter med metadata kilde: håndskrift, fil og side. Test først på én fil og vis meg resultatet før du kjører resten.
```

## Testing og kvalitet

Et fast testsett avgjør om endringer gjør boten bedre eller verre; uten det gjetter jeg.

- **Testsett:** 10–20 spørsmål per fag der jeg vet svaret og hvor i materialet det står. Lagres i en fil og kjøres etter hver endring.
- **Måles:** fant den riktig kilde blant de hentede bitene? Var svaret riktig? Sa den «finnes ikke» når det faktisk ikke fantes?
- **Feller-spørsmål:** 2–3 spørsmål om ting som ikke er i pensum, for å sjekke at den ikke dikter opp svar.
- **Det jeg justerer:** chunkstørrelse, overlapp, antall hentede biter og instruksen til Claude. Én ting om gangen.
- **Quizkvalitet:** stikkprøve fem spørsmål per quiz mot kilden. Feil fasit er verre enn ingen quiz.
- **Planlegger:** enkle tester i Python som sjekker at sum av planlagte timer aldri overstiger tilgjengelige timer, og at ingen dag ligger etter eksamensdatoen.

## Risikoer, begrensninger og åpne spørsmål

Største risiko er tid: byggingen kan spise lesetiden frem mot eksamen.

**Risikoer og begrensninger**

- E-bøker med kopisperre (DRM) lar seg ofte ikke lese inn. Foiler og egne notater fungerer som regel.
- Skannede sider krever OCR, et ekstra steg som er utelatt i første versjon.
- Formler blir rotete ved tekstuttrekk fra PDF. Matte og regnskapsoppgaver med tall passer dårlig.
- Claude kan lage quizspørsmål med feil fasit. Kilden vises alltid, og stikkprøver er nødvendig.
- Pensumbøker kan ikke deles videre. Verktøyet er kun til eget bruk.

**Åpne spørsmål**

- [ ] Eksamensdatoer for de fire fagene: UKJENT (kan stå i emneoversikt-filene)
- [x] Format på notatene: Word (kapittelnotater) og GoodNotes-PDF-er med håndskrift over foiler
- [x] Tidligere eksamener: ORG høsten 2025 (oppgave og A-besvarelse), MRK Spike-case og A-besvarelse, BØA løsningsforslag 2016–2025
- [ ] Er pensumbøkene tilgjengelige som PDF uten kopisperre: UKJENT
- [ ] Temaliste per fag (fra emnebeskrivelse eller pensumliste): UKJENT
- [ ] Månedlig API-kostnad ved normal bruk: UKJENT, måles første uke
- [ ] Fag for fase 1: ORG1100 anbefalt, ikke bekreftet
