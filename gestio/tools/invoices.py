"""Unelte pentru facturare: ciorne, linii, emitere, incasari, stornare."""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from anthropic import beta_tool

from .. import config
from ..accounting import cash_account, cost_account, post, stock_account
from ..db import rows, transaction
from ..money import line_amounts, ron_to_bani
from ._util import (
    ToolError,
    add_days,
    conn,
    money_fields,
    out,
    parse_date,
    require_vat_rate,
    ron,
    safe,
    today,
)
from .clients import find_client
from .inventory import find_product, record_move


def _get_invoice(c: sqlite3.Connection, invoice_id: int) -> dict:
    row = c.execute("SELECT * FROM invoices WHERE id = ?", (int(invoice_id),)).fetchone()
    if not row:
        raise ToolError(f"Nu exista factura cu id-ul {invoice_id}.")
    return dict(row)


def _recalc_totals(c: sqlite3.Connection, invoice_id: int) -> dict:
    """Recalculeaza totalurile facturii din liniile ei."""
    agg = c.execute(
        "SELECT COALESCE(SUM(net_bani),0) n, COALESCE(SUM(vat_bani),0) v,"
        " COALESCE(SUM(total_bani),0) t, COALESCE(SUM(cogs_bani),0) g"
        " FROM invoice_lines WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    c.execute(
        "UPDATE invoices SET net_bani = ?, vat_bani = ?, total_bani = ?, cogs_bani = ? WHERE id = ?",
        (agg["n"], agg["v"], agg["t"], agg["g"], invoice_id),
    )
    return {"net": agg["n"], "vat": agg["v"], "total": agg["t"], "cogs": agg["g"]}


def _next_number(c: sqlite3.Connection, series: str) -> int:
    row = c.execute(
        "SELECT COALESCE(MAX(number), 0) AS n FROM invoices WHERE series = ?", (series,)
    ).fetchone()
    return int(row["n"]) + 1


def _invoice_payload(c: sqlite3.Connection, invoice: dict) -> dict:
    client = c.execute("SELECT name, cui FROM clients WHERE id = ?", (invoice["client_id"],)).fetchone()
    lines = rows(
        c.execute(
            "SELECT l.*, p.sku FROM invoice_lines l LEFT JOIN products p ON p.id = l.product_id"
            " WHERE l.invoice_id = ? ORDER BY l.id",
            (invoice["id"],),
        )
    )
    numar = f"{invoice['series']}-{invoice['number']}" if invoice["number"] else "(ciorna)"
    return {
        "invoice_id": invoice["id"],
        "numar": numar,
        "client": client["name"] if client else None,
        "cui": client["cui"] if client else None,
        "data_emiterii": invoice["issue_date"],
        "scadenta": invoice["due_date"],
        "status": invoice["status"],
        "net_ron": ron(invoice["net_bani"]),
        "tva_ron": ron(invoice["vat_bani"]),
        "total_ron": ron(invoice["total_bani"]),
        "incasat_ron": ron(invoice["paid_bani"]),
        "restant_ron": ron(invoice["total_bani"] - invoice["paid_bani"]),
        "linii": [money_fields(line) for line in lines],
    }


@beta_tool
@safe
def creeaza_factura(
    client: str,
    issue_date: str | None = None,
    due_date: str | None = None,
    note: str | None = None,
    series: str | None = None,
) -> str:
    """Deschide o factura in stare de ciorna pentru un client.

    Ciorna nu afecteaza stocul si nici contabilitatea. Adauga liniile cu
    `adauga_linie_factura`, apoi finalizeaza cu `emite_factura`.

    Args:
        client: Id-ul, CUI-ul sau denumirea clientului.
        issue_date: Data emiterii (YYYY-MM-DD); implicit ziua curenta.
        due_date: Scadenta (YYYY-MM-DD); implicit se calculeaza din termenul clientului.
        note: Mentiuni care apar pe factura.
        series: Seria facturii; implicit seria configurata.
    """
    target = find_client(client)
    issue = parse_date(issue_date)
    due = parse_date(due_date, default=add_days(issue, target["payment_terms_days"]))
    if due < issue:
        raise ToolError("Scadenta nu poate fi inaintea datei de emitere.")
    with transaction() as c:
        cur = c.execute(
            "INSERT INTO invoices (series, client_id, issue_date, due_date, status, note)"
            " VALUES (?,?,?,?,'ciorna',?)",
            (series or config.INVOICE_SERIES, target["id"], issue, due, note),
        )
        invoice_id = int(cur.lastrowid)
    return out(
        {
            "ok": True,
            "invoice_id": invoice_id,
            "client": target["name"],
            "data_emiterii": issue,
            "scadenta": due,
            "status": "ciorna",
        }
    )


