"""Testele importului din CSV, pe fisiere cu forma pe care o au in realitate."""

from __future__ import annotations

import json

import pytest

from gestio import importer
from gestio.tools import books, clients, inventory, invoices


@pytest.fixture
def scrie(tmp_path):
    def _scrie(name: str, content: str):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _scrie


def test_numerele_romanesti_si_englezesti(scrie=None):
    assert importer.parse_number("1.234,56") == 1234.56
    assert importer.parse_number("1,234.56") == 1234.56
    assert importer.parse_number("1234.56") == 1234.56
    assert importer.parse_number("38,50") == 38.5
    assert importer.parse_number("1 200") == 1200
    assert importer.parse_number("125 lei") == 125
    assert importer.parse_number("", 0.0) == 0.0
    with pytest.raises(importer.ImportProblem):
        importer.parse_number("nu-i numar")


def test_datele_in_formatele_uzuale():
    assert importer.parse_date("2026-03-01") == "2026-03-01"
    assert importer.parse_date("01.03.2026") == "2026-03-01"
    assert importer.parse_date("01/03/2026") == "2026-03-01"
    with pytest.raises(importer.ImportProblem):
        importer.parse_date("martie")


def test_antetul_e_recunoscut_cu_diacritice_si_majuscule(scrie):
    path = scrie(
        "produse.csv",
        "Cod;Denumire;UM;Preț;Stoc;Cost unitar;Prag\n"
        "CIM-42;Ciment 42.5R;sac;38,50;400;26,00;50\n",
    )
    raport = importer.import_products(path)
    assert raport == {"importate": 1, "esuate": 0, "erori": []}

    produs = json.loads(inventory.cauta_produse(query="CIM-42"))["produse"][0]
    assert produs["stoc"] == 400
    assert produs["cost_mediu_ron"] == 26.0
    assert produs["pret_vanzare_ron"] == 38.5


def test_tipul_articolului_e_dedus_din_coloana_tip(scrie):
    path = scrie(
        "articole.csv",
        "cod,denumire,tip,pret,stoc,cost unitar\n"
        "CIM,Ciment,marfa,38.5,100,26\n"
        "MAN,Manusi,consumabile,0,50,7.5\n"
        "MON,Manopera,serviciu,95,,\n",
    )
    assert importer.import_products(path)["importate"] == 3

    tipuri = {p["sku"]: p["tip"] for p in json.loads(inventory.cauta_produse())["produse"]}
    assert tipuri == {"CIM": "marfa", "MAN": "consumabil", "MON": "serviciu"}

    balanta = {c["cont"]: c for c in json.loads(books.balanta_verificare())["conturi"]}
    assert balanta["371"]["rulaj_debitor_ron"] == 2600.0
    assert balanta["302"]["rulaj_debitor_ron"] == 375.0


def test_un_rand_gresit_nu_opreste_importul(scrie):
    path = scrie(
        "produse.csv",
        "cod,denumire,pret\nA,Bun,10\n,Fara cod,20\nB,Alt bun,nu-i pret\nC,Si asta,30\n",
    )
    raport = importer.import_products(path)
    assert raport["importate"] == 2  # A si C trec; randul fara cod si cel cu pret invalid cad
    assert raport["esuate"] == 2
    assert [e["rand"] for e in raport["erori"]] == [3, 4]


def test_importul_clientilor(scrie):
    path = scrie(
        "clienti.csv",
        "Client;CUI;Adresă;Email;Termen plată\n"
        "Alfa Construct SRL;RO12345678;Str. Fabricii 12;office@alfa.ro;30\n"
        "Beta Retail SA;RO87654321;Bd. Unirii 3;;45\n",
    )
    assert importer.import_clients(path)["importate"] == 2

    lista = json.loads(clients.cauta_clienti())["clienti"]
    assert {c["nume"] for c in lista} == {"Alfa Construct SRL", "Beta Retail SA"}
    assert lista[1]["termen_plata_zile"] == 45


