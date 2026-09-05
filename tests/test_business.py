"""Testele de business: stoc, facturare, incasari, contabilitate."""

from __future__ import annotations

import pytest

from gestio import db
from gestio.tools import books, clients, inventory, invoices


@pytest.fixture
def firma(ok):
    """Un client, o marfa cu stoc si un serviciu - punctul de plecare al testelor."""
    client = ok(clients.adauga_client, name="Alfa SRL", cui="RO1", payment_terms_days=30)
    ok(inventory.adauga_produs, sku="CIM", name="Ciment", sale_price_ron=40.0, reorder_level=10)
    ok(inventory.adauga_produs, sku="MAN", name="Manopera", sale_price_ron=100.0, tip="serviciu")
    ok(inventory.receptie_marfa, sku="CIM", qty=100, unit_cost_ron=25.0, supplier="Furnizor SRL")
    return client


def journal_is_balanced() -> bool:
    row = db.get_conn().execute(
        "SELECT COALESCE(SUM(debit_bani),0) d, COALESCE(SUM(credit_bani),0) c FROM journal_lines"
    ).fetchone()
    return row["d"] == row["c"]


# --- clienti ---------------------------------------------------------------


def test_client_duplicat_e_respins(ok, call):
    ok(clients.adauga_client, name="Alfa SRL")
    assert "eroare" in call(clients.adauga_client, name="Alfa SRL")


def test_identificator_ambiguu_cere_precizie(ok, call):
    ok(clients.adauga_client, name="Alfa Construct")
    ok(clients.adauga_client, name="Alfa Retail")
    result = call(clients.detalii_client, identificator="Alfa")
    assert "mai multi clienti" in result["eroare"]


def test_scadenta_urmeaza_termenul_clientului(ok):
    ok(clients.adauga_client, name="Beta SRL", payment_terms_days=45)
    result = ok(clients.propune_scadenta, identificator="Beta SRL", data_facturii="2026-01-01")
    assert result["scadenta"] == "2026-02-15"


# --- stoc ------------------------------------------------------------------


def test_receptia_recalculeaza_costul_mediu(ok, firma):
    ok(inventory.receptie_marfa, sku="CIM", qty=100, unit_cost_ron=35.0, supplier="Furnizor SRL")
    produs = ok(inventory.cauta_produse, query="CIM")["produse"][0]
    assert produs["stoc"] == 200
    assert produs["cost_mediu_ron"] == 30.0  # (100*25 + 100*35) / 200


def test_receptia_creeaza_datorie_si_tva_deductibila(ok, firma):
    balanta = {c["cont"]: c for c in ok(books.balanta_verificare)["conturi"]}
    assert balanta["371"]["rulaj_debitor_ron"] == 2500.0
    assert balanta["4426"]["rulaj_debitor_ron"] == 525.0  # 21% din 2500
    assert balanta["401"]["rulaj_creditor_ron"] == 3025.0
    assert journal_is_balanced()


def test_serviciile_nu_se_receptioneaza(call, firma):
    result = call(inventory.receptie_marfa, sku="MAN", qty=5, unit_cost_ron=10, supplier="X")
    assert "serviciu" in result["eroare"]


def test_minusul_de_inventar_intra_pe_cheltuieli(ok, firma):
    ok(inventory.ajusteaza_stoc, sku="CIM", qty_delta=-4, motiv="Sparte la manipulare")
    balanta = {c["cont"]: c for c in ok(books.balanta_verificare)["conturi"]}
    assert balanta["6588"]["rulaj_debitor_ron"] == 100.0  # 4 x 25 RON
    assert ok(inventory.cauta_produse, query="CIM")["produse"][0]["stoc"] == 96
    assert journal_is_balanced()


# --- facturare -------------------------------------------------------------


def _factura_simpla(ok, qty=10):
    factura = ok(invoices.creeaza_factura, client="Alfa SRL", issue_date="2026-03-01")
    ok(invoices.adauga_linie_factura, invoice_id=factura["invoice_id"], sku="CIM", qty=qty)
    return factura["invoice_id"]


def test_emiterea_scade_stocul_si_inregistreaza_venitul(ok, firma):
    invoice_id = _factura_simpla(ok)
    emisa = ok(invoices.emite_factura, invoice_id=invoice_id)

    assert emisa["numar"] == "FACT-1"
    assert emisa["net_ron"] == 400.0
    assert emisa["tva_ron"] == 84.0
    assert emisa["total_ron"] == 484.0
    assert emisa["marja_bruta_ron"] == 150.0  # 400 venit - 250 cost
    assert ok(inventory.cauta_produse, query="CIM")["produse"][0]["stoc"] == 90
    assert journal_is_balanced()


def test_ciorna_nu_atinge_stocul(ok, firma):
    _factura_simpla(ok)
    assert ok(inventory.cauta_produse, query="CIM")["produse"][0]["stoc"] == 100


