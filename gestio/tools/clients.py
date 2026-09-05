"""Unelte pentru gestiunea clientilor si a soldurilor lor."""

from __future__ import annotations

from anthropic import beta_tool

from .. import config
from ..db import rows, transaction
from ._util import (
    ToolError,
    add_days,
    conn,
    days_between,
    money_fields,
    out,
    parse_date,
    ron,
    safe,
    today,
)


def find_client(identifier: str) -> dict:
    """Cauta un client dupa id, CUI sau nume (potrivire partiala, unica)."""
    c = conn()
    ident = identifier.strip()
    if ident.isdigit():
        row = c.execute("SELECT * FROM clients WHERE id = ?", (int(ident),)).fetchone()
        if row:
            return dict(row)
    row = c.execute("SELECT * FROM clients WHERE cui = ?", (ident,)).fetchone()
    if row:
        return dict(row)
    matches = rows(
        c.execute("SELECT * FROM clients WHERE name LIKE ? ORDER BY name", (f"%{ident}%",))
    )
    if not matches:
        raise ToolError(f"Nu exista niciun client care sa corespunda cu '{identifier}'.")
    if len(matches) > 1:
        names = ", ".join(f"#{m['id']} {m['name']}" for m in matches[:10])
        raise ToolError(f"'{identifier}' se potriveste cu mai multi clienti: {names}.")
    return matches[0]


def client_balance_bani(client_id: int) -> int:
    """Soldul restant al clientului: facturi emise minus incasari."""
    row = conn().execute(
        "SELECT COALESCE(SUM(total_bani - paid_bani), 0) AS sold FROM invoices"
        " WHERE client_id = ? AND status IN ('emisa','partial')",
        (client_id,),
    ).fetchone()
    return int(row["sold"])


@beta_tool
@safe
def adauga_client(
    name: str,
    cui: str | None = None,
    address: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    payment_terms_days: int | None = None,
    reg_com: str | None = None,
    note: str | None = None,
) -> str:
    """Adauga un client nou in baza de date.

    Args:
        name: Denumirea clientului (obligatoriu).
        cui: Codul unic de inregistrare fiscala; trebuie sa fie unic.
        address: Adresa de facturare.
        email: Adresa de e-mail de contact.
        phone: Numarul de telefon.
        payment_terms_days: Termenul de plata in zile; implicit cel din configurare.
        reg_com: Numarul de la Registrul Comertului.
        note: Observatii libere despre client.
    """
    terms = config.DEFAULT_PAYMENT_TERMS_DAYS if payment_terms_days is None else int(payment_terms_days)
    if terms < 0:
        raise ToolError("Termenul de plata nu poate fi negativ.")
    if not name.strip():
        raise ToolError("Denumirea clientului nu poate fi goala.")
    with transaction() as c:
        existing = c.execute("SELECT id FROM clients WHERE name = ?", (name.strip(),)).fetchone()
        if existing:
            raise ToolError(f"Exista deja un client cu denumirea '{name}' (id {existing['id']}).")
        cur = c.execute(
            "INSERT INTO clients (name, cui, reg_com, address, email, phone,"
            " payment_terms_days, note) VALUES (?,?,?,?,?,?,?,?)",
            (name.strip(), cui, reg_com, address, email, phone, terms, note),
        )
        client_id = int(cur.lastrowid)
    return out({"ok": True, "client_id": client_id, "nume": name.strip(), "termen_plata_zile": terms})


