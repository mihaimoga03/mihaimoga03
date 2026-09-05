"""Unelte de contabilitate: cheltuieli, balanta, profit si pierdere, TVA, jurnal."""

from __future__ import annotations

from anthropic import beta_tool

from ..accounting import ACCOUNTS, EXPENSE_ACCOUNTS, account_name, cash_account, post
from ..db import rows, transaction
from ..money import ron_to_bani, vat_of
from ._util import (
    ToolError,
    conn,
    out,
    parse_date,
    period,
    require_vat_rate,
    ron,
    safe,
    today,
)


def _balances(date_from: str, date_to: str) -> list[dict]:
    """Rulajele si soldul fiecarui cont pe o perioada."""
    return rows(
        conn().execute(
            "SELECT l.account, SUM(l.debit_bani) AS debit, SUM(l.credit_bani) AS credit"
            " FROM journal_lines l JOIN journal j ON j.id = l.journal_id"
            " WHERE j.date BETWEEN ? AND ? GROUP BY l.account ORDER BY l.account",
            (date_from, date_to),
        )
    )


@beta_tool
@safe
def inregistreaza_cheltuiala(
    account: str,
    amount_ron: float,
    description: str,
    method: str = "banca",
    vat_rate: int | None = None,
    date: str | None = None,
) -> str:
    """Inregistreaza o cheltuiala platita, cu TVA deductibila.

    Nota contabila: contul de cheltuiala si 4426 pe debit, contul de trezorerie
    pe credit.

    Args:
        account: Contul de cheltuiala (ex. 628 servicii, 612 chirii, 624 transport, 605 utilitati).
        amount_ron: Valoarea fara TVA, in RON.
        description: Descrierea cheltuielii.
        method: 'banca' sau 'numerar'.
        vat_rate: Cota de TVA; 0 daca furnizorul nu e platitor. Implicit cota standard.
        date: Data platii (YYYY-MM-DD); implicit ziua curenta.
    """
    if account not in EXPENSE_ACCOUNTS:
        raise ToolError(
            f"Contul '{account}' nu e un cont de cheltuiala cunoscut."
            f" Alege dintre: {', '.join(sorted(EXPENSE_ACCOUNTS))}."
        )
    net = ron_to_bani(amount_ron)
    if net <= 0:
        raise ToolError("Valoarea cheltuielii trebuie sa fie pozitiva.")
    rate = require_vat_rate(vat_rate)
    cash = cash_account(method)
    when = parse_date(date)
    vat = vat_of(net, rate)
    total = net + vat

    with transaction() as c:
        lines = [(account, net, 0, description)]
        if vat:
            lines.append(("4426", vat, 0, f"TVA {rate}%"))
        lines.append((cash, 0, total, method))
        journal_id = post(c, when, "cheltuiala", None, description, lines)

    return out(
        {
            "ok": True,
            "journal_id": journal_id,
            "cont": f"{account} - {account_name(account)}",
            "net_ron": ron(net),
            "tva_ron": ron(vat),
            "total_ron": ron(total),
            "data": when,
        }
    )


@beta_tool
@safe
def plateste_furnizor(
    purchase_id: int, amount_ron: float, method: str = "banca", date: str | None = None
) -> str:
    """Achita, total sau partial, o factura de achizitie inregistrata prin receptie.

    Nota contabila: 401 pe debit, contul de trezorerie pe credit.

    Args:
        purchase_id: Id-ul achizitiei (intors de `receptie_marfa`).
        amount_ron: Suma platita in RON.
        method: 'banca' sau 'numerar'.
        date: Data platii (YYYY-MM-DD); implicit ziua curenta.
    """
    amount = ron_to_bani(amount_ron)
    if amount <= 0:
        raise ToolError("Suma platita trebuie sa fie pozitiva.")
    cash = cash_account(method)
    when = parse_date(date)

    with transaction() as c:
        row = c.execute(
            "SELECT p.*, s.name AS supplier FROM purchases p JOIN suppliers s ON s.id = p.supplier_id"
            " WHERE p.id = ?",
            (int(purchase_id),),
        ).fetchone()
        if not row:
            raise ToolError(f"Nu exista achizitia cu id-ul {purchase_id}.")
        purchase = dict(row)
        restant = purchase["total_bani"] - purchase["paid_bani"]
        if amount > restant:
            raise ToolError(f"Suma depaseste restul de plata ({ron(restant)} RON).")
        c.execute(
            "UPDATE purchases SET paid_bani = paid_bani + ? WHERE id = ?", (amount, purchase_id)
        )
        c.execute(
            "INSERT INTO payments (purchase_id, direction, date, amount_bani, method)"
            " VALUES (?,'plata',?,?,?)",
            (purchase_id, when, amount, method),
        )
        post(
            c,
            when,
            "plata_furnizor",
            purchase_id,
            f"Plata furnizor {purchase['supplier']}",
            [("401", amount, 0, "Stingere datorie"), (cash, 0, amount, method)],
        )

    return out(
        {
            "ok": True,
            "purchase_id": purchase_id,
            "furnizor": purchase["supplier"],
            "platit_acum_ron": ron(amount),
            "restant_ron": ron(restant - amount),
        }
    )


