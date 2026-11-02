"""Fase 5: Gradio-grensesnitt i nettleseren. Bruker de samme funksjonene som terminalkommandoene.

Kjører bare på din maskin (127.0.0.1). Ingenting deles på nettet.
Utseendet ligger i src/app.css; fargene per fag i FARGER under.

Kjør:  uv run python -m src.app      (åpner http://127.0.0.1:7860 i nettleseren)
"""

import json
from datetime import date, timedelta
from html import escape
from pathlib import Path

import gradio as gr

from src.database import koble, lagre_sporsmal
from src.flashcards import forfalte, lag_nye_kort
from src.henting import Bit, hent
from src.innlesing import alle_fag, standardfag
from src.kortsvar import STILER, vurder
from src.llm import generer
from src.planlegger import UKEDAGER, angre_hopp_over, blokker_for, hopp_over, lag_og_lagre, last_eksamener, marker_fullfort
from src.quiz import modellnavn, sporsmal_strom
from src.repetisjon import forfalte_sporsmal, lagre_resultat
from src.svar import svar_pa

FAG = alle_fag()
BOKSTAVER = "ABCD"
FARGER = {"MRK1001": "#ea7a1a", "ORG1100": "#2f6fde", "BOA1100": "#1f9d63", "MET1001": "#8b5cf6"}
NAVN = {"MRK1001": "Markedsføring", "ORG1100": "Organisasjon og ledelse", "BOA1100": "Bedriftsøkonomi",
        "MET1001": "Metode"}
IKONER = {"flashcards": "🗂️", "flervalg": "🎯", "kortsvar": "✍️", "repetisjon": "🔁"}
OVINGSNAVN = {"flashcards": "Flashcards", "flervalg": "Flervalg", "kortsvar": "Kortsvar", "repetisjon": "Repetisjon"}

# Quizøkter per nettleserfane. Generatorer kan ikke ligge i gr.State (den kopierer verdiene),
# så de lagres her med Gradios økt-ID som nøkkel.
OKTER: dict[str, dict] = {}


# ---------- små HTML-hjelpere ----------

def farge(fag: str) -> str:
    return FARGER.get(fag, "#64748b")


def merke(fag: str, lys: bool = False) -> str:
    return f'<span class="merke{" lys" if lys else ""}" style="--fag:{farge(fag)}">{escape(fag)}</span>'


def kort_tema(tema: str) -> str:
    """«Distribusjon (kap. 8)» → «Distribusjon»."""
    return tema.split(" (")[0]


def topp() -> str:
    datoer, _, _ = last_eksamener()
    eks = "".join(
        f'<div class="eks" style="--fag:{farge(fag)}">{escape(fag)}<b>{(d - date.today()).days} dager</b></div>'
        for fag, d in sorted(datoer.items(), key=lambda x: x[1]) if d >= date.today())
    return (f'<div class="topp"><div><h1>📚 Pensumboten</h1>'
            f'<div class="under">Spør, øv og følg planen – alt fra ditt eget pensum.</div></div>'
            f'<div class="nedtelling">{eks}</div></div>')


# ---------- Spør ----------

def svar_som_markdown(s) -> str:
    deler = [s.tekst]
    if s.finnes_ikke:
        vist = s.biter[:3]
        deler.append("\n\n**Nærmeste treff i materialet:**")
    else:
        vist = [b for b in s.biter if b in s.siterte] or s.biter
        deler.append("\n\n**Kilder:**")
    for b in vist:
        deler.append(f"\n- `[{s.biter.index(b) + 1}]` {b.metadata['fag']}/{b.kilde}")
    tekster = "".join(f"<p><b>[{nr}] {escape(b.metadata['fag'])}/{escape(b.kilde)}</b></p>"
                      f"<blockquote>{escape(b.tekst)}</blockquote>"
                      for nr, b in enumerate(s.biter, start=1))
    deler.append(f"\n\n<details><summary>Les kildetekstene ({len(s.biter)})</summary>{tekster}</details>")
    return "".join(deler)