@beta_tool
@safe
def cauta_clienti(query: str | None = None, doar_cu_sold: bool = False, limit: int = 25) -> str:
    """Listeaza clientii, optional filtrati dupa nume/CUI sau dupa sold restant.

    Args:
        query: Text cautat in denumire, CUI sau e-mail; gol inseamna toti clientii.
        doar_cu_sold: Daca e True, intoarce numai clientii care au facturi neincasate.
        limit: Numarul maxim de clienti intors.
    """
    c = conn()
    sql = "SELECT * FROM clients WHERE active = 1"
    args: list = []
    if query:
        sql += " AND (name LIKE ? OR cui LIKE ? OR email LIKE ?)"
        args += [f"%{query}%"] * 3
    sql += " ORDER BY name LIMIT ?"
    args.append(max(1, min(int(limit), 200)))

    result = []
    for row in rows(c.execute(sql, args)):
        sold = client_balance_bani(row["id"])
        if doar_cu_sold and sold == 0:
            continue
        result.append(
            {
                "id": row["id"],
                "nume": row["name"],
                "cui": row["cui"],
                "email": row["email"],
                "telefon": row["phone"],
                "termen_plata_zile": row["payment_terms_days"],
                "sold_restant_ron": ron(sold),
            }
        )
    return out({"clienti": result, "total": len(result)})


@beta_tool
@safe
def detalii_client(identificator: str) -> str:
    """Fisa completa a unui client: date de contact, sold si ultimele facturi.

    Args:
        identificator: Id-ul, CUI-ul sau denumirea clientului.
    """
    client = find_client(identificator)
    c = conn()
    facturi = rows(
        c.execute(
            "SELECT id, series, number, issue_date, due_date, status, total_bani, paid_bani"
            " FROM invoices WHERE client_id = ? ORDER BY issue_date DESC, id DESC LIMIT 10",
            (client["id"],),
        )
    )
    return out(
        {
            "client": money_fields(client),
            "sold_restant_ron": ron(client_balance_bani(client["id"])),
            "ultimele_facturi": [money_fields(f) for f in facturi],
        }
    )


@beta_tool
@safe
def actualizeaza_client(
    identificator: str,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    payment_terms_days: int | None = None,
    note: str | None = None,
    activ: bool | None = None,
) -> str:
    """Modifica datele unui client existent. Campurile lasate goale raman neschimbate.

    Args:
        identificator: Id-ul, CUI-ul sau denumirea clientului.
        email: Noua adresa de e-mail.
        phone: Noul numar de telefon.
        address: Noua adresa.
        payment_terms_days: Noul termen de plata in zile.
        note: Noile observatii.
        activ: False dezactiveaza clientul fara sa-i stearga istoricul.
    """
    client = find_client(identificator)
    updates: dict = {}
    if email is not None:
        updates["email"] = email
    if phone is not None:
        updates["phone"] = phone
    if address is not None:
        updates["address"] = address
    if payment_terms_days is not None:
        if int(payment_terms_days) < 0:
            raise ToolError("Termenul de plata nu poate fi negativ.")
        updates["payment_terms_days"] = int(payment_terms_days)
    if note is not None:
        updates["note"] = note
    if activ is not None:
        updates["active"] = 1 if activ else 0
    if not updates:
        raise ToolError("Nu ai indicat niciun camp de modificat.")

    sets = ", ".join(f"{k} = ?" for k in updates)
    with transaction() as c:
        c.execute(f"UPDATE clients SET {sets} WHERE id = ?", (*updates.values(), client["id"]))
    return out({"ok": True, "client_id": client["id"], "modificat": list(updates)})


