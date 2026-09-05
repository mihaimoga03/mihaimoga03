"""Unelte pentru gestiunea stocului: produse, receptii, ajustari, rapoarte.

Evaluarea stocului se face la cost mediu ponderat (CMP), recalculat la fiecare
receptie. Iesirile se descarca la CMP-ul curent.
"""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal

from anthropic import beta_tool

from ..accounting import cash_account, post
from ..db import rows, transaction
from ..money import ron_to_bani, vat_of
from ._util import (
    ToolError,
    conn,
    money_fields,
    out,
    parse_date,
    require_vat_rate,
    ron,
    safe,
)


def find_product(identifier: str, c: sqlite3.Connection | None = None) -> dict:
    """Cauta un produs dupa SKU, id sau denumire (potrivire unica)."""
    c = c or conn()
    ident = identifier.strip()
    row = c.execute("SELECT * FROM products WHERE sku = ?", (ident,)).fetchone()
    if row:
        return dict(row)
    if ident.isdigit():
        row = c.execute("SELECT * FROM products WHERE id = ?", (int(ident),)).fetchone()
        if row:
            return dict(row)
    matches = rows(c.execute("SELECT * FROM products WHERE name LIKE ?", (f"%{ident}%",)))
    if not matches:
        raise ToolError(f"Nu exista niciun produs care sa corespunda cu '{identifier}'.")
    if len(matches) > 1:
        names = ", ".join(f"{m['sku']} ({m['name']})" for m in matches[:10])
        raise ToolError(f"'{identifier}' se potriveste cu mai multe produse: {names}.")
    return matches[0]


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def record_move(
    c: sqlite3.Connection,
    product: dict,
    date: str,
    kind: str,
    qty: float,
    unit_cost_bani: int,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
) -> tuple[int, float]:
    """Aplica o miscare de stoc si intoarce (valoare_bani, stoc_nou).

    `qty` este pozitiv pentru intrari si negativ pentru iesiri. Costul mediu se
    recalculeaza doar la intrari; iesirile pastreaza CMP-ul curent.
    """
    old_qty = Decimal(str(product["stock_qty"]))
    delta = Decimal(str(qty))
    new_qty = old_qty + delta

    if delta < 0 and new_qty < Decimal("-0.000001"):
        raise ToolError(
            f"Stoc insuficient pentru {product['sku']}: ai {old_qty} {product['unit']},"
            f" ceri {-delta}."
        )

    if delta > 0:
        value = _round(delta * Decimal(unit_cost_bani))
        old_value = _round(old_qty * Decimal(product["avg_cost_bani"]))
        new_avg = (
            _round((Decimal(old_value + value)) / new_qty) if new_qty > 0 else unit_cost_bani
        )
    else:
        unit_cost_bani = product["avg_cost_bani"] if unit_cost_bani == 0 else unit_cost_bani
        value = -_round(-delta * Decimal(unit_cost_bani))
        new_avg = product["avg_cost_bani"] if new_qty > 0 else 0

    new_qty_f = float(new_qty)
    c.execute(
        "UPDATE products SET stock_qty = ?, avg_cost_bani = ? WHERE id = ?",
        (new_qty_f, new_avg, product["id"]),
    )
    c.execute(
        "INSERT INTO stock_moves (product_id, date, kind, qty, unit_cost_bani, value_bani,"
        " balance_qty, ref_type, ref_id, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            product["id"],
            date,
            kind,
            float(delta),
            unit_cost_bani,
            value,
            new_qty_f,
            ref_type,
            ref_id,
            note,
        ),
    )
    product["stock_qty"] = new_qty_f
    product["avg_cost_bani"] = new_avg
    return value, new_qty_f


def _get_or_create_supplier(c: sqlite3.Connection, name: str, cui: str | None) -> int:
    row = c.execute("SELECT id FROM suppliers WHERE name = ?", (name.strip(),)).fetchone()
    if row:
        return int(row["id"])
    cur = c.execute("INSERT INTO suppliers (name, cui) VALUES (?,?)", (name.strip(), cui))
    return int(cur.lastrowid)