@beta_tool
@safe
def balanta_verificare(date_from: str | None = None, date_to: str | None = None) -> str:
    """Balanta de verificare: rulaje debitoare si creditoare pe fiecare cont.

    Args:
        date_from: Data de inceput (YYYY-MM-DD); implicit inceputul anului curent.
        date_to: Data de sfarsit (YYYY-MM-DD); implicit ziua curenta.
    """
    start, end = period(date_from, date_to)
    conturi = []
    total_d = total_c = 0
    for row in _balances(start, end):
        debit, credit = int(row["debit"]), int(row["credit"])
        total_d += debit
        total_c += credit
        conturi.append(
            {
                "cont": row["account"],
                "denumire": account_name(row["account"]),
                "rulaj_debitor_ron": ron(debit),
                "rulaj_creditor_ron": ron(credit),
                "sold_ron": ron(debit - credit),
            }
        )
    return out(
        {
            "perioada": {"de_la": start, "pana_la": end},
            "conturi": conturi,
            "total_debit_ron": ron(total_d),
            "total_credit_ron": ron(total_c),
            "echilibrata": total_d == total_c,
        }
    )


@beta_tool
@safe
def cont_profit_pierdere(date_from: str | None = None, date_to: str | None = None) -> str:
    """Contul de profit si pierdere: venituri, cheltuieli si rezultatul perioadei.

    Args:
        date_from: Data de inceput (YYYY-MM-DD); implicit inceputul anului curent.
        date_to: Data de sfarsit (YYYY-MM-DD); implicit ziua curenta.
    """
    start, end = period(date_from, date_to)
    venituri, cheltuieli = [], []
    total_v = total_ch = 0
    for row in _balances(start, end):
        cont = row["account"]
        debit, credit = int(row["debit"]), int(row["credit"])
        if cont.startswith("7"):
            value = credit - debit
            total_v += value
            venituri.append({"cont": cont, "denumire": account_name(cont), "suma_ron": ron(value)})
        elif cont.startswith("6"):
            value = debit - credit
            total_ch += value
            cheltuieli.append({"cont": cont, "denumire": account_name(cont), "suma_ron": ron(value)})

    rezultat = total_v - total_ch
    marja = round(100 * rezultat / total_v, 2) if total_v else 0.0
    return out(
        {
            "perioada": {"de_la": start, "pana_la": end},
            "venituri": venituri,
            "total_venituri_ron": ron(total_v),
            "cheltuieli": cheltuieli,
            "total_cheltuieli_ron": ron(total_ch),
            "rezultat_ron": ron(rezultat),
            "tip_rezultat": "profit" if rezultat >= 0 else "pierdere",
            "marja_neta_procent": marja,
        }
    )


@beta_tool
@safe
def decont_tva(date_from: str | None = None, date_to: str | None = None) -> str:
    """Decontul de TVA: colectata, deductibila si soldul de plata sau de recuperat.

    Args:
        date_from: Data de inceput (YYYY-MM-DD); implicit inceputul anului curent.
        date_to: Data de sfarsit (YYYY-MM-DD); implicit ziua curenta.
    """
    start, end = period(date_from, date_to)
    colectata = deductibila = 0
    for row in _balances(start, end):
        if row["account"] == "4427":
            colectata = int(row["credit"]) - int(row["debit"])
        elif row["account"] == "4426":
            deductibila = int(row["debit"]) - int(row["credit"])
    sold = colectata - deductibila
    return out(
        {
            "perioada": {"de_la": start, "pana_la": end},
            "tva_colectata_ron": ron(colectata),
            "tva_deductibila_ron": ron(deductibila),
            "sold_ron": ron(abs(sold)),
            "situatie": "TVA de plata" if sold >= 0 else "TVA de recuperat",
        }
    )


