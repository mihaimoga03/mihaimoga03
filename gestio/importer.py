"""Import de date reale din fisiere CSV.

Antetele sunt recunoscute flexibil: nu conteaza diacriticele, majusculele sau
ordinea coloanelor, iar numerele pot fi scrise si romaneste (1.234,56).
Fiecare rand e procesat separat, asa ca un rand gresit nu opreste importul -
apare in lista de erori din raportul final.
"""

from __future__ import annotations

import csv
import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .tools import clients, inventory, invoices

# Numele de coloana acceptate pentru fiecare camp logic.
ALIASES: dict[str, tuple[str, ...]] = {
    "sku": ("sku", "cod", "codprodus", "codarticol", "codintern"),
    "name": ("denumire", "nume", "produs", "articol", "descriere"),
    "unit": ("um", "unitate", "unitatedemasura"),
    "kind": ("tip", "categorie"),
    "qty": ("cantitate", "cant", "qty", "buc", "stoc"),
    "unit_cost": ("costunitar", "cost", "pretachizitie", "pretintrare"),
    "price": ("pret", "pretvanzare", "pretunitar", "pretlista"),
    "vat": ("cotatva", "tva", "cota"),
    "reorder": ("prag", "pragreaprovizionare", "stocminim", "minim"),
    "client": ("client", "cumparator", "beneficiar", "partener"),
    "cui": ("cui", "cif", "codfiscal"),
    "address": ("adresa", "adresafacturare"),
    "email": ("email", "mail", "eposta"),
    "phone": ("telefon", "tel", "mobil"),
    "terms": ("termen", "termenplata", "zileplata", "scadentazile"),
    "date": ("data", "datafactura", "dataemitere", "datadocument", "databon"),
    "document": ("numar", "factura", "numarfactura", "document", "nrfactura", "nr"),
    "paid": ("incasat", "achitat", "platit"),
    "cost_center": ("centrucost", "centrudecost", "santier", "sectie", "locdeconsum"),
    "reason": ("motiv", "explicatie", "observatii", "scop"),
}


class ImportProblem(Exception):
    """Eroare de import, raportata pe rand, nu aruncata in sus."""


def _fold(text: str) -> str:
    """Reduce un nume de coloana la forma lui canonica: fara diacritice, litere mici."""
    stripped = unicodedata.normalize("NFKD", text or "")
    ascii_only = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    return "".join(ch for ch in ascii_only.lower() if ch.isalnum())


def _index(header: Iterable[str]) -> dict[str, str]:
    """Leaga fiecare camp logic de numele real al coloanei din fisier."""
    folded = {_fold(column): column for column in header}
    mapping: dict[str, str] = {}
    for field, names in ALIASES.items():
        for candidate in names:
            if candidate in folded:
                mapping[field] = folded[candidate]
                break
    return mapping


def _text(row: dict, mapping: dict, field: str, default: str | None = None) -> str | None:
    column = mapping.get(field)
    if not column:
        return default
    value = (row.get(column) or "").strip()
    return value or default


def parse_number(value: str | None, default: float | None = None) -> float | None:
    """Accepta 1234.56, 1.234,56, 1,234.56 sau '1 234,56'."""
    if value is None or not str(value).strip():
        return default
    text = str(value).strip().replace(" ", "").replace(" ", "")
    text = text.rstrip("%").replace("RON", "").replace("lei", "").strip()
    if "," in text and "." in text:
        # Separatorul zecimal e ultimul dintre ele.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        raise ImportProblem(f"'{value}' nu e un numar.") from None


DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%y")


def parse_date(value: str | None, default: str | None = None) -> str | None:
    """Accepta formatele uzuale romanesti si le normalizeaza la YYYY-MM-DD."""
    if not value or not str(value).strip():
        return default
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ImportProblem(f"Data '{value}' nu e intr-un format recunoscut.")