@beta_tool
@safe
def adauga_produs(
    sku: str,
    name: str,
    sale_price_ron: float,
    unit: str = "buc",
    vat_rate: int | None = None,
    reorder_level: float = 0,
    serviciu: bool = False,
) -> str:
    """Adauga un produs sau un serviciu nou in nomenclator.

    Args:
        sku: Codul intern al produsului; trebuie sa fie unic.
        name: Denumirea produsului.
        sale_price_ron: Pretul de vanzare fara TVA, in RON.
        unit: Unitatea de masura (buc, kg, l, ora...).
        vat_rate: Cota de TVA in procente; implicit cota standard configurata.
        reorder_level: Pragul de stoc sub care produsul apare in raportul de reaprovizionare.
        serviciu: True pentru servicii (manopera, transport); acestea nu tin stoc.
    """
    rate = require_vat_rate(vat_rate)
    if not sku.strip() or not name.strip():
        raise ToolError("SKU-ul si denumirea sunt obligatorii.")
    if sale_price_ron < 0:
        raise ToolError("Pretul de vanzare nu poate fi negativ.")
    with transaction() as c:
        if c.execute("SELECT 1 FROM products WHERE sku = ?", (sku.strip(),)).fetchone():
            raise ToolError(f"Exista deja un produs cu SKU-ul '{sku}'.")
        cur = c.execute(
            "INSERT INTO products (sku, name, unit, vat_rate, sale_price_bani, reorder_level,"
            " is_service) VALUES (?,?,?,?,?,?,?)",
            (
                sku.strip(),
                name.strip(),
                unit,
                rate,
                ron_to_bani(sale_price_ron),
                float(reorder_level),
                1 if serviciu else 0,
            ),
        )
        pid = int(cur.lastrowid)
    return out(
        {
            "ok": True,
            "product_id": pid,
            "sku": sku.strip(),
            "cota_tva": rate,
            "tip": "serviciu" if serviciu else "marfa",
        }
    )


@beta_tool
@safe
def cauta_produse(query: str | None = None, doar_stoc_redus: bool = False, limit: int = 30) -> str:
    """Listeaza produsele cu stocul si valoarea lor curenta.

    Args:
        query: Text cautat in SKU sau denumire; gol inseamna toate produsele.
        doar_stoc_redus: Daca e True, intoarce doar produsele sub pragul de reaprovizionare.
        limit: Numarul maxim de produse intors.
    """
    sql = "SELECT * FROM products WHERE active = 1"
    args: list = []
    if query:
        sql += " AND (sku LIKE ? OR name LIKE ?)"
        args += [f"%{query}%"] * 2
    if doar_stoc_redus:
        sql += " AND is_service = 0 AND stock_qty <= reorder_level"
    sql += " ORDER BY name LIMIT ?"
    args.append(max(1, min(int(limit), 200)))

    produse = []
    for p in rows(conn().execute(sql, args)):
        produse.append(
            {
                "sku": p["sku"],
                "denumire": p["name"],
                "tip": "serviciu" if p["is_service"] else "marfa",
                "um": p["unit"],
                "stoc": p["stock_qty"],
                "prag_reaprovizionare": p["reorder_level"],
                "cost_mediu_ron": ron(p["avg_cost_bani"]),
                "pret_vanzare_ron": ron(p["sale_price_bani"]),
                "cota_tva": p["vat_rate"],
                "valoare_stoc_ron": ron(_round(Decimal(str(p["stock_qty"])) * Decimal(p["avg_cost_bani"]))),
            }
        )
    return out({"produse": produse, "total": len(produse)})