@beta_tool
@safe
def adauga_linie_factura(
    invoice_id: int,
    sku: str | None = None,
    qty: float = 1,
    unit_price_ron: float | None = None,
    description: str | None = None,
    vat_rate: int | None = None,
) -> str:
    """Adauga o linie pe o factura in ciorna.

    Cu `sku` linia descarca stoc la emitere; fara `sku` este o linie de serviciu
    si atunci `description` si `unit_price_ron` sunt obligatorii.

    Args:
        invoice_id: Id-ul facturii in ciorna.
        sku: Codul produsului vandut; gol pentru servicii.
        qty: Cantitatea facturata.
        unit_price_ron: Pretul unitar fara TVA; implicit pretul de lista al produsului.
        description: Denumirea de pe factura; implicit denumirea produsului.
        vat_rate: Cota de TVA a liniei; implicit cota produsului sau cea standard.
    """
    if qty <= 0:
        raise ToolError("Cantitatea trebuie sa fie pozitiva.")
    with transaction() as c:
        invoice = _get_invoice(c, invoice_id)
        if invoice["status"] != "ciorna":
            raise ToolError(
                f"Factura {invoice_id} are statusul '{invoice['status']}'; se pot adauga linii"
                " doar pe ciorne."
            )
        product = None
        if sku:
            product = find_product(sku, c)
            price = product["sale_price_bani"] if unit_price_ron is None else ron_to_bani(unit_price_ron)
            rate = product["vat_rate"] if vat_rate is None else require_vat_rate(vat_rate)
            label = description or product["name"]
        else:
            if unit_price_ron is None or not description:
                raise ToolError("Pentru o linie fara produs sunt necesare descrierea si pretul.")
            price = ron_to_bani(unit_price_ron)
            rate = require_vat_rate(vat_rate)
            label = description
        if price < 0:
            raise ToolError("Pretul unitar nu poate fi negativ.")

        net, vat, total = line_amounts(qty, price, rate)
        c.execute(
            "INSERT INTO invoice_lines (invoice_id, product_id, description, qty,"
            " unit_price_bani, vat_rate, net_bani, vat_bani, total_bani) VALUES (?,?,?,?,?,?,?,?,?)",
            (invoice_id, product["id"] if product else None, label, float(qty), price, rate, net, vat, total),
        )
        totals = _recalc_totals(c, invoice_id)

    return out(
        {
            "ok": True,
            "invoice_id": invoice_id,
            "linie": {"descriere": label, "cantitate": qty, "pret_ron": ron(price), "cota_tva": rate},
            "net_linie_ron": ron(net),
            "total_linie_ron": ron(total),
            "total_factura_ron": ron(totals["total"]),
        }
    )


@beta_tool
@safe
def emite_factura(invoice_id: int) -> str:
    """Finalizeaza o ciorna: aloca numarul, descarca stocul si o inregistreaza in contabilitate.

    Nota contabila: 4111 = 707 + 4427 pentru venit si TVA, plus 607 = 371 pentru
    costul marfii vandute. Operatia esueaza in bloc daca stocul nu ajunge.

    Args:
        invoice_id: Id-ul facturii in ciorna.
    """
    with transaction() as c:
        invoice = _get_invoice(c, invoice_id)
        if invoice["status"] != "ciorna":
            raise ToolError(f"Factura {invoice_id} nu mai e ciorna (status '{invoice['status']}').")
        lines = rows(c.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,)))
        if not lines:
            raise ToolError("Nu poti emite o factura fara linii.")

        cogs_by_kind: dict[str, int] = {}
        for line in lines:
            if not line["product_id"]:
                continue
            product = dict(c.execute("SELECT * FROM products WHERE id = ?", (line["product_id"],)).fetchone())
            if product["kind"] == "serviciu":
                continue
            value, _ = record_move(
                c,
                product,
                invoice["issue_date"],
                "iesire",
                -float(line["qty"]),
                product["avg_cost_bani"],
                ref_type="factura",
                ref_id=invoice_id,
            )
            cogs = -value
            cogs_by_kind[product["kind"]] = cogs_by_kind.get(product["kind"], 0) + cogs
            c.execute("UPDATE invoice_lines SET cogs_bani = ? WHERE id = ?", (cogs, line["id"]))

        totals = _recalc_totals(c, invoice_id)
        number = _next_number(c, invoice["series"])
        c.execute(
            "UPDATE invoices SET number = ?, status = 'emisa' WHERE id = ?", (number, invoice_id)
        )

        client = c.execute("SELECT name FROM clients WHERE id = ?", (invoice["client_id"],)).fetchone()
        doc = f"{invoice['series']}-{number}"
        entries = [("4111", totals["total"], 0, f"Client {client['name']}")]
        if totals["net"]:
            entries.append(("707", 0, totals["net"], "Venituri din vanzari"))
        if totals["vat"]:
            entries.append(("4427", 0, totals["vat"], "TVA colectata"))
        post(c, invoice["issue_date"], "factura", invoice_id, f"Factura {doc}", entries)

        for kind, cogs in cogs_by_kind.items():
            if not cogs:
                continue
            post(
                c,
                invoice["issue_date"],
                "descarcare_gestiune",
                invoice_id,
                f"Descarcare gestiune factura {doc}",
                [
                    (cost_account(kind), cogs, 0, f"Cost {kind} vanduta"),
                    (stock_account(kind), 0, cogs, f"Iesire {kind}"),
                ],
            )
        cogs_total = sum(cogs_by_kind.values())

        invoice = _get_invoice(c, invoice_id)
        payload = _invoice_payload(c, invoice)

    payload["ok"] = True
    payload["marja_bruta_ron"] = ron(totals["net"] - cogs_total)
    return out(payload)