def spor(melding, samtale, fag, eksempelsvar):
    if not melding.strip():
        yield samtale, samtale, melding
        return
    samtale = samtale + [{"role": "user", "content": melding},
                         {"role": "assistant", "content": f"*Leter i {fag} …*"}]
    yield samtale, samtale, ""
    try:
        s = svar_pa(melding, fag=fag, med_eksempelsvar=eksempelsvar)
        samtale[-1] = {"role": "assistant", "content": svar_som_markdown(s)}
    except TimeoutError:
        samtale[-1] = {"role": "assistant", "content": "Språkmodellen brukte for lang tid. Prøv igjen."}
    yield samtale, samtale, ""


# ---------- Quiz ----------

def _repetisjonsstrom(fag):
    """Forfalte feilsvar i samme form som sporsmal_strom: (spørsmål, bit, id)."""
    for s in forfalte_sporsmal(koble(), fag):
        liste = json.loads(s["alternativer"]) if s["alternativer"] else []
        bit = Bit(s["kildetekst"] or s["sitat"] or "", {"fil": s["kilde"]}, 0.0)
        if s["ovingsmate"] == "flervalg":
            q = {"sporsmal": s["sporsmal"], "alternativer": liste, "fasit": s["fasit"], "forklaring": s["forklaring"],
                 "sitat": s["sitat"], "type": "flervalg", "tema": s["tema"]}
        else:
            q = {"sporsmal": s["sporsmal"], "nokkelpunkter": liste, "modellsvar": s["fasit"], "fasit": s["fasit"],
                 "sitat": s["sitat"], "type": "kortsvar", "tema": s["tema"]}
        yield q, bit, s["id"], s["kilde"]


def _ny_strom(fag, tema, type_, stil):
    if type_ == "repetisjon":
        yield from _repetisjonsstrom(fag)
        return
    db = koble()
    for q, bit in sporsmal_strom(fag, tema, 50, type_, stil):
        kilde = f"{fag}/{bit.kilde}"
        sid = lagre_sporsmal(db, fag=fag, tema=tema, ovingsmate=type_, sporsmal=q["sporsmal"],
                             alternativer=q.get("alternativer") or q.get("nokkelpunkter"), fasit=q["fasit"],
                             forklaring=q.get("forklaring"), sitat=q["sitat"], kilde=kilde, modell=modellnavn(),
                             kildetekst=bit.tekst)
        yield {**q, "type": type_, "tema": tema}, bit, sid, kilde


def _poeng(okt) -> str:
    if not okt or not okt.get("besvart"):
        return ""
    andel = okt["riktige"] / okt["besvart"]
    return (f'<div class="poeng"><div>Besvart <b>{okt["besvart"]}</b></div>'
            f'<div>Riktige <b>{okt["riktige"]}</b></div><div>Treff <b>{andel:.0%}</b></div></div>')


def _sporsmalskort(fag, q, nr) -> str:
    stil = f' · {escape(q["stil"])}' if q.get("stil") and q["stil"] != "forklar" else ""
    return (f'<div class="kort" style="--fag:{farge(fag)}"><div class="topplinje">'
            f'<span>{merke(fag)} &nbsp;{escape(kort_tema(q.get("tema") or ""))}</span>'
            f'<span>Spørsmål {nr} · {OVINGSNAVN[q["type"]]}{stil}</span></div>'
            f'<div class="sporsmal">{escape(q["sporsmal"])}</div></div>')


def _melding(tekst) -> str:
    return f'<div class="tom">{escape(tekst)}</div>'


def nytt_sporsmal(fag, tema, type_, stil, request: gr.Request):
    skjul = gr.update(visible=False)
    if type_ != "repetisjon" and not tema.strip():
        return _melding("Skriv et tema først, f.eks. «prisstrategi» eller «kap 9»."), skjul, skjul, "", ""
    okt = OKTER.get(request.session_hash)
    nokkel = (fag, tema, type_, stil)
    if not okt or okt["nokkel"] != nokkel:
        okt = OKTER[request.session_hash] = {"nokkel": nokkel, "strom": _ny_strom(fag, tema, type_, stil),
                                             "besvart": 0, "riktige": 0, "nr": 0}
    try:
        q, bit, sid, kilde = next(okt["strom"])
    except StopIteration:
        okt["nokkel"] = None
        tekst = ("Ingen spørsmål skal repeteres nå. 🎉" if type_ == "repetisjon"
                 else f"Fant ikke flere gode spørsmål om «{tema}». Prøv et bredere tema.")
        return _melding(tekst), skjul, skjul, "", _poeng(okt)
    okt.update(q=q, bit=bit, sid=sid, kilde=kilde, nr=okt["nr"] + 1)
    kort = _sporsmalskort(fag, q, okt["nr"])
    if q["type"] == "flervalg":
        valg = [f"{b}) {a}" for b, a in zip(BOKSTAVER, q["alternativer"])]
        return kort, gr.update(choices=valg, value=None, visible=True), skjul, "", _poeng(okt)
    return kort, skjul, gr.update(value="", visible=True), "", _poeng(okt)


