"""Fase 5: Gradio-grensesnitt i nettleseren. Bruker de samme funksjonene som terminalkommandoene.

Kjører bare på din maskin (127.0.0.1). Ingenting deles på nettet.

Kjør:  uv run python -m src.app      (åpner http://127.0.0.1:7860 i nettleseren)
"""

import json
from datetime import date, timedelta

import gradio as gr

from src.database import koble, lagre_sporsmal
from src.flashcards import forfalte, lag_nye_kort
from src.henting import Bit, hent
from src.innlesing import alle_fag, standardfag
from src.kortsvar import STILER, vurder
from src.llm import generer
from src.planlegger import UKEDAGER, blokker_for, hopp_over, lag_og_lagre, marker_fullfort
from src.quiz import modellnavn, sporsmal_strom
from src.repetisjon import forfalte_sporsmal, lagre_resultat
from src.svar import svar_pa, vis

FAG = alle_fag()
BOKSTAVER = "ABCD"

# Quizøkter per nettleserfane. Generatorer kan ikke ligge i gr.State (den kopierer verdiene),
# så de lagres her med Gradios økt-ID som nøkkel.
OKTER: dict[str, dict] = {}


# ---------- Spør ----------

def spor(sporsmal, fag, eksempelsvar):
    if not sporsmal.strip():
        return "Skriv et spørsmål.", ""
    try:
        s = svar_pa(sporsmal, fag=fag, med_eksempelsvar=eksempelsvar)
    except TimeoutError:
        return "Språkmodellen brukte for lang tid. Prøv igjen.", ""
    kilder = "\n\n---\n\n".join(f"**[{nr}] {b.metadata['fag']}/{b.kilde}**\n\n{b.tekst}"
                                for nr, b in enumerate(s.biter, start=1))
    return vis(s), kilder


# ---------- Quiz ----------

def _repetisjonsstrom(fag):
    """Forfalte feilsvar i samme form som sporsmal_strom: (spørsmål, bit, id)."""
    for s in forfalte_sporsmal(koble(), fag):
        liste = json.loads(s["alternativer"]) if s["alternativer"] else []
        bit = Bit(s["kildetekst"] or s["sitat"] or "", {"fil": s["kilde"]}, 0.0)
        if s["ovingsmate"] == "flervalg":
            q = {"sporsmal": s["sporsmal"], "alternativer": liste, "fasit": s["fasit"], "forklaring": s["forklaring"],
                 "sitat": s["sitat"], "type": "flervalg"}
        else:
            q = {"sporsmal": s["sporsmal"], "nokkelpunkter": liste, "modellsvar": s["fasit"], "fasit": s["fasit"],
                 "sitat": s["sitat"], "type": "kortsvar"}
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
        yield {**q, "type": type_}, bit, sid, kilde


def nytt_sporsmal(fag, tema, type_, stil, request: gr.Request):
    if type_ != "repetisjon" and not tema.strip():
        return "Skriv et tema, f.eks. «prisstrategi».", gr.update(visible=False), gr.update(visible=False), ""
    okt = OKTER.get(request.session_hash)
    nokkel = (fag, tema, type_, stil)
    if not okt or okt["nokkel"] != nokkel:
        okt = OKTER[request.session_hash] = {"nokkel": nokkel, "strom": _ny_strom(fag, tema, type_, stil)}
    try:
        q, bit, sid, kilde = next(okt["strom"])
    except StopIteration:
        okt["nokkel"] = None
        tekst = ("Ingen spørsmål skal repeteres nå." if type_ == "repetisjon"
                 else f"Fant ikke flere gode spørsmål om «{tema}». Prøv et bredere tema.")
        return tekst, gr.update(visible=False), gr.update(visible=False), ""
    okt.update(q=q, bit=bit, sid=sid, kilde=kilde)
    etikett = f"*{q['stil']}* · " if q.get("stil") and q["stil"] != "forklar" else ""
    overskrift = f"### {etikett}{q['sporsmal']}"
    if q["type"] == "flervalg":
        valg = [f"{b}) {a}" for b, a in zip(BOKSTAVER, q["alternativer"])]
        return overskrift, gr.update(choices=valg, value=None, visible=True), gr.update(visible=False), ""
    return overskrift, gr.update(visible=False), gr.update(value="", visible=True), ""


