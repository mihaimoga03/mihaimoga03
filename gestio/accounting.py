"""Contabilitate in partida dubla, pe planul de conturi romanesc.

Fiecare eveniment economic (vanzare, incasare, receptie, plata, ajustare) produce
o nota contabila echilibrata: suma debitelor = suma creditelor. Nimic nu modifica
soldurile in afara functiei `post`.
"""

from __future__ import annotations

import sqlite3

# Conturile folosite de aplicatie, cu denumirile din planul de conturi.
ACCOUNTS: dict[str, str] = {
    "1012": "Capital subscris varsat",
    "302": "Materiale consumabile",
    "371": "Marfuri",
    "401": "Furnizori",
    "4111": "Clienti",
    "4426": "TVA deductibila",
    "4427": "TVA colectata",
    "5121": "Conturi la banci in lei",
    "5311": "Casa in lei",
    "607": "Cheltuieli privind marfurile",
    "602": "Cheltuieli cu materialele consumabile",
    "605": "Cheltuieli cu energia si apa",
    "612": "Cheltuieli cu redeventele si chiriile",
    "624": "Cheltuieli cu transportul",
    "628": "Alte cheltuieli cu serviciile executate de terti",
    "641": "Cheltuieli cu salariile personalului",
    "6588": "Alte cheltuieli de exploatare",
    "707": "Venituri din vanzarea marfurilor",
    "704": "Venituri din servicii prestate",
    "758": "Alte venituri din exploatare",
}

# Conturile de cheltuiala acceptate de `inregistreaza_cheltuiala`.
EXPENSE_ACCOUNTS = tuple(code for code in ACCOUNTS if code.startswith("6"))

ACCOUNT_ALIASES = {
    "banca": "5121",
    "numerar": "5311",
}

# Tipurile de articol si conturile lor. Marfa se cumpara ca sa fie vanduta,
# consumabilul ca sa fie folosit in firma, serviciul nu tine stoc deloc.
PRODUCT_KINDS = ("marfa", "consumabil", "serviciu")

STOCK_ACCOUNT = {"marfa": "371", "consumabil": "302"}
COST_ACCOUNT = {"marfa": "607", "consumabil": "602"}


def stock_account(kind: str) -> str:
    """Contul de stoc pentru un tip de articol."""
    try:
        return STOCK_ACCOUNT[kind]
    except KeyError:
        raise ValueError(f"Tipul '{kind}' nu tine stoc.") from None


def cost_account(kind: str) -> str:
    """Contul pe care se descarca valoarea iesita din stoc."""
    try:
        return COST_ACCOUNT[kind]
    except KeyError:
        raise ValueError(f"Tipul '{kind}' nu are cont de cost de stoc.") from None


def account_name(code: str) -> str:
    return ACCOUNTS.get(code, "Cont necunoscut")


def cash_account(method: str) -> str:
    """Contul de trezorerie pentru o metoda de plata ('banca' sau 'numerar')."""
    try:
        return ACCOUNT_ALIASES[method]
    except KeyError:
        raise ValueError("Metoda de plata trebuie sa fie 'banca' sau 'numerar'.") from None


def post(
    conn: sqlite3.Connection,
    date: str,
    ref_type: str,
    ref_id: int | None,
    description: str,
    lines: list[tuple[str, int, int, str]],
) -> int:
    """Inregistreaza o nota contabila.

    `lines` contine tupluri (cont, debit_bani, credit_bani, explicatie).
    Ridica ValueError daca nota nu e echilibrata sau daca o linie are si debit,
    si credit - ambele sunt erori de programare, nu situatii de rulare.
    """
    debit = sum(line[1] for line in lines)
    credit = sum(line[2] for line in lines)
    if debit != credit:
        raise ValueError(f"Nota contabila dezechilibrata: debit {debit} != credit {credit}")
    if debit == 0:
        raise ValueError("Nota contabila fara sume.")
    for account, d, c, _ in lines:
        if d and c:
            raise ValueError(f"Linia pe contul {account} are si debit, si credit.")
        if d < 0 or c < 0:
            raise ValueError(f"Sume negative pe contul {account}; foloseste stornarea.")

    cur = conn.execute(
        "INSERT INTO journal (date, ref_type, ref_id, description) VALUES (?,?,?,?)",
        (date, ref_type, ref_id, description),
    )
    journal_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO journal_lines (journal_id, account, debit_bani, credit_bani, description)"
        " VALUES (?,?,?,?,?)",
        [(journal_id, acc, d, c, desc) for acc, d, c, desc in lines],
    )
    return journal_id


def account_balance(conn: sqlite3.Connection, account: str, until: str | None = None) -> int:
    """Soldul unui cont (debit - credit) pana la o data inclusiv."""
    sql = (
        "SELECT COALESCE(SUM(l.debit_bani - l.credit_bani), 0) AS bal"
        " FROM journal_lines l JOIN journal j ON j.id = l.journal_id"
        " WHERE l.account = ?"
    )
    args: list = [account]
    if until:
        sql += " AND j.date <= ?"
        args.append(until)
    return int(conn.execute(sql, args).fetchone()["bal"])