def _tilbakemelding(riktig: bool, dom: str, innhold: str) -> str:
    return (f'<div class="tilbakemelding {"riktig" if riktig else "feil"}">'
            f'<div class="dom">{"✅" if riktig else "❌"} {dom}</div>{innhold}</div>')


def svar_quiz(valgt, tekst, request: gr.Request):
    okt = OKTER.get(request.session_hash)
    if not okt or "q" not in okt:
        return _melding("Trykk «Nytt spørsmål» først."), _poeng(okt)
    q, bit, sid = okt["q"], okt["bit"], okt["sid"]
    if q["type"] == "flervalg":
        if not valgt:
            return _melding("Velg et alternativ."), _poeng(okt)
        svar = valgt[3:]
        riktig = svar == q["fasit"]
        dom = "Riktig!" if riktig else f"Feil. Riktig svar: {escape(q['fasit'])}"
        innhold = f"<p>{escape(q.get('forklaring') or '')}</p>"
        tilbakemelding = None
    else:
        if len(tekst.split()) < 3:
            return _melding("Skriv et svar på 2–4 setninger."), _poeng(okt)
        svar = tekst
        try:
            v = vurder(q, svar, bit.tekst)
        except (TimeoutError, ValueError):
            return (_tilbakemelding(False, "Vurderingen feilet",
                                    f'<div class="modellsvar"><b>Sammenlign selv med modellsvaret:</b><br>'
                                    f'{escape(q["modellsvar"])}</div>'), _poeng(okt))
        riktig, tilbakemelding = v["riktig"], v["tilbakemelding"]
        dom = f"{'Godkjent' if riktig else 'Ikke godkjent'} · {sum(v['dekket'])} av {len(v['dekket'])} nøkkelpunkter"
        punkter = "".join(f"<li>{'✓' if d else '·'} {escape(p)}</li>" for p, d in zip(q["nokkelpunkter"], v["dekket"]))
        punkter += "".join(f"<li>✗ Stemmer ikke med kilden: {escape(f)}</li>" for f in v["feil"])
        innhold = (f"<ul>{punkter}</ul><p>{escape(v['tilbakemelding'])}</p>"
                   f'<div class="modellsvar"><b>Modellsvar:</b> {escape(q["modellsvar"])}</div>'
                   f'<p class="notis">Vurderingen er en indikasjon fra en liten modell, ikke en karakter.</p>')
    neste = lagre_resultat(koble(), sid, svar, riktig, tilbakemelding)
    okt["besvart"] += 1
    okt["riktige"] += int(riktig)
    sitat = f" «{escape(q['sitat'])}»" if q.get("sitat") else ""
    innhold += f'<div class="kilde">Kilde: {escape(okt["kilde"])}{sitat}'
    innhold += f"<br>Kommer igjen {neste:%d.%m} for repetisjon.</div>" if neste else "</div>"
    del okt["q"]
    return _tilbakemelding(riktig, dom, innhold), _poeng(okt)


# ---------- Flashcards ----------

def _kort(kid):
    return koble().execute("SELECT * FROM sporsmal WHERE id = ?", (kid,)).fetchone()