def svar_quiz(valgt, tekst, request: gr.Request):
    okt = OKTER.get(request.session_hash)
    if not okt or "q" not in okt:
        return "Trykk «Nytt spørsmål» først."
    q, bit, sid = okt["q"], okt["bit"], okt["sid"]
    if q["type"] == "flervalg":
        if not valgt:
            return "Velg et alternativ."
        svar = valgt[3:]
        riktig = svar == q["fasit"]
        linjer = ["✅ **Riktig!**" if riktig else f"❌ **Feil.** Riktig svar: {q['fasit']}", "", q.get("forklaring") or ""]
        tilbakemelding = None
    else:
        if len(tekst.split()) < 3:
            return "Skriv et svar på 2–4 setninger."
        svar = tekst
        try:
            v = vurder(q, svar, bit.tekst)
        except (TimeoutError, ValueError):
            return f"Vurderingen feilet. Sammenlign selv med modellsvaret:\n\n{q['modellsvar']}"
        riktig, tilbakemelding = v["riktig"], v["tilbakemelding"]
        linjer = [f"{'✅ **Godkjent**' if riktig else '❌ **Ikke godkjent**'}: "
                  f"{sum(v['dekket'])} av {len(v['dekket'])} nøkkelpunkter", ""]
        linjer += [f"- {'✓' if d else '·'} {p}" for p, d in zip(q["nokkelpunkter"], v["dekket"])]
        linjer += [f"- ✗ Stemmer ikke med kilden: {f}" for f in v["feil"]]
        linjer += ["", v["tilbakemelding"], "", f"**Modellsvar:** {q['modellsvar']}",
                   "", "*Vurderingen er en indikasjon fra en liten modell, ikke en karakter.*"]
    neste = lagre_resultat(koble(), sid, svar, riktig, tilbakemelding)
    linjer += ["", f"Kilde: {okt['kilde']}  «{q.get('sitat') or ''}»",
               f"Kommer igjen {neste:%d.%m} for repetisjon." if neste else ""]
    del okt["q"]
    return "\n".join(linjer)


# ---------- Flashcards ----------

def _kort(kid):
    return koble().execute("SELECT * FROM sporsmal WHERE id = ?", (kid,)).fetchone()


def _forside(ko):
    if not ko:
        return "Ingen kort å øve på nå. Lag nye kort med et tema.", ""
    return f"## {_kort(ko[0])['sporsmal']}\n\n*{len(ko)} kort igjen*", ""


def hent_kort(fag, tema, nye):
    db = koble()
    if nye and tema.strip():
        lag_nye_kort(db, fag, tema, int(nye))
    ko = [k["id"] for k in forfalte(db, fag, tema.strip() or None)]
    return ko, *_forside(ko)


def snu(ko):
    if not ko:
        return ""
    k = _kort(ko[0])
    return f"{k['fasit']}\n\n*Kilde: {k['kilde']}*"


def vurder_kort(vurdering, ko):
    if not ko:
        return ko, *_forside(ko)
    kid = ko.pop(0)
    lagre_resultat(koble(), kid, svar=vurdering, riktig=vurdering in ("greit", "lett"), vurdering=vurdering)
    if vurdering == "igjen":
        ko.append(kid)
    return ko, *_forside(ko)


# ---------- I dag og plan ----------

def _dagens(db):
    return [b for b in blokker_for(db, date.today()) if b["fag"] != "-"]