def test_vanzarile_se_grupeaza_pe_numar_de_factura(scrie):
    importer.import_clients(scrie("c.csv", "client\nAlfa SRL\n"))
    importer.import_products(
        scrie("p.csv", "cod,denumire,pret,stoc,cost unitar\nCIM,Ciment,40,100,25\nGIP,Gips,42,100,28\n")
    )
    path = scrie(
        "vanzari.csv",
        "Numar;Data;Client;Cod;Cantitate;Pret\n"
        "F-101;15.02.2026;Alfa SRL;CIM;10;40\n"
        "F-101;15.02.2026;Alfa SRL;GIP;5;42\n"
        "F-102;20.02.2026;Alfa SRL;CIM;3;40\n",
    )
    raport = importer.import_sales(path)
    assert raport["importate"] == 2
    assert raport["esuate"] == 0

    facturi = json.loads(invoices.cauta_facturi())["facturi"]
    assert len(facturi) == 2
    prima = json.loads(invoices.detalii_factura(invoice_id=1))
    assert len(prima["linii"]) == 2
    assert prima["net_ron"] == 610.0  # 10x40 + 5x42
    assert prima["data_emiterii"] == "2026-02-15"

    produs = json.loads(inventory.cauta_produse(query="CIM"))["produse"][0]
    assert produs["stoc"] == 87


def test_vanzarile_marcate_incasate_se_sting(scrie):
    importer.import_clients(scrie("c.csv", "client\nAlfa SRL\n"))
    importer.import_products(scrie("p.csv", "cod,denumire,pret,stoc,cost unitar\nCIM,Ciment,40,100,25\n"))
    path = scrie(
        "vanzari.csv",
        "numar,data,client,cod,cantitate,pret,incasat\nF-1,2026-02-15,Alfa SRL,CIM,10,40,484\n",
    )
    assert importer.import_sales(path)["importate"] == 1
    assert json.loads(invoices.detalii_factura(invoice_id=1))["status"] == "achitata"


def test_vanzarea_fara_stoc_e_raportata_nu_aruncata(scrie):
    importer.import_clients(scrie("c.csv", "client\nAlfa SRL\n"))
    importer.import_products(scrie("p.csv", "cod,denumire,pret,stoc,cost unitar\nCIM,Ciment,40,5,25\n"))
    raport = importer.import_sales(
        scrie("v.csv", "numar,data,client,cod,cantitate,pret\nF-1,2026-02-15,Alfa SRL,CIM,50,40\n")
    )
    assert raport["importate"] == 0
    assert "Stoc insuficient" in raport["erori"][0]["eroare"]


def test_consumurile_se_grupeaza_pe_numar_de_bon(scrie):
    importer.import_products(
        scrie("p.csv", "cod,denumire,tip,pret,stoc,cost unitar\n"
                      "MAN,Manusi,consumabil,0,200,7.5\nCIM,Ciment,marfa,40,100,25\n")
    )
    path = scrie(
        "consumuri.csv",
        "Nr;Data;Cod;Cantitate;Centru cost;Motiv\n"
        "BC-1;10.03.2026;MAN;20;Santier Militari;Protectie\n"
        "BC-1;10.03.2026;CIM;4;Santier Militari;Turnare\n"
        "BC-2;12.03.2026;MAN;5;Atelier;Intretinere\n",
    )
    raport = importer.import_consumptions(path)
    assert raport == {"importate": 3, "esuate": 0, "erori": []}

    consum = json.loads(inventory.raport_consumuri())
    assert consum["total_consum_ron"] == 287.5  # 25x7,50 + 4x25
    centre = {c["centru"]: c["valoare_ron"] for c in consum["pe_centru_de_cost"]}
    assert centre == {"Santier Militari": 250.0, "Atelier": 37.5}

    balanta = {c["cont"]: c for c in json.loads(books.balanta_verificare())["conturi"]}
    assert balanta["602"]["rulaj_debitor_ron"] == 187.5
    assert balanta["607"]["rulaj_debitor_ron"] == 100.0


def test_fisierul_fara_coloana_obligatorie_e_respins(scrie):
    path = scrie("x.csv", "ceva,altceva\n1,2\n")
    with pytest.raises(importer.ImportProblem, match="sku"):
        importer.import_products(path)


def test_fisierul_gol_e_respins(scrie):
    with pytest.raises(importer.ImportProblem, match="gol"):
        importer.import_products(scrie("gol.csv", ""))
