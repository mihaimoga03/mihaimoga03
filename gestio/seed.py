"""Date demonstrative, ca sa poti incerca agentul fara sa introduci nimic manual."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

from . import config, db
from .accounting import post
from .tools import books, clients, inventory, invoices


def _call(tool, **kwargs) -> dict[str, Any]:
    """Apeleaza o unealta si intoarce raspunsul ei ca dictionar."""
    result = json.loads(tool(**kwargs))
    if "eroare" in result:
        raise RuntimeError(f"{tool.name}: {result['eroare']}")
    return result


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def seed(reset: bool = False) -> dict[str, Any]:
    """Populeaza baza de date cu un mic set de date realiste."""
    if reset and os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
        db.set_conn(db.connect())

    conn = db.get_conn()
    if conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]:
        return {"ok": False, "mesaj": "Baza de date contine deja date. Ruleaza cu --reset."}

    # Aport initial de capital, ca trezoreria sa porneasca de la o valoare reala.
    with db.transaction() as c:
        post(
            c,
            _d(60),
            "aport_capital",
            None,
            "Aport initial de capital",
            [("5121", 3_000_000, 0, "Depunere in cont"), ("1012", 0, 3_000_000, "Capital")],
        )

    c1 = _call(clients.adauga_client, name="Alfa Construct SRL", cui="RO12345678",
               address="Str. Fabricii 12, Cluj-Napoca", email="office@alfaconstruct.ro",
               payment_terms_days=30)
    c2 = _call(clients.adauga_client, name="Beta Retail SA", cui="RO87654321",
               address="Bd. Unirii 3, Bucuresti", email="facturi@betaretail.ro",
               payment_terms_days=45)
    c3 = _call(clients.adauga_client, name="Gamma Service SRL", cui="RO11223344",
               address="Calea Victoriei 88, Bucuresti", payment_terms_days=15)

    _call(inventory.adauga_produs, sku="CIM-42", name="Ciment Portland 42.5R sac 40kg",
          sale_price_ron=38.50, unit="sac", reorder_level=50)
    _call(inventory.adauga_produs, sku="VOP-15", name="Vopsea lavabila interior 15L",
          sale_price_ron=189.00, unit="galeata", reorder_level=10)
    _call(inventory.adauga_produs, sku="GIP-125", name="Placa gips-carton 12.5mm",
          sale_price_ron=42.00, unit="buc", reorder_level=80)
    _call(inventory.adauga_produs, sku="SRV-MON", name="Manopera montaj",
          sale_price_ron=95.00, unit="ora", tip="serviciu")
    _call(inventory.adauga_produs, sku="MAN-PROT", name="Manusi protectie",
          sale_price_ron=0, unit="pereche", tip="consumabil", reorder_level=40)
    _call(inventory.adauga_produs, sku="DISC-230", name="Disc debitat 230mm",
          sale_price_ron=0, unit="buc", tip="consumabil", reorder_level=25)

    _call(inventory.receptie_marfa, sku="CIM-42", qty=400, unit_cost_ron=26.00,
          supplier="Holcim Distributie SRL", doc_no="HD-4412", date=_d(40))
    _call(inventory.receptie_marfa, sku="VOP-15", qty=30, unit_cost_ron=128.00,
          supplier="Deco Import SRL", doc_no="DI-991", date=_d(35), plata_imediata="banca")
    _call(inventory.receptie_marfa, sku="GIP-125", qty=300, unit_cost_ron=28.50,
          supplier="Holcim Distributie SRL", doc_no="HD-4501", date=_d(20))

    _call(inventory.receptie_marfa, sku="MAN-PROT", qty=240, unit_cost_ron=7.50,
          supplier="Protect Echipamente SRL", doc_no="PE-118", date=_d(38),
          plata_imediata="banca")
    _call(inventory.receptie_marfa, sku="DISC-230", qty=120, unit_cost_ron=11.20,
          supplier="Protect Echipamente SRL", doc_no="PE-119", date=_d(38))

    # Factura achitata integral catre primul client.
    f1 = _call(invoices.creeaza_factura, client="Alfa Construct SRL", issue_date=_d(30))
    _call(invoices.adauga_linie_factura, invoice_id=f1["invoice_id"], sku="CIM-42", qty=120)
    _call(invoices.adauga_linie_factura, invoice_id=f1["invoice_id"], sku="GIP-125", qty=80)
    emisa1 = _call(invoices.emite_factura, invoice_id=f1["invoice_id"])
    _call(invoices.incaseaza_factura, invoice_id=f1["invoice_id"],
          amount_ron=emisa1["total_ron"], method="banca", date=_d(12))

    # Factura restanta, ca sa se vada in raportul de scadente.
    f2 = _call(invoices.creeaza_factura, client="Beta Retail SA", issue_date=_d(70))
    _call(invoices.adauga_linie_factura, invoice_id=f2["invoice_id"], sku="VOP-15", qty=12)
    _call(invoices.adauga_linie_factura, invoice_id=f2["invoice_id"], sku="SRV-MON", qty=16,
          description="Manopera montaj - santier Militari")
    _call(invoices.emite_factura, invoice_id=f2["invoice_id"])

    # Factura incasata partial.
    f3 = _call(invoices.creeaza_factura, client="Gamma Service SRL", issue_date=_d(8))
    _call(invoices.adauga_linie_factura, invoice_id=f3["invoice_id"], sku="CIM-42", qty=60)
    emisa3 = _call(invoices.emite_factura, invoice_id=f3["invoice_id"])
    _call(invoices.incaseaza_factura, invoice_id=f3["invoice_id"],
          amount_ron=round(emisa3["total_ron"] / 2, 2), method="banca", date=_d(2))

    # Bonuri de consum: consumabile date pe santiere.
    bon = _call(inventory.bon_consum, sku="MAN-PROT", qty=60,
                centru_cost="Santier Militari", motiv="Echipament protectie", date=_d(28))
    _call(inventory.bon_consum, sku="DISC-230", qty=35, bon_id=bon["bon_id"])
    _call(inventory.bon_consum, sku="MAN-PROT", qty=24, centru_cost="Atelier",
          motiv="Intretinere utilaje", date=_d(15))
    _call(inventory.bon_consum, sku="DISC-230", qty=18, centru_cost="Santier Berceni",
          motiv="Debitare armatura", date=_d(6))
    _call(inventory.bon_consum, sku="CIM-42", qty=15, centru_cost="Sediu",
          motiv="Reparatii platforma depozit", date=_d(9))

    _call(books.inregistreaza_cheltuiala, account="612", amount_ron=3500,
          description="Chirie depozit", method="banca", date=_d(25))
    _call(books.inregistreaza_cheltuiala, account="605", amount_ron=742.30,
          description="Energie electrica si apa", method="banca", date=_d(18))
    _call(books.inregistreaza_cheltuiala, account="624", amount_ron=1180,
          description="Transport marfa la client", method="banca", date=_d(10))

    return {
        "ok": True,
        "clienti": [c1["client_id"], c2["client_id"], c3["client_id"]],
        "produse": 6,
        "facturi": [f1["invoice_id"], f2["invoice_id"], f3["invoice_id"]],
        "baza_de_date": config.DB_PATH,
        "mesaj": "Date demonstrative create. Incearca: gestio ask 'cum stam?'",
    }