def vis_plan():
    db = koble()
    if not _dagens(db):
        lag_og_lagre(db)
    dagens = _dagens(db)
    tegn = {"fullfort": "✓", "hoppet_over": "–", "planlagt": ""}
    rader = [[b["id"], tegn[b["status"]], b["fag"], b["ovingsmate"], b["tema"]] for b in dagens]
    valg = [(f"{b['fag']} · {b['ovingsmate']} · {b['tema']}", b["id"]) for b in dagens if b["status"] == "planlagt"]
    uke = []
    for i in range(1, 8):
        dag = date.today() + timedelta(days=i)
        blokker = [b for b in blokker_for(db, dag) if b["fag"] != "-" and b["status"] == "planlagt"]
        if blokker:
            uke.append(f"**{UKEDAGER[dag.weekday()]} {dag:%d.%m}**: "
                       + ", ".join(f"{b['fag']} {b['ovingsmate']} ({b['tema'].split(' (')[0]})" for b in blokker))
    sporsmal = len(forfalte_sporsmal(db))
    overskrift = (f"### I dag, {UKEDAGER[date.today().weekday()]} {date.today():%d.%m}"
                  + (f" · {sporsmal} feilsvar venter på repetisjon" if sporsmal else ""))
    return overskrift, rader, gr.update(choices=valg, value=valg[0][1] if valg else None), "\n\n".join(uke)


def ov_paa_blokk(blokk_id):
    """Fyller ut riktig fane med fag og tema fra blokken, og bytter til den."""
    if not blokk_id:
        return [gr.update()] * 7
    b = koble().execute("SELECT * FROM plan WHERE id = ?", (blokk_id,)).fetchone()
    if b["ovingsmate"] == "flashcards":
        return (gr.Tabs(selected="kort"), gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(value=b["fag"]), gr.update(value=b["tema"]))
    type_ = "flervalg" if b["ovingsmate"] == "flervalg" else "kortsvar"
    stil = "blandet" if type_ == "kortsvar" else "forklar"
    return (gr.Tabs(selected="quiz"), gr.update(value=b["fag"]), gr.update(value=b["tema"]),
            gr.update(value=type_), gr.update(value=stil), gr.update(), gr.update())


def fullfort(blokk_id):
    if blokk_id:
        db = koble()
        marker_fullfort(db, blokk_id)
        lag_og_lagre(db, date.today() + timedelta(days=1))   # mestringen fra økten styrer resten
    return vis_plan()


def hopp_over_i_dag():
    hopp_over(koble(), date.today())
    return vis_plan()


def forklar_plan():
    from src.planlegger import forklar
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        forklar(koble())
    return buffer.getvalue()


# ---------- Mestring ----------

def vis_mestring():
    db = koble()
    rader = [[r["fag"], f"{r['mestring']:.0%}", r["forsok"], (r["sist_ovd"] or "")[:10], r["tema"]]
             for r in db.execute("SELECT * FROM temaer ORDER BY fag, mestring")]
    kort = sum(1 for fag in FAG for k in forfalte(db, fag, None) if k["neste"])
    info = f"{len(forfalte_sporsmal(db))} feilsvar og {kort} flashcards venter på repetisjon."
    return rader, info


# ---------- oppsett ----------