def test_stocul_insuficient_anuleaza_toata_emiterea(ok, call, firma):
    invoice_id = _factura_simpla(ok, qty=500)
    result = call(invoices.emite_factura, invoice_id=invoice_id)

    assert "Stoc insuficient" in result["eroare"]
    assert ok(inventory.cauta_produse, query="CIM")["produse"][0]["stoc"] == 100
    assert ok(invoices.detalii_factura, invoice_id=invoice_id)["status"] == "ciorna"
    assert journal_is_balanced()


def test_serviciile_se_factureaza_fara_stoc(ok, firma):
    factura = ok(invoices.creeaza_factura, client="Alfa SRL")
    ok(invoices.adauga_linie_factura, invoice_id=factura["invoice_id"], sku="MAN", qty=8)
    emisa = ok(invoices.emite_factura, invoice_id=factura["invoice_id"])
    assert emisa["net_ron"] == 800.0
    assert emisa["marja_bruta_ron"] == 800.0


def test_nu_se_adauga_linii_pe_factura_emisa(ok, call, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    result = call(invoices.adauga_linie_factura, invoice_id=invoice_id, sku="CIM", qty=1)
    assert "ciorne" in result["eroare"]


def test_numerotarea_e_consecutiva_pe_serie(ok, firma):
    first = ok(invoices.emite_factura, invoice_id=_factura_simpla(ok, qty=5))
    second = ok(invoices.emite_factura, invoice_id=_factura_simpla(ok, qty=5))
    assert (first["numar"], second["numar"]) == ("FACT-1", "FACT-2")


# --- incasari --------------------------------------------------------------


def test_incasarea_partiala_apoi_totala(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)

    partial = ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=200)
    assert partial["status"] == "partial"
    assert partial["restant_ron"] == 284.0

    final = ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=284, method="numerar")
    assert final["status"] == "achitata"
    assert final["restant_ron"] == 0.0
    assert journal_is_balanced()