@beta_tool
@safe
def fisa_client(identificator: str, date_from: str | None = None, date_to: str | None = None) -> str:
    """Extras de cont pentru un client: toate facturile si incasarile din perioada.

    Args:
        identificator: Id-ul, CUI-ul sau denumirea clientului.
        date_from: Data de inceput (YYYY-MM-DD); implicit inceputul anului curent.
        date_to: Data de sfarsit (YYYY-MM-DD); implicit ziua curenta.
    """
    from ._util import period

    client = find_client(identificator)
    start, end = period(date_from, date_to)
    c = conn()
    facturi = rows(
        c.execute(
            "SELECT id, series, number, issue_date, due_date, status, net_bani, vat_bani,"
            " total_bani, paid_bani FROM invoices WHERE client_id = ?"
            " AND issue_date BETWEEN ? AND ? ORDER BY issue_date, id",
            (client["id"], start, end),
        )
    )
    incasari = rows(
        c.execute(
            "SELECT p.id, p.date, p.amount_bani, p.method, p.invoice_id FROM payments p"
            " JOIN invoices i ON i.id = p.invoice_id"
            " WHERE i.client_id = ? AND p.direction = 'incasare' AND p.date BETWEEN ? AND ?"
            " ORDER BY p.date, p.id",
            (client["id"], start, end),
        )
    )
    facturat = sum(f["total_bani"] for f in facturi if f["status"] != "anulata")
    incasat = sum(p["amount_bani"] for p in incasari)
    return out(
        {
            "client": client["name"],
            "perioada": {"de_la": start, "pana_la": end},
            "facturi": [money_fields(f) for f in facturi],
            "incasari": [money_fields(p) for p in incasari],
            "total_facturat_ron": ron(facturat),
            "total_incasat_ron": ron(incasat),
            "sold_restant_ron": ron(client_balance_bani(client["id"])),
        }
    )


@beta_tool
@safe
def raport_scadente(la_data: str | None = None) -> str:
    """Situatia creantelor pe intervale de intarziere (raport de aging).

    Grupeaza facturile neincasate in: nescadente, 1-30, 31-60, 61-90 si peste 90
    de zile de intarziere.

    Args:
        la_data: Data de referinta (YYYY-MM-DD); implicit ziua curenta.
    """
    ref = parse_date(la_data, default=today())
    c = conn()
    facturi = rows(
        c.execute(
            "SELECT i.id, i.series, i.number, i.due_date, i.total_bani, i.paid_bani,"
            " c.name AS client, c.id AS client_id FROM invoices i"
            " JOIN clients c ON c.id = i.client_id"
            " WHERE i.status IN ('emisa','partial') ORDER BY i.due_date",
        )
    )
    buckets = {"nescadente": [], "1-30": [], "31-60": [], "61-90": [], "peste_90": []}
    totals = {k: 0 for k in buckets}
    for f in facturi:
        restant = f["total_bani"] - f["paid_bani"]
        if restant <= 0:
            continue
        late = days_between(f["due_date"], ref)
        if late <= 0:
            key = "nescadente"
        elif late <= 30:
            key = "1-30"
        elif late <= 60:
            key = "31-60"
        elif late <= 90:
            key = "61-90"
        else:
            key = "peste_90"
        totals[key] += restant
        buckets[key].append(
            {
                "factura": f"{f['series']}-{f['number']}",
                "invoice_id": f["id"],
                "client": f["client"],
                "scadenta": f["due_date"],
                "zile_intarziere": max(0, late),
                "restant_ron": ron(restant),
            }
        )
    return out(
        {
            "la_data": ref,
            "intervale": {k: {"total_ron": ron(totals[k]), "facturi": v} for k, v in buckets.items()},
            "total_creante_ron": ron(sum(totals.values())),
        }
    )


@beta_tool
@safe
def propune_scadenta(identificator: str, data_facturii: str | None = None) -> str:
    """Calculeaza scadenta unei facturi pe baza termenului de plata al clientului.

    Args:
        identificator: Id-ul, CUI-ul sau denumirea clientului.
        data_facturii: Data emiterii (YYYY-MM-DD); implicit ziua curenta.
    """
    client = find_client(identificator)
    issue = parse_date(data_facturii)
    return out(
        {
            "client": client["name"],
            "data_facturii": issue,
            "termen_zile": client["payment_terms_days"],
            "scadenta": add_days(issue, client["payment_terms_days"]),
        }
    )


TOOLS = [
    adauga_client,
    cauta_clienti,
    detalii_client,
    actualizeaza_client,
    fisa_client,
    raport_scadente,
    propune_scadenta,
]