def lag_app() -> gr.Blocks:
    with gr.Blocks(title="Pensumboten") as app:
        gr.Markdown("# Pensumboten")
        with gr.Tabs() as faner:
            with gr.Tab("I dag", id="idag"):
                plan_overskrift = gr.Markdown()
                plan_tabell = gr.Dataframe(headers=["id", "", "fag", "øving", "tema"], interactive=False)
                with gr.Row():
                    blokkvalg = gr.Dropdown(label="Blokk", scale=3)
                    ov_knapp = gr.Button("Øv på denne", variant="primary")
                    ferdig_knapp = gr.Button("Marker fullført")
                with gr.Row():
                    hopp_knapp = gr.Button("Hopp over i dag")
                    forklar_knapp = gr.Button("Forklar planen")
                forklaring = gr.Markdown()
                gr.Markdown("#### Neste 7 dager")
                uke = gr.Markdown()

            with gr.Tab("Spør", id="spor"):
                with gr.Row():
                    spor_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag")
                    spor_eksempel = gr.Checkbox(label="Ta med A-besvarelser (ikke fasit)")
                spor_tekst = gr.Textbox(label="Spørsmål", placeholder="Hva er en pull-strategi?")
                spor_knapp = gr.Button("Spør", variant="primary")
                spor_svar = gr.Markdown()
                with gr.Accordion("Kildetekstene", open=False):
                    spor_kilder = gr.Markdown()

            with gr.Tab("Quiz", id="quiz"):
                with gr.Row():
                    quiz_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag")
                    quiz_tema = gr.Textbox(label="Tema", placeholder="prisstrategi")
                    quiz_type = gr.Radio(["flervalg", "kortsvar", "repetisjon"], value="flervalg", label="Type")
                    quiz_stil = gr.Dropdown([*STILER, "blandet"], value="forklar", label="Stil (kortsvar)")
                nytt_knapp = gr.Button("Nytt spørsmål", variant="primary")
                quiz_sporsmal = gr.Markdown()
                quiz_valg = gr.Radio(label="Ditt svar", visible=False)
                quiz_tekst = gr.Textbox(label="Ditt svar (2–4 setninger)", lines=4, visible=False)
                svar_knapp = gr.Button("Svar")
                quiz_resultat = gr.Markdown()

            with gr.Tab("Flashcards", id="kort"):
                ko = gr.State([])
                with gr.Row():
                    kort_fag = gr.Dropdown(FAG, value=standardfag(), label="Fag")
                    kort_tema = gr.Textbox(label="Tema (tomt = alle kort som skal repeteres)")
                    kort_nye = gr.Number(value=6, precision=0, label="Lag nye kort først")
                hent_knapp = gr.Button("Start", variant="primary")
                forside = gr.Markdown()
                snu_knapp = gr.Button("Snu kortet")
                bakside = gr.Markdown()
                with gr.Row():
                    vurderingsknapper = [gr.Button(v) for v in ("igjen", "vanskelig", "greit", "lett")]

            with gr.Tab("Mestring", id="mestring"):
                mestring_info = gr.Markdown()
                mestring_tabell = gr.Dataframe(headers=["fag", "mestring", "forsøk", "sist øvd", "tema"],
                                               interactive=False)
                oppdater_knapp = gr.Button("Oppdater")

        plan_ut = [plan_overskrift, plan_tabell, blokkvalg, uke]
        app.load(vis_plan, outputs=plan_ut)
        app.load(vis_mestring, outputs=[mestring_tabell, mestring_info])
        ov_knapp.click(ov_paa_blokk, blokkvalg, [faner, quiz_fag, quiz_tema, quiz_type, quiz_stil, kort_fag, kort_tema])
        ferdig_knapp.click(fullfort, blokkvalg, plan_ut)
        hopp_knapp.click(hopp_over_i_dag, outputs=plan_ut)
        forklar_knapp.click(forklar_plan, outputs=forklaring)

        spor_knapp.click(spor, [spor_tekst, spor_fag, spor_eksempel], [spor_svar, spor_kilder])
        spor_tekst.submit(spor, [spor_tekst, spor_fag, spor_eksempel], [spor_svar, spor_kilder])

        nytt_knapp.click(nytt_sporsmal, [quiz_fag, quiz_tema, quiz_type, quiz_stil],
                         [quiz_sporsmal, quiz_valg, quiz_tekst, quiz_resultat])
        svar_knapp.click(svar_quiz, [quiz_valg, quiz_tekst], quiz_resultat)

        hent_knapp.click(hent_kort, [kort_fag, kort_tema, kort_nye], [ko, forside, bakside])
        snu_knapp.click(snu, ko, bakside)
        for knapp in vurderingsknapper:
            knapp.click(vurder_kort, [knapp, ko], [ko, forside, bakside])

        oppdater_knapp.click(vis_mestring, outputs=[mestring_tabell, mestring_info])
    return app


if __name__ == "__main__":
    print("Laster modellene ...")
    hent("oppvarming", fag=standardfag())
    generer("Svar med ett ord.", "Hei")
    lag_app().launch(server_name="127.0.0.1", inbrowser=True, theme=gr.themes.Soft())
