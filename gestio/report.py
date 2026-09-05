"""Raport HTML de sine statator: stoc, vanzari, creante, consumuri, contabilitate.

Fisierul generat nu depinde de nimic din exterior in afara fonturilor, asa ca se
poate deschide pe telefon, trimite pe mail sau atasa la o discutie cu contabilul.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from . import config
from .db import get_conn, rows
from .money import bani_to_ron
from .tools import books, clients, inventory

LUNI = ("ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec")


def _t(tool, **kwargs) -> dict[str, Any]:
    return json.loads(tool(**kwargs))


def collect(year: int | None = None) -> dict[str, Any]:
    """Aduna toate cifrele raportului dintr-un singur an calendaristic."""
    year = year or date.today().year
    start, end = f"{year}-01-01", f"{year}-12-31"
    conn = get_conn()

    lunar = rows(
        conn.execute(
            "SELECT substr(issue_date, 6, 2) AS luna, SUM(net_bani) AS net,"
            " SUM(cogs_bani) AS cost, COUNT(*) AS n FROM invoices"
            " WHERE status IN ('emisa','partial','achitata') AND issue_date BETWEEN ? AND ?"
            " GROUP BY luna ORDER BY luna",
            (start, end),
        )
    )
    vanzari_lunar = [{"luna": LUNI[i], "net": 0, "cost": 0, "facturi": 0} for i in range(12)]
    for row in lunar:
        index = int(row["luna"]) - 1
        vanzari_lunar[index] = {
            "luna": LUNI[index],
            "net": bani_to_ron(int(row["net"])),
            "cost": bani_to_ron(int(row["cost"])),
            "facturi": int(row["n"]),
        }

    top_clienti = rows(
        conn.execute(
            "SELECT c.name AS client, SUM(i.net_bani) AS net, COUNT(*) AS n FROM invoices i"
            " JOIN clients c ON c.id = i.client_id"
            " WHERE i.status IN ('emisa','partial','achitata') AND i.issue_date BETWEEN ? AND ?"
            " GROUP BY c.id ORDER BY net DESC LIMIT 8",
            (start, end),
        )
    )

    return {
        "an": year,
        "firma": config.COMPANY_NAME,
        "moneda": config.CURRENCY,
        "generat": date.today().isoformat(),
        "situatie": _t(books.situatie_generala, date_from=start, date_to=end),
        "pnl": _t(books.cont_profit_pierdere, date_from=start, date_to=end),
        "tva": _t(books.decont_tva, date_from=start, date_to=end),
        "scadente": _t(clients.raport_scadente),
        "stoc": _t(inventory.raport_stoc),
        "consumuri": _t(inventory.raport_consumuri, date_from=start, date_to=end),
        "vanzari_lunar": vanzari_lunar,
        "top_clienti": [
            {"client": r["client"], "net": bani_to_ron(int(r["net"])), "facturi": int(r["n"])}
            for r in top_clienti
        ],
    }


# --- randare ---------------------------------------------------------------


def lei(value: float, decimals: int = 2) -> str:
    """Formateaza romaneste: 12345.6 -> '12.345,60'."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def compact(value: float) -> str:
    """Cifra scurta pentru etichetele graficelor: 12.345 -> '12,3 mii'."""
    if abs(value) >= 1_000_000:
        return f"{lei(value / 1_000_000, 1)} mil."
    if abs(value) >= 1000:
        return f"{lei(value / 1000, 1)} mii"
    return lei(value, 0)