def read_rows(path: str | Path) -> tuple[list[dict], dict[str, str]]:
    """Citeste un CSV, ghicindu-i delimitatorul, si intoarce randurile plus maparea."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ImportProblem("Fisierul e gol.")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(raw.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise ImportProblem("Fisierul nu are un rand de antet.")
    return list(reader), _index(reader.fieldnames)


def _call(tool, **kwargs) -> dict[str, Any]:
    result = json.loads(tool(**kwargs))
    if "eroare" in result:
        raise ImportProblem(result["eroare"])
    return result


def _run(rows: list[dict], handler: Callable[[dict], Any]) -> dict[str, Any]:
    """Aplica `handler` pe fiecare rand si aduna ce a reusit si ce nu."""
    ok_count, errors = 0, []
    for number, row in enumerate(rows, start=2):  # randul 1 e antetul
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            handler(row)
            ok_count += 1
        except ImportProblem as exc:
            errors.append({"rand": number, "eroare": str(exc)})
        except Exception as exc:  # noqa: BLE001 - orice rand stricat e raportat, nu fatal
            errors.append({"rand": number, "eroare": f"{type(exc).__name__}: {exc}"})
    return {"importate": ok_count, "esuate": len(errors), "erori": errors[:25]}


def import_clients(path: str | Path) -> dict[str, Any]:
    """Coloane: nume, cui, adresa, email, telefon, termen."""
    rows, mapping = read_rows(path)
    if "client" not in mapping and "name" not in mapping:
        raise ImportProblem("Lipseste coloana cu numele clientului ('client' sau 'denumire').")

    def handle(row: dict) -> None:
        name = _text(row, mapping, "client") or _text(row, mapping, "name")
        if not name:
            raise ImportProblem("Rand fara nume de client.")
        terms = parse_number(_text(row, mapping, "terms"))
        _call(
            clients.adauga_client,
            name=name,
            cui=_text(row, mapping, "cui"),
            address=_text(row, mapping, "address"),
            email=_text(row, mapping, "email"),
            phone=_text(row, mapping, "phone"),
            payment_terms_days=int(terms) if terms is not None else None,
        )

    return _run(rows, handle)


def import_products(path: str | Path, stock_date: str | None = None) -> dict[str, Any]:
    """Coloane: sku, denumire, um, tip, pret, cota_tva, stoc, cost_unitar, prag.

    Daca randul are stoc si cost unitar, se face si o receptie de sold initial.
    """
    rows, mapping = read_rows(path)
    if "sku" not in mapping:
        raise ImportProblem("Lipseste coloana cu codul articolului ('sku' sau 'cod').")

    def handle(row: dict) -> None:
        sku = _text(row, mapping, "sku")
        if not sku:
            raise ImportProblem("Rand fara cod de articol.")
        kind = (_text(row, mapping, "kind", "marfa") or "marfa").lower()
        if kind.startswith("cons"):
            kind = "consumabil"
        elif kind.startswith("serv"):
            kind = "serviciu"
        else:
            kind = "marfa"
        vat = parse_number(_text(row, mapping, "vat"))
        _call(
            inventory.adauga_produs,
            sku=sku,
            name=_text(row, mapping, "name") or sku,
            sale_price_ron=parse_number(_text(row, mapping, "price"), 0.0) or 0.0,
            unit=_text(row, mapping, "unit", "buc") or "buc",
            vat_rate=int(vat) if vat is not None else None,
            reorder_level=parse_number(_text(row, mapping, "reorder"), 0.0) or 0.0,
            tip=kind,
        )
        qty = parse_number(_text(row, mapping, "qty"), 0.0) or 0.0
        cost = parse_number(_text(row, mapping, "unit_cost"), 0.0) or 0.0
        if kind != "serviciu" and qty > 0:
            _call(
                inventory.receptie_marfa,
                sku=sku,
                qty=qty,
                unit_cost_ron=cost,
                supplier="Sold initial",
                doc_no="Sold initial",
                date=parse_date(stock_date) or stock_date,
                vat_rate=0,
            )

    return _run(rows, handle)


def import_sales(path: str | Path) -> dict[str, Any]:
    """Coloane: data, client, sku, cantitate, pret, numar (optional), incasat (optional).

    Randurile cu acelasi numar de document - sau, in lipsa lui, acelasi client si
    aceeasi data - ajung pe aceeasi factura, care se emite la final.
    """
    rows, mapping = read_rows(path)
    for required in ("client", "sku", "qty"):
        if required not in mapping:
            raise ImportProblem(f"Lipseste coloana '{required}' din fisierul de vanzari.")

    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    errors: list[dict] = []
    for number, row in enumerate(rows, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            key = _text(row, mapping, "document") or (
                f"{_text(row, mapping, 'client')}|{_text(row, mapping, 'date')}"
            )
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append({"row": row, "line": number})
        except Exception as exc:  # noqa: BLE001
            errors.append({"rand": number, "eroare": str(exc)})

    facturi, esuate = [], errors
    for key in order:
        entries = grouped[key]
        first = entries[0]["row"]
        try:
            client = _text(first, mapping, "client")
            if not client:
                raise ImportProblem("Rand fara client.")
            date = parse_date(_text(first, mapping, "date"))
            invoice = _call(invoices.creeaza_factura, client=client, issue_date=date)
            for entry in entries:
                row = entry["row"]
                _call(
                    invoices.adauga_linie_factura,
                    invoice_id=invoice["invoice_id"],
                    sku=_text(row, mapping, "sku"),
                    qty=parse_number(_text(row, mapping, "qty")) or 0,
                    unit_price_ron=parse_number(_text(row, mapping, "price")),
                )
            emisa = _call(invoices.emite_factura, invoice_id=invoice["invoice_id"])
            paid = parse_number(_text(first, mapping, "paid"))
            if paid:
                _call(
                    invoices.incaseaza_factura,
                    invoice_id=invoice["invoice_id"],
                    amount_ron=min(paid, emisa["total_ron"]),
                    date=date,
                )
            facturi.append(emisa["numar"])
        except Exception as exc:  # noqa: BLE001
            esuate.append({"rand": entries[0]["line"], "eroare": str(exc)})

    return {
        "importate": len(facturi),
        "esuate": len(esuate),
        "facturi": facturi[:50],
        "erori": esuate[:25],
    }


def import_consumptions(path: str | Path) -> dict[str, Any]:
    """Coloane: data, sku, cantitate, centru_cost, motiv, numar bon (optional).

    Randurile cu acelasi numar de bon ajung pe acelasi bon de consum.
    """
    rows, mapping = read_rows(path)
    for required in ("sku", "qty"):
        if required not in mapping:
            raise ImportProblem(f"Lipseste coloana '{required}' din fisierul de consumuri.")

    bonuri: dict[str, int] = {}

    def handle(row: dict) -> None:
        document = _text(row, mapping, "document")
        result = _call(
            inventory.bon_consum,
            sku=_text(row, mapping, "sku"),
            qty=parse_number(_text(row, mapping, "qty")) or 0,
            centru_cost=_text(row, mapping, "cost_center"),
            motiv=_text(row, mapping, "reason"),
            date=parse_date(_text(row, mapping, "date")),
            bon_id=bonuri.get(document) if document else None,
        )
        if document:
            bonuri[document] = result["bon_id"]

    return _run(rows, handle)


IMPORTERS: dict[str, Callable[..., dict[str, Any]]] = {
    "clienti": import_clients,
    "produse": import_products,
    "stoc": import_products,
    "vanzari": import_sales,
    "consumuri": import_consumptions,
}