def test_nu_se_incaseaza_mai_mult_decat_restul(ok, call, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    result = call(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=1000)
    assert "depaseste" in result["eroare"]


def test_soldul_clientului_reflecta_incasarile(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=84)
    fisa = ok(clients.detalii_client, identificator="Alfa SRL")
    assert fisa["sold_restant_ron"] == 400.0


# --- stornare --------------------------------------------------------------


def test_stornarea_repune_marfa_si_inverseaza_notele(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(invoices.anuleaza_factura, invoice_id=invoice_id, motiv="Comanda anulata de client")

    assert ok(inventory.cauta_produse, query="CIM")["produse"][0]["stoc"] == 100
    pnl = ok(books.cont_profit_pierdere)
    assert pnl["total_venituri_ron"] == 0.0
    assert ok(clients.detalii_client, identificator="Alfa SRL")["sold_restant_ron"] == 0.0
    assert journal_is_balanced()


def test_factura_incasata_nu_se_storneaza(ok, call, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=100)
    result = call(invoices.anuleaza_factura, invoice_id=invoice_id, motiv="Gresita")
    assert "incasari" in result["eroare"]


# --- contabilitate ---------------------------------------------------------


def test_decontul_de_tva_scade_deductibila_din_colectata(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    decont = ok(books.decont_tva)
    assert decont["tva_colectata_ron"] == 84.0
    assert decont["tva_deductibila_ron"] == 525.0
    assert decont["situatie"] == "TVA de recuperat"


def test_cheltuiala_pe_cont_necunoscut_e_respinsa(call):
    assert "eroare" in call(books.inregistreaza_cheltuiala, account="999", amount_ron=10,
                            description="Test")


def test_cheltuiala_reduce_rezultatul(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(books.inregistreaza_cheltuiala, account="612", amount_ron=150, description="Chirie")

    pnl = ok(books.cont_profit_pierdere)
    assert pnl["total_venituri_ron"] == 400.0
    assert pnl["total_cheltuieli_ron"] == 400.0  # 250 cost marfa + 150 chirie
    assert pnl["rezultat_ron"] == 0.0


def test_plata_furnizorului_stinge_datoria(ok, call, firma):
    achizitie = ok(inventory.receptie_marfa, sku="CIM", qty=10, unit_cost_ron=25.0,
                   supplier="Furnizor SRL")
    plata = ok(books.plateste_furnizor, purchase_id=achizitie["purchase_id"], amount_ron=100)
    assert plata["restant_ron"] == round(achizitie["total_ron"] - 100, 2)
    assert "eroare" in call(books.plateste_furnizor, purchase_id=achizitie["purchase_id"],
                            amount_ron=99999)
    assert journal_is_balanced()


def test_balanta_ramane_echilibrata_dupa_orice_operatiune(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=484)
    ok(books.inregistreaza_cheltuiala, account="628", amount_ron=99.99, description="Contabilitate")
    ok(inventory.ajusteaza_stoc, sku="CIM", qty_delta=2, motiv="Plus la inventar")

    balanta = ok(books.balanta_verificare)
    assert balanta["echilibrata"] is True
    assert balanta["total_debit_ron"] == balanta["total_credit_ron"]


def test_raportul_de_scadente_grupeaza_pe_intarziere(ok, firma):
    vechi = ok(invoices.creeaza_factura, client="Alfa SRL", issue_date="2026-01-01",
               due_date="2026-01-10")
    ok(invoices.adauga_linie_factura, invoice_id=vechi["invoice_id"], sku="CIM", qty=1)
    ok(invoices.emite_factura, invoice_id=vechi["invoice_id"])

    raport = ok(clients.raport_scadente, la_data="2026-03-01")
    assert raport["intervale"]["31-60"]["total_ron"] == 48.4
    assert raport["total_creante_ron"] == 48.4


def test_situatia_generala_aduna_toate_capitolele(ok, firma):
    invoice_id = _factura_simpla(ok)
    ok(invoices.emite_factura, invoice_id=invoice_id)
    ok(invoices.incaseaza_factura, invoice_id=invoice_id, amount_ron=484)

    situatie = ok(books.situatie_generala)
    assert situatie["trezorerie"]["banca_ron"] == 484.0
    assert situatie["creante_clienti_ron"] == 0.0
    assert situatie["vanzari"]["cifra_afaceri_ron"] == 400.0
    assert situatie["valoare_stoc_contabil_ron"] == 2250.0


# --- consumabile si bonuri de consum ---------------------------------------


@pytest.fixture
def consumabil(ok, firma):
    ok(inventory.adauga_produs, sku="MAN-PROT", name="Manusi protectie",
       sale_price_ron=0, unit="pereche", tip="consumabil")
    ok(inventory.receptie_marfa, sku="MAN-PROT", qty=200, unit_cost_ron=7.50,
       supplier="Protect SRL")
    return "MAN-PROT"


def test_consumabilul_intra_pe_contul_302(ok, consumabil):
    balanta = {c["cont"]: c for c in ok(books.balanta_verificare)["conturi"]}
    assert balanta["302"]["rulaj_debitor_ron"] == 1500.0  # 200 x 7,50
    assert balanta["371"]["rulaj_debitor_ron"] == 2500.0  # marfa, cont separat


def test_bonul_de_consum_scade_stocul_si_trece_pe_cheltuiala(ok, consumabil):
    bon = ok(inventory.bon_consum, sku="MAN-PROT", qty=20, centru_cost="Santier Militari",
             motiv="Echipament protectie")

    assert bon["numar_bon"] == 1
    assert bon["valoare_ron"] == 150.0  # 20 x 7,50
    assert bon["stoc_ramas"] == 180

    balanta = {c["cont"]: c for c in ok(books.balanta_verificare)["conturi"]}
    assert balanta["602"]["rulaj_debitor_ron"] == 150.0
    assert balanta["302"]["rulaj_creditor_ron"] == 150.0
    assert journal_is_balanced()


def test_un_bon_poate_avea_mai_multe_pozitii(ok, consumabil):
    primul = ok(inventory.bon_consum, sku="MAN-PROT", qty=10, centru_cost="Atelier")
    al_doilea = ok(inventory.bon_consum, sku="CIM", qty=2, bon_id=primul["bon_id"])

    assert al_doilea["bon_id"] == primul["bon_id"]
    assert al_doilea["numar_bon"] == primul["numar_bon"]

    raport = ok(inventory.raport_consumuri)
    assert raport["total_consum_ron"] == 125.0  # 10 x 7,50 + 2 x 25
    assert {r["sku"] for r in raport["pe_articol"]} == {"MAN-PROT", "CIM"}
    assert raport["pe_centru_de_cost"][0]["centru"] == "Atelier"


def test_consumul_marfii_merge_pe_607(ok, firma):
    ok(inventory.bon_consum, sku="CIM", qty=4, motiv="Reparatii sediu")
    balanta = {c["cont"]: c for c in ok(books.balanta_verificare)["conturi"]}
    assert balanta["607"]["rulaj_debitor_ron"] == 100.0
    assert balanta["371"]["rulaj_creditor_ron"] == 100.0


def test_nu_se_consuma_peste_stoc(ok, call, consumabil):
    result = call(inventory.bon_consum, sku="MAN-PROT", qty=500)
    assert "Stoc insuficient" in result["eroare"]
    assert ok(inventory.cauta_produse, query="MAN-PROT")["produse"][0]["stoc"] == 200


def test_serviciul_nu_se_da_in_consum(call, firma):
    assert "serviciu" in call(inventory.bon_consum, sku="MAN", qty=1)["eroare"]


def test_raportul_de_consumuri_filtreaza_pe_centru(ok, consumabil):
    ok(inventory.bon_consum, sku="MAN-PROT", qty=10, centru_cost="Santier A")
    ok(inventory.bon_consum, sku="MAN-PROT", qty=4, centru_cost="Santier B")

    raport = ok(inventory.raport_consumuri, centru_cost="Santier B")
    assert raport["total_consum_ron"] == 30.0
