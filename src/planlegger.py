"""Fase 3: eksamensplanleggeren. Lager en plan dag for dag frem til hver eksamen.

Alt regnes ut i Python, ikke av språkmodellen, slik at timer og datoer alltid stemmer.
Språkmodellen brukes bare til å forklare planen (--forklar).

Regler:
- Hver dag deles i blokker (blokk_minutter). Summen blir aldri mer enn timer_per_dag.
- Tiden fordeles mellom fagene omvendt proporsjonalt med dager igjen til eksamen.
- De siste repetisjonsdager før en eksamen brukes bare på det faget.
- Innenfor et fag velges temaene som er lengst siden du øvde på, vektet med mestring
  (lav mestring = oftere). Temaer du aldri har øvd på kommer først.
- Øvingsmåten følger hvor nær eksamen er: flashcards → flervalg → kortsvar → repetisjon.
- Ingen blokk for et fag på eller etter eksamensdagen.

Kjør:  uv run python -m src.planlegger --lag            (lag planen på nytt fra i dag)
       uv run python -m src.planlegger --vis --dager 7
       uv run python -m src.planlegger --hopp-over       (i dag går ikke; resten fordeles på nytt)
       uv run python -m src.planlegger --forklar
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import yaml

from src.database import koble
from src.konfig import ROT


@dataclass
class Blokk:
    dato: date
    fag: str
    tema: str
    ovingsmate: str
    minutter: int


def last_eksamener() -> tuple[dict, dict, dict]:
    """Returnerer (eksamensdatoer, temaer per fag, innstillinger). Fag uten dato eller temaer hoppes over."""
    with open(ROT / "config" / "eksamener.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    innst = {n: data[n] for n in ("timer_per_dag", "blokk_minutter", "repetisjonsdager")}
    datoer, temaer = {}, {}
    for fag, verdi in data.items():
        if isinstance(verdi, dict) and isinstance(verdi.get("dato"), date) and verdi.get("temaer"):
            datoer[fag] = verdi["dato"]
            temaer[fag] = list(verdi["temaer"])
    return datoer, temaer, innst


def ovingsmate_for(dager_igjen: int, repetisjonsdager: int, gang: int = 0) -> str:
    """Gjenkjenne tidlig, hente frem og forklare senere, blandet repetisjon helt til slutt (SPEC.md).

    gang: hvor mange ganger temaet er planlagt før. Tidlig veksler vi mellom flashcards og
    flervalg, så det ikke blir uker med bare flashcards for fag med eksamen langt frem.
    """
    if dager_igjen <= repetisjonsdager:
        return "repetisjon"
    if dager_igjen <= 7:
        return "kortsvar"
    if dager_igjen <= 21:
        return "flervalg"
    return "flashcards" if gang % 2 == 0 else "flervalg"


def fordel_heltall(andeler: dict[str, float], antall: int) -> dict[str, int]:
    """Gjør andeler om til et helt antall blokker som summerer til `antall` (største rest-metoden)."""
    raa = {k: v * antall for k, v in andeler.items()}
    hele = {k: int(v) for k, v in raa.items()}
    rest = antall - sum(hele.values())
    for k in sorted(raa, key=lambda k: raa[k] - hele[k], reverse=True)[:rest]:
        hele[k] += 1
    return hele


def lag_plan(eksamener: dict[str, date], temaer: dict[str, list[str]], start: date,
             timer_per_dag: float, blokk_minutter: int, repetisjonsdager: int,
             mestring: dict | None = None, sist_ovd: dict | None = None,
             hoppes_over: set[date] = frozenset()) -> list[Blokk]:
    """Ren funksjon: samme input gir alltid samme plan. Ingen database, så den kan testes direkte.

    mestring:  {(fag, tema): 0–1}, standard 0,5
    sist_ovd:  {(fag, tema): dato} for temaer du allerede har øvd på
    hoppes_over: datoer det ikke skal planlegges noe på
    """
    mestring = mestring or {}
    sist = dict(sist_ovd or {})
    ganger = Counter()          # hvor mange ganger hvert tema er planlagt så langt
    blokker_per_dag = int(timer_per_dag * 60 // blokk_minutter)
    plan = []

    dag = start
    while dag < max(eksamener.values(), default=start):
        aktive = {f: (eksamener[f] - dag).days for f in eksamener if eksamener[f] > dag and temaer.get(f)}
        if dag in hoppes_over or not aktive or blokker_per_dag == 0:
            dag += timedelta(days=1)
            continue

        i_repetisjon = [f for f, d in aktive.items() if d <= repetisjonsdager]
        if i_repetisjon:
            andeler = {f: 1 / len(i_repetisjon) for f in i_repetisjon}
        else:
            totalt = sum(1 / d for d in aktive.values())
            andeler = {f: (1 / d) / totalt for f, d in aktive.items()}

        for fag, antall in fordel_heltall(andeler, blokker_per_dag).items():
            for _ in range(antall):
                tema = _neste_tema(fag, temaer[fag], dag, sist, mestring)
                modus = ovingsmate_for(aktive[fag], repetisjonsdager, ganger[(fag, tema)])
                plan.append(Blokk(dag, fag, tema, modus, blokk_minutter))
                sist[(fag, tema)] = dag
                ganger[(fag, tema)] += 1
        dag += timedelta(days=1)
    return plan


def _neste_tema(fag, temaliste, dag, sist, mestring) -> str:
    """Temaet med høyest prioritet: lenge siden sist × hvor svak du er. Aldri øvd = først."""
    def prioritet(tema):
        dager = (dag - sist[(fag, tema)]).days if (fag, tema) in sist else 10_000
        return dager * (1.5 - mestring.get((fag, tema), 0.5))
    return max(temaliste, key=prioritet)    # ved likhet vinner den første i listen


def sjekk_plan(plan: list[Blokk], eksamener: dict, temaer: dict, timer_per_dag: float) -> list[str]:
    """Kontroller reglene SPEC.md krever. Tom liste = alt i orden."""
    problemer = []
    per_dag = defaultdict(int)
    for b in plan:
        per_dag[b.dato] += b.minutter
        if b.dato >= eksamener[b.fag]:
            problemer.append(f"{b.dato}: {b.fag} er planlagt på eller etter eksamensdagen")
    for dag, minutter in per_dag.items():
        if minutter > timer_per_dag * 60:
            problemer.append(f"{dag}: {minutter} minutter planlagt, mer enn {timer_per_dag} timer")
    dekket = {(b.fag, b.tema) for b in plan}
    for fag, liste in temaer.items():
        mangler = [t for t in liste if (fag, t) not in dekket]
        if mangler and any(b.fag == fag for b in plan):
            problemer.append(f"{fag}: {len(mangler)} temaer får ingen blokk før eksamen")
    return problemer


# ---------- database: lagre, hente og endre planen ----------

def mestring_fra_quiz(db) -> dict:
    """Andel riktige på de siste 10 forsøkene per (fag, tema). Fase 4 gjør dette mer avansert."""
    forsok = defaultdict(list)
    for r in db.execute("SELECT s.fag, s.tema, f.riktig FROM forsok f JOIN sporsmal s ON s.id = f.sporsmal_id"
                        " ORDER BY f.id"):
        forsok[(r["fag"], r["tema"])].append(r["riktig"])
    return {k: sum(v[-10:]) / len(v[-10:]) for k, v in forsok.items()}


def lag_og_lagre(db, start: date | None = None) -> tuple[list[Blokk], list[str]]:
    """Lager planen på nytt fra `start` (i dag). Fullførte og hoppet-over-blokker beholdes."""
    start = start or date.today()
    eksamener, temaer, innst = last_eksamener()
    sist_ovd = {(r["fag"], r["tema"]): date.fromisoformat(r["sist"]) for r in db.execute(
        "SELECT fag, tema, MAX(dato) AS sist FROM plan WHERE status = 'fullfort' GROUP BY fag, tema")}
    hoppes_over = {date.fromisoformat(r["dato"]) for r in db.execute(
        "SELECT DISTINCT dato FROM plan WHERE status = 'hoppet_over' AND dato >= ?", (start.isoformat(),))}
    plan = lag_plan(eksamener, temaer, start, innst["timer_per_dag"], innst["blokk_minutter"],
                    innst["repetisjonsdager"], mestring_fra_quiz(db), sist_ovd, hoppes_over)

    db.execute("DELETE FROM plan WHERE status = 'planlagt' AND dato >= ?", (start.isoformat(),))
    db.executemany("INSERT INTO plan (dato, fag, tema, ovingsmate, minutter, status) VALUES (?, ?, ?, ?, ?, 'planlagt')",
                   [(b.dato.isoformat(), b.fag, b.tema, b.ovingsmate, b.minutter) for b in plan])
    db.commit()
    return plan, sjekk_plan(plan, eksamener, temaer, innst["timer_per_dag"])


def blokker_for(db, dato: date):
    return db.execute("SELECT * FROM plan WHERE dato = ? ORDER BY fag, id", (dato.isoformat(),)).fetchall()


def hopp_over(db, dato: date):
    """Markerer dagen som hoppet over og fordeler resten på nytt fra i dag."""
    db.execute("UPDATE plan SET status = 'hoppet_over' WHERE dato = ? AND status = 'planlagt'", (dato.isoformat(),))
    if not blokker_for(db, dato):      # dag uten plan: legg inn en markør så den ikke planlegges senere
        db.execute("INSERT INTO plan (dato, fag, tema, ovingsmate, minutter, status) VALUES (?, '-', '-', '-', 0, 'hoppet_over')",
                   (dato.isoformat(),))
    db.commit()
    # Planlegg på nytt fra i dag. Den hoppede dagen er nå merket, så den får ingen nye blokker.
    return lag_og_lagre(db, date.today())


def marker_fullfort(db, blokk_id: int):
    db.execute("UPDATE plan SET status = 'fullfort' WHERE id = ?", (blokk_id,))
    db.commit()


UKEDAGER = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]


def skriv_dager(db, fra: date, dager: int):
    for i in range(dager):
        dag = fra + timedelta(days=i)
        rader = [r for r in blokker_for(db, dag) if r["fag"] != "-"]
        if not rader:
            continue
        status = Counter(r["status"] for r in rader)
        merke = " (hoppet over)" if status.get("hoppet_over") == len(rader) else ""
        timer = sum(r["minutter"] for r in rader if r["status"] != "hoppet_over") / 60
        print(f"\n{UKEDAGER[dag.weekday()]} {dag:%d.%m}{merke}  {timer:.1f} t")
        for r in rader:
            tegn = {"fullfort": "✓", "hoppet_over": "–"}.get(r["status"], "·")
            print(f"  {tegn} {r['fag']}  {r['ovingsmate']:<10} {r['tema']}")


def oppsummer(plan: list[Blokk]):
    eksamener, temaer, _ = last_eksamener()
    print(f"Plan fra {plan[0].dato:%d.%m} til {plan[-1].dato:%d.%m.%Y}, {len(plan)} blokker.")
    for fag, eksamen in sorted(eksamener.items(), key=lambda x: x[1]):
        fagblokker = [b for b in plan if b.fag == fag]
        dekning = Counter(b.tema for b in fagblokker)
        print(f"  {fag} (eksamen {eksamen:%d.%m}): {sum(b.minutter for b in fagblokker) / 60:.0f} timer, "
              f"hvert tema {min(dekning.values(), default=0)}–{max(dekning.values(), default=0)} ganger")


def forklar(db):
    """Språkmodellen forklarer planen. Tallene kommer fra Python, ikke fra modellen."""
    from src.llm import generer

    eksamener, _, innst = last_eksamener()
    neste = [r for i in range(7) for r in blokker_for(db, date.today() + timedelta(days=i))
             if r["status"] == "planlagt"]
    per_fag = Counter(r["fag"] for r in neste)
    fakta = (f"I dag er {date.today():%d.%m.%Y}. Eksamener: "
             + ", ".join(f"{f} {d:%d.%m.%Y} ({(d - date.today()).days} dager)" for f, d in eksamener.items())
             + f". Timer per dag: {innst['timer_per_dag']}. Neste 7 dager, blokker per fag: {dict(per_fag)}. "
             + "Øvingsmåter neste 7 dager: " + str(dict(Counter(r["ovingsmate"] for r in neste))) + ".")
    print(generer("Forklar en studieplan for en student på norsk, kort og konkret (maks 6 setninger). "
                  "Bruk bare tallene du får. Ikke regn ut noe nytt.", fakta))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eksamensplanleggeren.")
    parser.add_argument("--lag", action="store_true", help="lag planen på nytt fra i dag")
    parser.add_argument("--vis", action="store_true", help="vis planen")
    parser.add_argument("--dager", type=int, default=7, help="antall dager som vises med --vis")
    parser.add_argument("--hopp-over", nargs="?", const=date.today().isoformat(), metavar="ÅÅÅÅ-MM-DD",
                        help="marker en dag som hoppet over (standard i dag) og fordel resten på nytt")
    parser.add_argument("--forklar", action="store_true", help="la språkmodellen forklare de neste 7 dagene")
    args = parser.parse_args()
    db = koble()

    if args.lag:
        plan, problemer = lag_og_lagre(db)
        oppsummer(plan)
        print("\n".join(problemer) if problemer else "Kontroll: ingen dag over timegrensen, ingen blokk etter eksamen.")
    if args.hopp_over:
        dag = date.fromisoformat(args.hopp_over)
        plan, problemer = hopp_over(db, dag)
        print(f"{dag:%d.%m} er markert som hoppet over. Resten er fordelt på nytt.")
        oppsummer(plan)
        if problemer:
            print("\n".join(problemer))
    if args.vis:
        skriv_dager(db, date.today(), args.dager)
    if args.forklar:
        forklar(db)
    if not (args.lag or args.vis or args.hopp_over or args.forklar):
        parser.print_help()