@beta_tool
@safe
def jurnal_contabil(
    date_from: str | None = None,
    date_to: str | None = None,
    account: str | None = None,
    limit: int = 30,
) -> str:
    """Notele contabile dintr-o perioada, optional filtrate pe un cont.

    Args:
        date_from: Data de inceput (YYYY-MM-DD); implicit inceputul anului curent.
        date_to: Data de sfarsit (YYYY-MM-DD); implicit ziua curenta.
        account: Codul unui cont, pentru a vedea doar notele care il ating.
        limit: Numarul maxim de note intors.
    """
    start, end = period(date_from, date_to)
    if account and account not in ACCOUNTS:
        raise ToolError(f"Cont necunoscut '{account}'. Conturi disponibile: {', '.join(sorted(ACCOUNTS))}.")

    sql = "SELECT DISTINCT j.* FROM journal j"
    args: list = []
    if account:
        sql += " JOIN journal_lines l ON l.journal_id = j.id AND l.account = ?"
        args.append(account)
    sql += " WHERE j.date BETWEEN ? AND ? ORDER BY j.date DESC, j.id DESC LIMIT ?"
    args += [start, end, max(1, min(int(limit), 200))]

    c = conn()
    note = []
    for j in rows(c.execute(sql, args)):
        lines = rows(
            c.execute(
                "SELECT account, debit_bani, credit_bani, description FROM journal_lines"
                " WHERE journal_id = ? ORDER BY id",
                (j["id"],),
            )
        )
        note.append(
            {
                "id": j["id"],
                "data": j["date"],
                "document": j["ref_type"],
                "ref_id": j["ref_id"],
                "explicatie": j["description"],
                "linii": [
                    {
                        "cont": line["account"],
                        "denumire": account_name(line["account"]),
                        "debit_ron": ron(line["debit_bani"]),
                        "credit_ron": ron(line["credit_bani"]),
                    }
                    for line in lines
                ],
            }
        )
    return out({"perioada": {"de_la": start, "pana_la": end}, "note": note, "total": len(note)})


@beta_tool
@safe
def situatie_generala(date_from: str | None = None, date_to: str | None = None) -> str:
    """Tablou de bord: trezorerie, creante, datorii, stoc, vanzari si rezultat.

    Este raportul de pornit cand cineva intreaba 'cum stam?'.

    Args:
        date_from: Data de inceput a perioadei analizate; implicit inceputul anului curent.
        date_to: Data de sfarsit; implicit ziua curenta.
    """
    start, end = period(date_from, date_to)
    c = conn()

    def sold(account: str) -> int:
        row = c.execute(
            "SELECT COALESCE(SUM(l.debit_bani - l.credit_bani), 0) AS s FROM journal_lines l"
            " JOIN journal j ON j.id = l.journal_id WHERE l.account = ? AND j.date <= ?",
            (account, end),
        ).fetchone()
        return int(row["s"])

    banca, casa = sold("5121"), sold("5311")
    creante = sold("4111")
    datorii = -sold("401")
    stoc_contabil = sold("371")

    vanzari = c.execute(
        "SELECT COALESCE(SUM(net_bani),0) net, COALESCE(SUM(cogs_bani),0) cogs, COUNT(*) n"
        " FROM invoices WHERE status IN ('emisa','partial','achitata')"
        " AND issue_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()

    restante = c.execute(
        "SELECT COALESCE(SUM(total_bani - paid_bani),0) AS s, COUNT(*) AS n FROM invoices"
        " WHERE status IN ('emisa','partial') AND due_date < ?",
        (end,),
    ).fetchone()

    stoc_redus = rows(
        c.execute(
            "SELECT sku, name, stock_qty, reorder_level FROM products"
            " WHERE active = 1 AND is_service = 0 AND reorder_level > 0"
            " AND stock_qty <= reorder_level ORDER BY stock_qty"
        )
    )

    net = int(vanzari["net"])
    cogs = int(vanzari["cogs"])
    return out(
        {
            "perioada": {"de_la": start, "pana_la": end},
            "trezorerie": {
                "banca_ron": ron(banca),
                "casa_ron": ron(casa),
                "total_ron": ron(banca + casa),
            },
            "creante_clienti_ron": ron(creante),
            "datorii_furnizori_ron": ron(datorii),
            "valoare_stoc_contabil_ron": ron(stoc_contabil),
            "vanzari": {
                "numar_facturi": vanzari["n"],
                "cifra_afaceri_ron": ron(net),
                "cost_marfa_ron": ron(cogs),
                "marja_bruta_ron": ron(net - cogs),
                "marja_bruta_procent": round(100 * (net - cogs) / net, 2) if net else 0.0,
            },
            "facturi_restante": {
                "numar": restante["n"],
                "valoare_ron": ron(int(restante["s"])),
            },
            "produse_de_reaprovizionat": stoc_redus,
        }
    )


@beta_tool
@safe
def plan_de_conturi() -> str:
    """Listeaza conturile disponibile in aplicatie, cu denumirile lor."""
    return out(
        {
            "conturi": [{"cont": code, "denumire": name} for code, name in sorted(ACCOUNTS.items())],
            "conturi_cheltuiala": sorted(EXPENSE_ACCOUNTS),
            "data_curenta": today(),
        }
    )


TOOLS = [
    inregistreaza_cheltuiala,
    plateste_furnizor,
    balanta_verificare,
    cont_profit_pierdere,
    decont_tva,
    jurnal_contabil,
    situatie_generala,
    plan_de_conturi,
]