def _flashcard(ko, vis_svar=False) -> str:
    if not ko:
        return _melding("Ingen kort å øve på nå. Skriv et tema og trykk «Start» for å lage nye kort.")
    k = _kort(ko[0])
    svar = (f'<div class="svar">{escape(k["fasit"])}<div class="kilde">Kilde: {escape(k["kilde"])}</div></div>'
            if vis_svar else "")
    return (f'<div class="kort flashcard" style="--fag:{farge(k["fag"])}"><div class="topplinje">'
            f'<span>{merke(k["fag"])} &nbsp;{escape(kort_tema(k["tema"]))}</span><span>{len(ko)} kort igjen</span></div>'
            f'<div class="sporsmal">{escape(k["sporsmal"])}</div>{svar}</div>')


def hent_kort(fag, tema, nye):
    db = koble()
    if nye and tema.strip():
        lag_nye_kort(db, fag, tema, int(nye))
    ko = [k["id"] for k in forfalte(db, fag, tema.strip() or None)]
    return ko, _flashcard(ko), gr.update(visible=bool(ko)), gr.update(visible=False)


def snu(ko):
    if not ko:
        return _flashcard(ko), gr.update(visible=False), gr.update(visible=False)
    return _flashcard(ko, vis_svar=True), gr.update(visible=False), gr.update(visible=True)


def vurder_kort(vurdering, ko):
    if ko:
        kid = ko.pop(0)
        lagre_resultat(koble(), kid, svar=vurdering, riktig=vurdering in ("greit", "lett"), vurdering=vurdering)
        if vurdering == "igjen":
            ko.append(kid)
    return ko, _flashcard(ko), gr.update(visible=bool(ko)), gr.update(visible=False)


# ---------- I dag og plan ----------

def _dagens(db):
    return [dict(b) for b in blokker_for(db, date.today()) if b["fag"] != "-"]


def _blokk_html(b) -> str:
    status = {"fullfort": ("fullfort", "✓ Fullført"), "hoppet_over": ("fullfort", "Hoppet over")}.get(b["status"])
    klasse, tekst = status or ("", f"{b['minutter']} min")
    return (f'<div class="blokk {klasse}" style="--fag:{farge(b["fag"])}">'
            f'<div class="ikon">{IKONER.get(b["ovingsmate"], "📘")}</div>'
            f'<div class="tekst"><div class="tema">{escape(kort_tema(b["tema"]))}</div>'
            f'<div class="meta">{merke(b["fag"], lys=True)} &nbsp;{OVINGSNAVN.get(b["ovingsmate"], b["ovingsmate"])}</div></div>'
            f'<div class="status">{tekst}</div></div>')


def _uke_html(db) -> str:
    dager = []
    for i in range(1, 8):
        dag = date.today() + timedelta(days=i)
        blokker = [b for b in blokker_for(db, dag) if b["fag"] != "-" and b["status"] == "planlagt"]
        biter = "".join(f'<div class="bit" style="--fag:{farge(b["fag"])}" title="{escape(b["tema"])}">'
                        f'{escape(kort_tema(b["tema"]))}</div>' for b in blokker)
        dager.append(f'<div class="dag"><div class="navn">{UKEDAGER[dag.weekday()][:3]} <span>{dag:%d.%m}</span></div>'
                     f'{biter or "<div class=bit>fri</div>"}</div>')
    return f'<div class="uke">{"".join(dager)}</div>'


def vis_plan():
    db = koble()
    if not _dagens(db):
        lag_og_lagre(db)
    dagens = _dagens(db)
    igjen = sum(b["status"] == "planlagt" for b in dagens)
    feilsvar = len(forfalte_sporsmal(db))
    varsel = f' <span class="varsel">🔁 {feilsvar} feilsvar venter på repetisjon</span>' if feilsvar else ""
    overskrift = (f'<div class="overskrift"><h2>I dag · {UKEDAGER[date.today().weekday()].capitalize()} {date.today():%d.%m}</h2>'
                  f'<span class="info">{igjen} av {len(dagens)} blokker igjen</span>{varsel}</div>')
    return overskrift, dagens, _uke_html(db)


