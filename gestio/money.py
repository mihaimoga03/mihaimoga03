"""Aritmetica de bani.

Toate sumele sunt stocate ca numere intregi de bani (1 RON = 100 bani), niciodata
ca float. Conversia catre float se face doar la afisare.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def ron_to_bani(amount: float | int | str | Decimal) -> int:
    """Converteste o suma in RON la bani, rotunjind la cel mai apropiat ban."""
    return int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def bani_to_ron(bani: int) -> float:
    """Converteste bani in RON pentru afisare."""
    return round(bani / 100, 2)


def fmt(bani: int, currency: str = "RON") -> str:
    """Formateaza o suma pentru rapoarte: 1234567 -> '12.345,67 RON'."""
    sign = "-" if bani < 0 else ""
    whole, cents = divmod(abs(bani), 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{cents:02d} {currency}"


def vat_of(net_bani: int, vat_rate: int) -> int:
    """TVA aferent unei baze impozabile, rotunjit half-up la ban."""
    return int(
        (Decimal(net_bani) * Decimal(vat_rate) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def line_amounts(qty: float, unit_price_bani: int, vat_rate: int) -> tuple[int, int, int]:
    """Calculeaza (net, tva, total) in bani pentru o linie de factura."""
    net = int(
        (Decimal(str(qty)) * Decimal(unit_price_bani)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    tva = vat_of(net, vat_rate)
    return net, tva, net + tva