def _bars_vertical(serie: list[dict], moneda: str) -> str:
    """Vanzarile lunare: o singura serie, deci fara legenda - titlul o numeste."""
    values = [item["net"] for item in serie]
    top = max(values) or 1
    width, height = 720, 240
    left, bottom, right, top_pad = 58, 34, 8, 26
    plot_w = width - left - right
    plot_h = height - bottom - top_pad
    slot = plot_w / len(serie)
    bar_w = min(38, slot - 10)
    peak = values.index(top) if top in values else -1

    parts = []
    for index in range(5):
        y = top_pad + plot_h - plot_h * index / 4
        parts.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" />'
        )
    for fraction in (0, 0.5, 1):
        y = top_pad + plot_h - plot_h * fraction
        parts.append(
            f'<text class="axis" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">'
            f"{compact(top * fraction)}</text>"
        )
    for index, item in enumerate(serie):
        value = item["net"]
        x = left + slot * index + (slot - bar_w) / 2
        bar_h = plot_h * value / top if value else 0
        y = top_pad + plot_h - bar_h
        radius = min(4, bar_h)
        if bar_h > 0:
            path = (
                f"M{x:.1f},{top_pad + plot_h:.1f} V{y + radius:.1f}"
                f" a{radius},{radius} 0 0 1 {radius},-{radius}"
                f" h{bar_w - 2 * radius:.1f}"
                f" a{radius},{radius} 0 0 1 {radius},{radius}"
                f" V{top_pad + plot_h:.1f} Z"
            )
            klass = "bar bar-peak" if index == peak else "bar"
            parts.append(
                f'<path class="{klass}" d="{path}">'
                f"<title>{item['luna']}: {lei(value)} {moneda} din {item['facturi']} facturi</title>"
                "</path>"
            )
        if index == peak and value:
            parts.append(
                f'<text class="mark-label" x="{x + bar_w / 2:.1f}" y="{y - 7:.1f}"'
                f' text-anchor="middle">{compact(value)}</text>'
            )
        parts.append(
            f'<text class="axis" x="{x + bar_w / 2:.1f}" y="{height - 12}"'
            f' text-anchor="middle">{item["luna"]}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img"'
        f' aria-label="Vanzari nete pe luni, in {moneda}">{"".join(parts)}</svg>'
    )


def _bars_horizontal(items: list[tuple[str, float]], moneda: str, ramp: bool = False) -> str:
    """Bare orizontale cu eticheta si valoarea direct pe bara."""
    if not items:
        return '<p class="empty">Nimic de aratat aici.</p>'
    top = max(value for _, value in items) or 1
    row_h, gap = 34, 8
    width = 720
    label_w, value_w = 190, 110
    track = width - label_w - value_w
    height = len(items) * (row_h + gap)

    parts = []
    for index, (label, value) in enumerate(items):
        y = index * (row_h + gap)
        bar_w = max(3, track * value / top) if value else 0
        klass = f"bar seq-{min(index + 1, 5)}" if ramp else "bar"
        parts.append(
            f'<text class="row-label" x="0" y="{y + row_h / 2 + 5:.0f}">{escape(label)}</text>'
        )
        parts.append(
            f'<rect class="{klass}" x="{label_w}" y="{y + 6}" width="{bar_w:.1f}"'
            f' height="{row_h - 12}" rx="4"><title>{escape(label)}:'
            f" {lei(value)} {moneda}</title></rect>"
        )
        parts.append(
            f'<text class="row-value" x="{width}" y="{y + row_h / 2 + 5:.0f}"'
            f' text-anchor="end">{lei(value)}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img"'
        f' aria-label="Valori pe categorii, in {moneda}">{"".join(parts)}</svg>'
    )


def _tile(label: str, value: str, sub: str, tone: str = "") -> str:
    tone_class = f" tile-{tone}" if tone else ""
    return (
        f'<div class="tile{tone_class}"><p class="tile-label">{escape(label)}</p>'
        f'<p class="tile-value">{value}</p><p class="tile-sub">{escape(sub)}</p></div>'
    )


def _table(headers: list[str], body: list[list[str]], numeric_from: int = 1) -> str:
    if not body:
        return '<p class="empty">Nimic de aratat aici.</p>'
    head = "".join(
        f'<th class="{"num" if i >= numeric_from else ""}">{escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    lines = []
    for row in body:
        cells = "".join(
            f'<td class="{"num" if i >= numeric_from else ""}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        lines.append(f"<tr>{cells}</tr>")
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(lines)}</tbody></table></div>'
    )