def ov_paa_blokk(blokk_id):
    """Fyller ut riktig fane med fag og tema fra blokken, og bytter til den."""
    b = koble().execute("SELECT * FROM plan WHERE id = ?", (blokk_id,)).fetchone()
    if b["ovingsmate"] == "flashcards":
        return (gr.Tabs(selected="kort"), gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(value=b["fag"]), gr.update(value=b["tema"]))
    type_ = "flervalg" if b["ovingsmate"] == "flervalg" else "kortsvar"
    stil = "blandet" if type_ == "kortsvar" else "forklar"
    return (gr.Tabs(selected="quiz"), gr.update(value=b["fag"]), gr.update(value=b["tema"]),
            gr.update(value=type_), gr.update(value=stil), gr.update(), gr.update())


def fullfort(blokk_id):
    db = koble()
    marker_fullfort(db, blokk_id)
    lag_og_lagre(db, date.today() + timedelta(days=1))   # mestringen fra økten styrer resten
    return vis_plan()


def hopp_over_i_dag():
    hopp_over(koble(), date.today())
    return vis_plan()


def angre_i_dag():
    angre_hopp_over(koble(), date.today())
    return vis_plan()


def _forklaring_html(f, oppsummering) -> str:
    totalt = sum(x["blokker"] for x in f["fag"]) or 1
    rader = "".join(
        f'<div class="planfag" style="--fag:{farge(x["fag"])}"><div class="topp-linje">{merke(x["fag"])}'
        f'<span>eksamen {x["dato"]:%d.%m} · om <b>{x["dager_igjen"]} dager</b></span>'
        f'<span class="timer">{x["blokker"]} blokker · {x["timer"]:.0f} t</span></div>'
        f'<div class="stolpe"><div style="width:{x["blokker"] / totalt:.0%}"></div></div>'
        f'<div class="fase">Fase: {escape(x["fase"])}'
        + (f' · svake temaer først: {escape(", ".join(x["svake"]))}' if x["svake"] else "") + "</div></div>"
        for x in f["fag"])
    regler = (f"<ul><li>Faget med nærmest eksamen får mest tid. Andelen øker jo færre dager som er igjen.</li>"
              f"<li>De siste {f['repetisjonsdager']} dagene før en eksamen brukes bare på det faget.</li>"
              f"<li>Øvingen endrer seg mot eksamen: først gjenkjenne (flashcards), så hente frem (flervalg), "
              f"siste uke forklare med egne ord (kortsvar).</li>"
              f"<li>Temaer du ikke har øvd på eller er svak på, kommer oftere. Temaer du nettopp har øvd på, venter litt.</li>"
              f"<li>Når du trykker «Ferdig», legges planen på nytt fra i morgen ut fra mestringen din.</li></ul>")
    return (f'<div class="planforklaring"><h3>De neste {f["dager"]} dagene · {f["blokker"]} blokker à '
            f'{f["blokk_minutter"]} min</h3>{rader}<h4>Slik er planen laget</h4>{regler}'
            f'<h4>Oppsummering</h4><p>{oppsummering}</p></div>')


def forklar_plan():
    from src.planlegger import forklar, planfakta
    db = koble()
    f = planfakta(db)
    yield _forklaring_html(f, "<i>Språkmodellen skriver en oppsummering …</i>")
    try:
        tekst = escape(forklar(db))
    except Exception:   # tidsavbrudd eller Ollama ikke startet: tallene over står uansett
        tekst = "<i>Språkmodellen svarte ikke. Tallene over er likevel riktige.</i>"
    yield _forklaring_html(f, tekst)


# ---------- Mestring ----------

