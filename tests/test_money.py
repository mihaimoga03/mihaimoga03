from gestio.money import bani_to_ron, fmt, line_amounts, ron_to_bani, vat_of


def test_conversia_nu_pierde_bani():
    assert ron_to_bani("19.99") == 1999
    assert ron_to_bani(0.1 + 0.2) == 30  # float murdar, rezultat curat
    assert bani_to_ron(1999) == 19.99


def test_tva_se_rotunjeste_half_up():
    assert vat_of(10000, 21) == 2100
    assert vat_of(1, 21) == 0  # 0.21 bani -> 0
    assert vat_of(3, 21) == 1  # 0.63 bani -> 1


def test_linia_de_factura_se_aduna_corect():
    net, tva, total = line_amounts(3, 3850, 21)
    assert (net, tva) == (11550, 2426)
    assert total == net + tva


def test_formatarea_pentru_rapoarte():
    assert fmt(123456789) == "1.234.567,89 RON"
    assert fmt(-500) == "-5,00 RON"