@beta_tool
@safe
def incaseaza_factura(
    invoice_id: int, amount_ron: float, method: str = "banca", date: str | None = None, note: str | None = None
) -> str:
    """Inregistreaza o incasare, totala sau partiala, pe o factura emisa.

    Nota contabila: 5121 (sau 5311) = 4111. Statusul facturii devine 'partial'
    sau 'achitata', dupa caz.

    Args:
        invoice_id: Id-ul facturii incasate.
        amount_ron: Suma incasata in RON.
        method: 'banca' sau 'numerar'.
        date: Data incasarii (YYYY-MM-DD); implicit ziua curenta.
        note: Explicatie (numar OP, chitanta).
    """
    amount = ron_to_bani(amount_ron)
    if amount <= 0:
        raise ToolError("Suma incasata trebuie sa fie pozitiva.")
    account = cash_account(method)
    pay_date = parse_date(date)

    with transaction() as c:
        invoice = _get_invoice(c, invoice_id)
        if invoice["status"] in ("ciorna", "anulata"):
            raise ToolError(f"Factura {invoice_id} are statusul '{invoice['status']}' si nu poate fi incasata.")
        restant = invoice["total_bani"] - invoice["paid_bani"]
        if amount > restant:
            raise ToolError(
                f"Suma depaseste restul de plata: restant {ron(restant)} RON,"
                f" incercat {ron(amount)} RON."
            )
        paid = invoice["paid_bani"] + amount
        status = "achitata" if paid >= invoice["total_bani"] else "partial"
        c.execute("UPDATE invoices SET paid_bani = ?, status = ? WHERE id = ?", (paid, status, invoice_id))
        c.execute(
            "INSERT INTO payments (invoice_id, direction, date, amount_bani, method, note)"
            " VALUES (?,'incasare',?,?,?,?)",
            (invoice_id, pay_date, amount, method, note),
        )
        post(
            c,
            pay_date,
            "incasare",
            invoice_id,
            f"Incasare factura {invoice['series']}-{invoice['number']}",
            [(account, amount, 0, method), ("4111", 0, amount, "Stingere creanta")],
        )

    return out(
        {
            "ok": True,
            "invoice_id": invoice_id,
            "incasat_acum_ron": ron(amount),
            "incasat_total_ron": ron(paid),
            "restant_ron": ron(invoice["total_bani"] - paid),
            "status": status,
        }
    )