STYLE = """
:root {
  --ground:#EEF1F5; --surface:#FFFFFF; --surface-2:#F6F8FA;
  --ink:#131A22; --ink-2:#4A5765; --ink-3:#77838F; --rule:#D9DFE7;
  --accent:#1F3A5F; --accent-soft:#E3E9F2;
  --good:#1B6F4A; --warn:#8F5A12; --bad:#9C2A26;
  --seq-1:#B8C7DC; --seq-2:#8FA6C6; --seq-3:#6685AF; --seq-4:#3F6396; --seq-5:#1F3A5F;
  --shadow:0 1px 2px rgba(19,26,34,.06), 0 8px 24px -18px rgba(19,26,34,.5);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0E1319; --surface:#161D25; --surface-2:#1C242D;
    --ink:#E6ECF3; --ink-2:#A6B2BF; --ink-3:#7C8894; --rule:#28323C;
    --accent:#8FB2E0; --accent-soft:#22303F;
    --good:#59BE8E; --warn:#D9A24A; --bad:#E58179;
    --seq-1:#2E3F53; --seq-2:#3F5878; --seq-3:#54749B; --seq-4:#6E93BE; --seq-5:#8FB2E0;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -20px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"] {
  --ground:#0E1319; --surface:#161D25; --surface-2:#1C242D;
  --ink:#E6ECF3; --ink-2:#A6B2BF; --ink-3:#7C8894; --rule:#28323C;
  --accent:#8FB2E0; --accent-soft:#22303F;
  --good:#59BE8E; --warn:#D9A24A; --bad:#E58179;
  --seq-1:#2E3F53; --seq-2:#3F5878; --seq-3:#54749B; --seq-4:#6E93BE; --seq-5:#8FB2E0;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 28px -20px rgba(0,0,0,.9);
}

* { box-sizing:border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  font-size:15px; line-height:1.55; -webkit-text-size-adjust:100%;
}
.page { max-width:1080px; margin:0 auto; padding:28px 18px 72px; }

header.masthead { display:flex; flex-wrap:wrap; gap:14px 24px; align-items:baseline;
  padding-bottom:18px; border-bottom:2px solid var(--ink); margin-bottom:26px; }
.masthead h1 { font-family:"IBM Plex Serif", Georgia, serif; font-weight:600;
  font-size:clamp(24px,5vw,34px); line-height:1.15; margin:0; text-wrap:balance; }
.masthead .meta { margin:0; color:var(--ink-2); font-size:13px;
  font-family:"IBM Plex Mono", ui-monospace, monospace; }
.masthead .spacer { flex:1 1 auto; }

section { margin-top:34px; }
.eyebrow { font-size:11px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600; margin:0 0 4px; }
h2 { font-family:"IBM Plex Serif", Georgia, serif; font-size:20px; font-weight:600;
  margin:0 0 14px; text-wrap:balance; }
h3 { font-size:13px; font-weight:600; color:var(--ink-2); margin:22px 0 8px; }
p.note { color:var(--ink-2); font-size:13px; margin:10px 0 0; }
.empty { color:var(--ink-3); font-size:13px; font-style:italic; margin:6px 0; }

.tiles { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); }
.tile { background:var(--surface); border:1px solid var(--rule); border-radius:10px;
  padding:14px 15px; box-shadow:var(--shadow); }
.tile-label { margin:0; font-size:11px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600; }
.tile-value { margin:6px 0 2px; font-family:"IBM Plex Mono", ui-monospace, monospace;
  font-size:clamp(20px,4.4vw,26px); font-weight:600; font-variant-numeric:tabular-nums;
  letter-spacing:-.01em; }
.tile-sub { margin:0; font-size:12px; color:var(--ink-2); }
.tile-good .tile-value { color:var(--good); }
.tile-bad .tile-value { color:var(--bad); }
.tile-warn .tile-value { color:var(--warn); }

.panel { background:var(--surface); border:1px solid var(--rule); border-radius:10px;
  padding:16px 16px 8px; box-shadow:var(--shadow); }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:13.5px; min-width:440px; }
th, td { padding:8px 10px; border-bottom:1px solid var(--rule); text-align:left;
  vertical-align:baseline; }
th { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3);
  font-weight:600; white-space:nowrap; }
td.num, th.num { text-align:right; font-family:"IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric:tabular-nums; white-space:nowrap; }
tbody tr:last-child td { border-bottom:none; }
tfoot td { font-weight:600; border-top:2px solid var(--ink); }

.pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px;
  font-weight:600; letter-spacing:.02em; border:1px solid currentColor; white-space:nowrap; }
.pill-good { color:var(--good); }
.pill-warn { color:var(--warn); }
.pill-bad { color:var(--bad); }
.pill-mut { color:var(--ink-3); }

svg { width:100%; height:auto; display:block; }
.grid { stroke:var(--rule); stroke-width:1; }
.bar { fill:var(--seq-4); }
.bar-peak { fill:var(--accent); }
.seq-1 { fill:var(--seq-1); } .seq-2 { fill:var(--seq-2); } .seq-3 { fill:var(--seq-3); }
.seq-4 { fill:var(--seq-4); } .seq-5 { fill:var(--seq-5); }
text { font-family:"IBM Plex Sans", system-ui, sans-serif; }
.axis { fill:var(--ink-3); font-size:12px; }
.mark-label, .row-value { fill:var(--ink); font-size:12.5px; font-weight:600;
  font-family:"IBM Plex Mono", ui-monospace, monospace; }
.row-label { fill:var(--ink-2); font-size:13px; }

.banner { margin:0 0 22px; padding:10px 14px; border-radius:8px; font-size:13px;
  font-weight:600; color:var(--warn); background:var(--surface);
  border:1px solid currentColor; }
footer { margin-top:42px; padding-top:16px; border-top:1px solid var(--rule);
  color:var(--ink-3); font-size:12px; }
@media (max-width:560px) {
  .page { padding:20px 13px 56px; }
  .panel { padding:13px 11px 6px; }
  table { min-width:0; font-size:12.5px; }
  th, td { padding:7px 5px; }
  th { font-size:10px; letter-spacing:.05em; white-space:normal; }
  .pill { padding:1px 6px; font-size:10px; }
}
@media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; } }
"""