def vis_mestring():
    db = koble()
    _, temaer, _ = last_eksamener()
    lagret = {(r["fag"], r["tema"]): r for r in db.execute("SELECT * FROM temaer")}
    kort = sum(1 for fag in FAG for k in forfalte(db, fag, None) if k["neste"])
    fliser = [f'<div class="flis" style="--fag:#e5484d"><div class="tall">{len(forfalte_sporsmal(db))}</div>'
              f'<div class="tekst">feilsvar venter</div></div>',
              f'<div class="flis" style="--fag:#3b82f6"><div class="tall">{kort}</div>'
              f'<div class="tekst">flashcards forfalt</div></div>']
    seksjoner = []
    for fag in [f for f in FAG if f in temaer]:
        rader, ovde = [], []
        egne = [t for (f, t) in lagret if f == fag and t not in temaer[fag]]   # temaer du har skrevet selv i quizen
        for tema in temaer[fag] + egne:
            r = lagret.get((fag, tema))
            if r and r["forsok"]:
                ovde.append(r["mestring"])
                rader.append(f'<div class="temarad"><div>{escape(kort_tema(tema))}</div>'
                             f'<div class="stolpe"><div style="width:{r["mestring"]:.0%}"></div></div>'
                             f'<div class="prosent">{r["mestring"]:.0%}</div>'
                             f'<div class="sist">{r["forsok"]} forsøk · {(r["sist_ovd"] or "")[8:10]}.{(r["sist_ovd"] or "")[5:7]}</div></div>')
            elif tema in temaer[fag]:
                rader.append(f'<div class="temarad uovd"><div>{escape(kort_tema(tema))}</div>'
                             f'<div class="stolpe"></div><div class="prosent">–</div><div class="sist">ikke øvd</div></div>')
        snitt = sum(ovde) / len(ovde) if ovde else None
        fliser.append(f'<div class="flis" style="--fag:{farge(fag)}"><div class="tall">'
                      f'{f"{snitt:.0%}" if snitt is not None else "–"}</div>'
                      f'<div class="tekst">{escape(NAVN.get(fag, fag))} · {len(ovde)} temaer øvd</div></div>')
        seksjoner.append(f'<div class="fagseksjon" style="--fag:{farge(fag)}"><h3>{merke(fag)} {escape(NAVN.get(fag, fag))}</h3>'
                         f'{"".join(rader)}</div>')
    return f'<div class="fliser">{"".join(fliser)}</div>{"".join(seksjoner)}'


# ---------- oppsett ----------