@beta_tool
@safe
def anuleaza_factura(invoice_id: int, motiv: str) -> str:
    """Storneaza o factura emisa: repune marfa in stoc si inverseaza notele contabile.

    Nu se pot storna facturi care au deja incasari; acestea trebuie mai intai
    stornate de la incasare.

    Args:
        invoice_id: Id-ul facturii de anulat.
        motiv: Motivul anularii, pastrat in jurnal.
    """
    with transaction() as c:
        invoice = _get_invoice(c, invoice_id)
        if invoice["status"] == "anulata":
            raise ToolError(f"Factura {invoice_id} e deja anulata.")
        if invoice["paid_bani"]:
            raise ToolError(
                f"Factura {invoice_id} are incasari de {ron(invoice['paid_bani'])} RON;"
                " storneaza intai incasarile."
            )
        doc = f"{invoice['series']}-{invoice['number']}" if invoice["number"] else f"ciorna #{invoice_id}"

        if invoice["status"] == "ciorna":
            c.execute("UPDATE invoices SET status = 'anulata' WHERE id = ?", (invoice_id,))
            return out({"ok": True, "invoice_id": invoice_id, "status": "anulata", "note": "Ciorna anulata."})

        lines = rows(c.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,)))
        restored_by_kind: dict[str, int] = {}
        for line in lines:
            if not line["product_id"] or line["qty"] <= 0 or not line["cogs_bani"]:
                continue
            product = dict(c.execute("SELECT * FROM products WHERE id = ?", (line["product_id"],)).fetchone())
            unit_cost = int(
                (Decimal(line["cogs_bani"]) / Decimal(str(line["qty"]))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            ) if line["cogs_bani"] else product["avg_cost_bani"]
            record_move(
                c, product, today(), "stornare", float(line["qty"]), unit_cost,
                ref_type="stornare_factura", ref_id=invoice_id, note=motiv,
            )
            restored_by_kind[product["kind"]] = restored_by_kind.get(product["kind"], 0) + line["cogs_bani"]

        entries = [("4111", 0, invoice["total_bani"], "Stornare creanta")]
        if invoice["net_bani"]:
            entries.append(("707", invoice["net_bani"], 0, "Stornare venit"))
        if invoice["vat_bani"]:
            entries.append(("4427", invoice["vat_bani"], 0, "Stornare TVA colectata"))
        post(c, today(), "stornare_factura", invoice_id, f"Stornare factura {doc}: {motiv}", entries)

        for kind, value in restored_by_kind.items():
            if not value:
                continue
            post(
                c,
                today(),
                "stornare_descarcare",
                invoice_id,
                f"Stornare descarcare gestiune {doc}",
                [
                    (stock_account(kind), value, 0, f"Repunere {kind}"),
                    (cost_account(kind), 0, value, "Stornare cost"),
                ],
            )
        restored = sum(restored_by_kind.values())
        c.execute("UPDATE invoices SET status = 'anulata' WHERE id = ?", (invoice_id,))

    return out(
        {
            "ok": True,
            "invoice_id": invoice_id,
            "status": "anulata",
            "valoare_stornata_ron": ron(invoice["total_bani"]),
            "marfa_repusa_ron": ron(restored),
        }
    )


@beta_tool
@safe
def detalii_factura(invoice_id: int) -> str:
    """Afiseaza o factura cu toate liniile, totalurile si incasarile ei.

    Args:
        invoice_id: Id-ul facturii.
    """
    c = conn()
    invoice = _get_invoice(c, invoice_id)
    payload = _invoice_payload(c, invoice)
    payload["incasari"] = [
        money_fields(p)
        for p in rows(
            c.execute(
                "SELECT date, amount_bani, method, note FROM payments"
                " WHERE invoice_id = ? AND direction = 'incasare' ORDER BY date",
                (invoice_id,),
            )
        )
    ]
    return out(payload)


@beta_tool
@safe
def cauta_facturi(
    client: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
) -> str:
    """Listeaza facturile, filtrate dupa client, status sau perioada.

    Args:
        client: Id-ul, CUI-ul sau denumirea clientului; gol inseamna toti clientii.
        status: 'ciorna', 'emisa', 'partial', 'achitata' sau 'anulata'.
        date_from: Data de inceput a emiterii (YYYY-MM-DD).
        date_to: Data de sfarsit a emiterii (YYYY-MM-DD).
        limit: Numarul maxim de facturi intors.
    """
    valid = {"ciorna", "emisa", "partial", "achitata", "anulata"}
    if status and status not in valid:
        raise ToolError(f"Status invalid '{status}'; foloseste unul din: {', '.join(sorted(valid))}.")

    sql = (
        "SELECT i.*, c.name AS client FROM invoices i JOIN clients c ON c.id = i.client_id WHERE 1=1"
    )
    args: list = []
    if client:
        args.append(find_client(client)["id"])
        sql += " AND i.client_id = ?"
    if status:
        sql += " AND i.status = ?"
        args.append(status)
    if date_from:
        sql += " AND i.issue_date >= ?"
        args.append(parse_date(date_from))
    if date_to:
        sql += " AND i.issue_date <= ?"
        args.append(parse_date(date_to))
    sql += " ORDER BY i.issue_date DESC, i.id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 200)))

    facturi = [
        {
            "invoice_id": f["id"],
            "numar": f"{f['series']}-{f['number']}" if f["number"] else "(ciorna)",
            "client": f["client"],
            "data": f["issue_date"],
            "scadenta": f["due_date"],
            "status": f["status"],
            "total_ron": ron(f["total_bani"]),
            "restant_ron": ron(f["total_bani"] - f["paid_bani"]),
        }
        for f in rows(conn().execute(sql, args))
    ]
    return out({"facturi": facturi, "total": len(facturi)})


TOOLS = [
    creeaza_factura,
    adauga_linie_factura,
    emite_factura,
    incaseaza_factura,
    anuleaza_factura,
    detalii_factura,
    cauta_facturi,
]