@beta_tool
@safe
def receptie_marfa(
    sku: str,
    qty: float,
    unit_cost_ron: float,
    supplier: str,
    doc_no: str | None = None,
    date: str | None = None,
    vat_rate: int | None = None,
    plata_imediata: str | None = None,
) -> str:
    """Inregistreaza o receptie de marfa: creste stocul si datoria catre furnizor.

    Recalculeaza costul mediu ponderat si intocmeste nota contabila
    371 = 401 pentru valoarea marfii, plus 4426 pentru TVA deductibila.

    Args:
        sku: Codul produsului receptionat.
        qty: Cantitatea receptionata; trebuie sa fie pozitiva.
        unit_cost_ron: Costul unitar de achizitie fara TVA, in RON.
        supplier: Denumirea furnizorului; se creeaza automat daca nu exista.
        doc_no: Numarul facturii de la furnizor.
        date: Data receptiei (YYYY-MM-DD); implicit ziua curenta.
        vat_rate: Cota de TVA a achizitiei; implicit cota produsului.
        plata_imediata: 'banca' sau 'numerar' daca factura se achita pe loc; gol o lasa neplatita.
    """
    if qty <= 0:
        raise ToolError("Cantitatea receptionata trebuie sa fie pozitiva.")
    if unit_cost_ron < 0:
        raise ToolError("Costul de achizitie nu poate fi negativ.")
    move_date = parse_date(date)
    unit_cost = ron_to_bani(unit_cost_ron)

    with transaction() as c:
        product = find_product(sku, c)
        if product["is_service"]:
            raise ToolError(f"'{product['sku']}' e un serviciu; serviciile nu au stoc de receptionat.")
        rate = product["vat_rate"] if vat_rate is None else require_vat_rate(vat_rate)
        supplier_id = _get_or_create_supplier(c, supplier, None)

        net = _round(Decimal(str(qty)) * Decimal(unit_cost))
        vat = vat_of(net, rate)
        total = net + vat
        cur = c.execute(
            "INSERT INTO purchases (supplier_id, doc_no, date, net_bani, vat_bani, total_bani)"
            " VALUES (?,?,?,?,?,?)",
            (supplier_id, doc_no, move_date, net, vat, total),
        )
        purchase_id = int(cur.lastrowid)

        value, new_qty = record_move(
            c, product, move_date, "receptie", qty, unit_cost,
            ref_type="receptie", ref_id=purchase_id, note=doc_no,
        )

        lines = [("371", value, 0, f"Marfa {product['sku']}")]
        if vat:
            lines.append(("4426", vat, 0, f"TVA {rate}%"))
        lines.append(("401", 0, total, f"Furnizor {supplier}"))
        post(c, move_date, "receptie", purchase_id, f"Receptie {product['sku']} de la {supplier}", lines)

        paid = 0
        if plata_imediata:
            account = cash_account(plata_imediata)
            post(
                c,
                move_date,
                "plata_furnizor",
                purchase_id,
                f"Plata furnizor {supplier}",
                [("401", total, 0, "Stingere datorie"), (account, 0, total, plata_imediata)],
            )
            c.execute("UPDATE purchases SET paid_bani = ? WHERE id = ?", (total, purchase_id))
            c.execute(
                "INSERT INTO payments (purchase_id, direction, date, amount_bani, method)"
                " VALUES (?,'plata',?,?,?)",
                (purchase_id, move_date, total, plata_imediata),
            )
            paid = total

    return out(
        {
            "ok": True,
            "purchase_id": purchase_id,
            "sku": product["sku"],
            "stoc_nou": new_qty,
            "cost_mediu_nou_ron": ron(product["avg_cost_bani"]),
            "valoare_ron": ron(value),
            "tva_ron": ron(vat),
            "total_ron": ron(total),
            "achitat_ron": ron(paid),
        }
    )