def render(data: dict[str, Any], nota: str | None = None) -> str:
    """Construieste pagina HTML din cifrele adunate de `collect`.

    `nota` apare ca banda marcata sub antet - pentru un raport in lucru sau
    pentru un exemplu care nu trebuie confundat cu cifrele reale.
    """
    moneda = data["moneda"]
    situatie = data["situatie"]
    pnl = data["pnl"]
    tva = data["tva"]
    stoc = data["stoc"]
    consum = data["consumuri"]
    scadente = data["scadente"]
    vanzari = situatie["vanzari"]

    rezultat = pnl["rezultat_ron"]
    restante = situatie["facturi_restante"]

    tiles = "".join(
        [
            _tile("Cifra de afaceri", lei(vanzari["cifra_afaceri_ron"]),
                  f"{vanzari['numar_facturi']} facturi in {data['an']}"),
            _tile("Marja bruta", lei(vanzari["marja_bruta_ron"]),
                  f"{lei(vanzari['marja_bruta_procent'], 1)}% din vanzari"),
            _tile("Rezultat", lei(rezultat), pnl["tip_rezultat"].capitalize(),
                  "good" if rezultat >= 0 else "bad"),
            _tile("Sold clienti", lei(situatie["creante_clienti_ron"]),
                  f"din care {lei(restante['valoare_ron'])} restant",
                  "warn" if restante["valoare_ron"] else ""),
            _tile("Valoare stoc", lei(stoc["valoare_totala_stoc_ron"]),
                  f"{stoc['numar_produse']} articole in gestiune"),
            _tile("Consumuri", lei(consum["total_consum_ron"]),
                  f"{len(consum['pe_articol'])} articole date in consum"),
            _tile("Trezorerie", lei(situatie["trezorerie"]["total_ron"]),
                  f"banca {lei(situatie['trezorerie']['banca_ron'])}"),
            _tile("TVA", lei(tva["sold_ron"]), tva["situatie"].lower(),
                  "bad" if tva["situatie"] == "TVA de plata" else "good"),
        ]
    )

    # Vanzari lunare
    luni_cu_vanzari = [item for item in data["vanzari_lunar"] if item["net"]]
    grafic_vanzari = _bars_vertical(data["vanzari_lunar"], moneda)
    top_clienti = _table(
        ["Client", f"Vanzari ({moneda})", "Facturi"],
        [[escape(c["client"]), lei(c["net"]), str(c["facturi"])] for c in data["top_clienti"]],
    )

    # Creante
    ordine = ["nescadente", "1-30", "31-60", "61-90", "peste_90"]
    etichete = {
        "nescadente": "Nescadente", "1-30": "1-30 zile", "31-60": "31-60 zile",
        "61-90": "61-90 zile", "peste_90": "Peste 90 de zile",
    }
    aging = [(etichete[k], scadente["intervale"][k]["total_ron"]) for k in ordine]
    grafic_scadente = _bars_horizontal([a for a in aging if a[1]], moneda, ramp=True)

    restante_rows = []
    for key in ordine:
        for f in scadente["intervale"][key]["facturi"]:
            zile = f["zile_intarziere"]
            tone = "mut" if zile == 0 else "warn" if zile <= 60 else "bad"
            eticheta = "in termen" if zile == 0 else f"{zile} zile"
            restante_rows.append(
                [
                    escape(f["factura"]),
                    escape(f["client"]),
                    escape(f["scadenta"]),
                    f'<span class="pill pill-{tone}">{eticheta}</span>',
                    lei(f["restant_ron"]),
                ]
            )
    tabel_restante = _table(
        ["Factura", "Client", "Scadenta", "Intarziere", f"Restant ({moneda})"],
        restante_rows, numeric_from=4,
    )

    # Stoc
    sub_prag = {item["sku"] for item in stoc["produse_sub_prag"]}
    epuizate = set(stoc["produse_epuizate"])
    stoc_rows = []
    for item in stoc["detalii"]:
        if item["sku"] in epuizate:
            stare = '<span class="pill pill-bad">epuizat</span>'
        elif item["sku"] in sub_prag:
            stare = '<span class="pill pill-warn">sub prag</span>'
        else:
            stare = '<span class="pill pill-good">ok</span>'
        stoc_rows.append(
            [
                escape(item["sku"]),
                escape(item["denumire"]),
                stare,
                f'{lei(item["stoc"], 0)} {escape(item["um"])}',
                lei(item["valoare_ron"]),
            ]
        )
    tabel_stoc = _table(
        ["Cod", "Denumire", "Stare", "Stoc", f"Valoare ({moneda})"], stoc_rows, numeric_from=3
    )

    # Consumuri
    grafic_consum = _bars_horizontal(
        [(c["centru"], c["valoare_ron"]) for c in consum["pe_centru_de_cost"]], moneda
    )
    tabel_consum = _table(
        ["Cod", "Denumire", "Cantitate", f"Valoare ({moneda})"],
        [
            [escape(c["sku"]), escape(c["denumire"]),
             f'{lei(c["cantitate"], 0)} {escape(c["um"])}', lei(c["valoare_ron"])]
            for c in consum["pe_articol"]
        ],
        numeric_from=2,
    )

    # Contabilitate
    pnl_rows = [[escape(v["denumire"]), lei(v["suma_ron"])] for v in pnl["venituri"]]
    pnl_rows += [[escape(ch["denumire"]), "-" + lei(ch["suma_ron"])] for ch in pnl["cheltuieli"]]
    pnl_rows.append([f"<strong>{pnl['tip_rezultat'].capitalize()}</strong>",
                     f"<strong>{lei(rezultat)}</strong>"])
    tabel_pnl = _table(["Cont", f"Suma ({moneda})"], pnl_rows)

    banda = f'<p class="banner">{escape(nota)}</p>' if nota else ""

    alerta = ""
    if restante["valoare_ron"]:
        alerta = (
            f'<p class="note">De urmarit: {restante["numar"]} facturi restante,'
            f' in valoare de {lei(restante["valoare_ron"])} {moneda}.</p>'
        )

    return f"""<title>Situatia {escape(data['firma'])} {data['an']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>{STYLE}</style>
<div class="page">
  <header class="masthead">
    <h1>{escape(data['firma'])}<br>Situatia anului {data['an']}</h1>
    <span class="spacer"></span>
    <p class="meta">Generat {data['generat']}<br>Sume in {moneda}, fara TVA acolo unde nu scrie altfel</p>
  </header>

  {banda}
  <section>
    <p class="eyebrow">Pe scurt</p>
    <h2>Cum sta firma</h2>
    <div class="tiles">{tiles}</div>
    {alerta}
  </section>

  <section>
    <p class="eyebrow">Vanzari</p>
    <h2>Vanzari nete pe luni, {data['an']}</h2>
    <div class="panel">
      {grafic_vanzari}
      <p class="note">{len(luni_cu_vanzari)} luni cu activitate. Cost marfa vanduta:
        {lei(vanzari['cost_marfa_ron'])} {moneda}.</p>
    </div>
    <h3>Cei mai mari clienti</h3>
    <div class="panel">{top_clienti}</div>
  </section>

  <section>
    <p class="eyebrow">Creante</p>
    <h2>Cine si de cand datoreaza</h2>
    <div class="panel">
      {grafic_scadente}
      <p class="note">Total de incasat: {lei(scadente['total_creante_ron'])} {moneda}.</p>
    </div>
    <h3>Facturi neincasate</h3>
    <div class="panel">{tabel_restante}</div>
  </section>

  <section>
    <p class="eyebrow">Gestiune</p>
    <h2>Stocul la zi</h2>
    <div class="panel">{tabel_stoc}
      <p class="note">Evaluat la cost mediu ponderat. Total
        {lei(stoc['valoare_totala_stoc_ron'])} {moneda}.</p>
    </div>
  </section>

  <section>
    <p class="eyebrow">Consumuri</p>
    <h2>Ce s-a dat in consum</h2>
    <div class="panel">
      {grafic_consum}
      <p class="note">Repartizat pe centre de cost, la costul mediu din momentul bonului.</p>
    </div>
    <h3>Pe articol</h3>
    <div class="panel">{tabel_consum}</div>
  </section>

  <section>
    <p class="eyebrow">Contabilitate</p>
    <h2>Rezultatul si TVA</h2>
    <div class="panel">{tabel_pnl}
      <p class="note">TVA colectata {lei(tva['tva_colectata_ron'])}, deductibila
        {lei(tva['tva_deductibila_ron'])} - {tva['situatie'].lower()}
        {lei(tva['sold_ron'])} {moneda}.</p>
    </div>
  </section>

  <footer>
    Raport generat de Gestio din inregistrarile proprii. Cifrele urmeaza notele
    contabile din jurnal; nu tin locul unei balante semnate de contabil.
  </footer>
</div>
"""


def write(path: str | Path, year: int | None = None, nota: str | None = None) -> Path:
    """Scrie raportul pe disc si intoarce calea catre el."""
    target = Path(path)
    target.write_text(render(collect(year), nota=nota), encoding="utf-8")
    return target