TEMA = gr.themes.Soft(primary_hue="indigo", neutral_hue="slate", radius_size="lg",
                      font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"])
CSS = (Path(__file__).parent / "app.css").read_text(encoding="utf-8")


def lag_app() -> gr.Blocks:
    with gr.Blocks(title="Pensumboten") as app:
        gr.HTML(topp)
        with gr.Tabs() as faner:
            with gr.Tab("📅 I dag", id="idag"):
                plan_overskrift = gr.HTML()
                plan_data = gr.State([])

                @gr.render(inputs=plan_data)
                def tegn_blokker(blokker):
                    if not blokker:
                        gr.HTML(_melding("Ingenting planlagt i dag – fridag eller etter siste eksamen."))
                        return
                    for b in blokker:
                        with gr.Row(elem_classes="blokk-rad"):
                            with gr.Column(scale=8, min_width=240):
                                gr.HTML(_blokk_html(b))
                            if b["status"] == "planlagt":
                                ov = gr.Button("Øv nå", variant="primary", size="sm", scale=0, min_width=84, elem_classes="blokk-knapp")
                                ferdig = gr.Button("✓ Ferdig", size="sm", scale=0, min_width=84, elem_classes="blokk-knapp")
                                ov.click(lambda bid=b["id"]: ov_paa_blokk(bid), None,
                                         [faner, quiz_fag, quiz_tema, quiz_type, quiz_stil, kort_fag, kort_tema])
                                ferdig.click(lambda bid=b["id"]: fullfort(bid), None, plan_ut)

                with gr.Row():
                    hopp_knapp = gr.Button("Hopp over i dag", size="sm")
                    angre_knapp = gr.Button("↩ Angre hopp over", size="sm")
                    forklar_knapp = gr.Button("💡 Forklar planen", size="sm")
                forklaring = gr.HTML()
                gr.Markdown("#### Neste 7 dager")
                uke = gr.HTML()

            with gr.Tab("💬 Spør", id="spor"):
                samtale = gr.State([])
                with gr.Row():
                    spor_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag", scale=1)
                    spor_eksempel = gr.Checkbox(label="Ta med A-besvarelser (ikke fasit)", scale=2)
                chat = gr.Chatbot(height=480, elem_classes="chat", show_label=False,
                                  placeholder="**Spør om hva som helst i pensumet ditt.**<br>"
                                              "Svarene kommer bare fra dine egne filer, med kilde.")
                with gr.Row():
                    spor_tekst = gr.Textbox(placeholder="Hva er en pull-strategi?", show_label=False, scale=6,
                                            container=False)
                    spor_knapp = gr.Button("Send", variant="primary", scale=1, min_width=80)
                tom_knapp = gr.Button("Ny samtale", size="sm")

            with gr.Tab("🎯 Quiz", id="quiz"):
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        quiz_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag")
                        quiz_tema = gr.Textbox(label="Tema", placeholder="prisstrategi")
                        quiz_type = gr.Radio(["flervalg", "kortsvar", "repetisjon"], value="flervalg", label="Type",
                                             scale=2)
                        quiz_stil = gr.Dropdown([*STILER, "blandet"], value="forklar", label="Stil", visible=False)
                poeng = gr.HTML()
                quiz_sporsmal = gr.HTML(_melding("Velg fag og tema, og trykk «Nytt spørsmål»."))
                quiz_valg = gr.Radio(show_label=False, visible=False, elem_classes="svaralternativer")
                quiz_tekst = gr.Textbox(label="Ditt svar (2–4 setninger)", lines=4, visible=False)
                with gr.Row():
                    svar_knapp = gr.Button("Svar", variant="primary")
                    nytt_knapp = gr.Button("Nytt spørsmål ➜")
                quiz_resultat = gr.HTML()

            with gr.Tab("🗂️ Flashcards", id="kort"):
                ko = gr.State([])
                with gr.Group(elem_classes="panel"):
                    with gr.Row():
                        kort_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag")
                        kort_tema = gr.Textbox(label="Tema (tomt = alle kort som skal repeteres)")
                        kort_nye = gr.Number(value=6, precision=0, label="Lag nye kort først")
                hent_knapp = gr.Button("Start", variant="primary")
                flashcard = gr.HTML(_melding("Velg fag og tema, og trykk «Start»."))
                with gr.Row(visible=False) as snu_rad:
                    snu_knapp = gr.Button("Snu kortet", variant="primary", size="lg")
                with gr.Row(visible=False) as vurder_rad:
                    vurderingsknapper = [gr.Button(v, size="lg", elem_classes=f"v-{v}")
                                         for v in ("igjen", "vanskelig", "greit", "lett")]

            with gr.Tab("📈 Mestring", id="mestring"):
                mestring = gr.HTML()
                oppdater_knapp = gr.Button("Oppdater", size="sm")


        plan_ut = [plan_overskrift, plan_data, uke]
        app.load(vis_plan, outputs=plan_ut)
        app.load(vis_mestring, outputs=mestring)
        hopp_knapp.click(hopp_over_i_dag, outputs=plan_ut)
        angre_knapp.click(angre_i_dag, outputs=plan_ut)
        forklar_knapp.click(forklar_plan, outputs=forklaring)

        spor_ut = [chat, samtale, spor_tekst]
        spor_knapp.click(spor, [spor_tekst, samtale, spor_fag, spor_eksempel], spor_ut)
        spor_tekst.submit(spor, [spor_tekst, samtale, spor_fag, spor_eksempel], spor_ut)
        tom_knapp.click(lambda: ([], []), outputs=[chat, samtale])

        nytt_knapp.click(nytt_sporsmal, [quiz_fag, quiz_tema, quiz_type, quiz_stil],
                         [quiz_sporsmal, quiz_valg, quiz_tekst, quiz_resultat, poeng])
        quiz_type.change(lambda t: gr.update(visible=t == "kortsvar"), quiz_type, quiz_stil)
        svar_knapp.click(svar_quiz, [quiz_valg, quiz_tekst], [quiz_resultat, poeng])

        hent_knapp.click(hent_kort, [kort_fag, kort_tema, kort_nye], [ko, flashcard, snu_rad, vurder_rad])
        snu_knapp.click(snu, ko, [flashcard, snu_rad, vurder_rad])
        for knapp in vurderingsknapper:
            knapp.click(vurder_kort, [knapp, ko], [ko, flashcard, snu_rad, vurder_rad])

        oppdater_knapp.click(vis_mestring, outputs=mestring)
    return app


if __name__ == "__main__":
    print("Laster modellene ...")
    hent("oppvarming", fag=standardfag())
    generer("Svar med ett ord.", "Hei")
    lag_app().launch(server_name="127.0.0.1", inbrowser=True, theme=TEMA, css=CSS)