@beta_tool
@safe
def ajusteaza_stoc(sku: str, qty_delta: float, motiv: str, date: str | None = None) -> str:
    """Corecteaza stocul dupa inventar: plus sau minus de gestiune.

    Minusul se inregistreaza pe cheltuieli (6588 = 371), plusul pe venituri
    (371 = 758), evaluat la costul mediu curent.

    Args:
        sku: Codul produsului.
        qty_delta: Diferenta fata de stocul scriptic; negativa pentru minus.
        motiv: Explicatia ajustarii (inventar, deteriorare, eroare de operare).
        date: Data ajustarii (YYYY-MM-DD); implicit ziua curenta.
    """
    if qty_delta == 0:
        raise ToolError("Ajustarea trebuie sa fie diferita de zero.")
    move_date = parse_date(date)

    with transaction() as c:
        product = find_product(sku, c)
        if product["is_service"]:
            raise ToolError(f"'{product['sku']}' e un serviciu; nu are stoc de ajustat.")
        cost = product["avg_cost_bani"]
        value, new_qty = record_move(c, product, move_date, "ajustare", qty_delta, cost, note=motiv)
        amount = abs(value)
        if amount:
            if qty_delta < 0:
                lines = [("6588", amount, 0, motiv), ("371", 0, amount, f"Minus {product['sku']}")]
            else:
                lines = [("371", amount, 0, f"Plus {product['sku']}"), ("758", 0, amount, motiv)]
            post(c, move_date, "ajustare_stoc", product["id"], f"Ajustare {product['sku']}: {motiv}", lines)

    return out(
        {
            "ok": True,
            "sku": product["sku"],
            "ajustare": qty_delta,
            "stoc_nou": new_qty,
            "impact_valoric_ron": ron(value),
        }
    )


@beta_tool
@safe
def miscari_stoc(sku: str, limit: int = 20) -> str:
    """Istoricul miscarilor de stoc pentru un produs, cele mai recente intai.

    Args:
        sku: Codul produsului.
        limit: Numarul maxim de miscari intors.
    """
    product = find_product(sku)
    moves = rows(
        conn().execute(
            "SELECT date, kind, qty, unit_cost_bani, value_bani, balance_qty, ref_type, ref_id, note"
            " FROM stock_moves WHERE product_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (product["id"], max(1, min(int(limit), 200))),
        )
    )
    return out(
        {
            "sku": product["sku"],
            "denumire": product["name"],
            "stoc_curent": product["stock_qty"],
            "miscari": [money_fields(m) for m in moves],
        }
    )


@beta_tool
@safe
def raport_stoc() -> str:
    """Situatia stocurilor: valoare totala, produse sub prag si produse fara miscare."""
    produse = rows(
        conn().execute("SELECT * FROM products WHERE active = 1 AND is_service = 0 ORDER BY name")
    )
    total = 0
    sub_prag = []
    epuizate = []
    detalii = []
    for p in produse:
        val = _round(Decimal(str(p["stock_qty"])) * Decimal(p["avg_cost_bani"]))
        total += val
        entry = {
            "sku": p["sku"],
            "denumire": p["name"],
            "stoc": p["stock_qty"],
            "um": p["unit"],
            "valoare_ron": ron(val),
        }
        detalii.append(entry)
        if p["stock_qty"] <= 0:
            epuizate.append(p["sku"])
        elif p["stock_qty"] <= p["reorder_level"]:
            sub_prag.append({**entry, "prag": p["reorder_level"]})
    return out(
        {
            "valoare_totala_stoc_ron": ron(total),
            "numar_produse": len(produse),
            "produse_epuizate": epuizate,
            "produse_sub_prag": sub_prag,
            "detalii": detalii,
        }
    )


@beta_tool
@safe
def actualizeaza_pret(sku: str, sale_price_ron: float) -> str:
    """Modifica pretul de vanzare al unui produs.

    Args:
        sku: Codul produsului.
        sale_price_ron: Noul pret de vanzare fara TVA, in RON.
    """
    if sale_price_ron < 0:
        raise ToolError("Pretul nu poate fi negativ.")
    with transaction() as c:
        product = find_product(sku, c)
        c.execute(
            "UPDATE products SET sale_price_bani = ? WHERE id = ?",
            (ron_to_bani(sale_price_ron), product["id"]),
        )
    return out(
        {
            "ok": True,
            "sku": product["sku"],
            "pret_vechi_ron": ron(product["sale_price_bani"]),
            "pret_nou_ron": round(sale_price_ron, 2),
        }
    )


TOOLS = [
    adauga_produs,
    cauta_produse,
    receptie_marfa,
    ajusteaza_stoc,
    miscari_stoc,
    raport_stoc,
    actualizeaza_pret,
]
