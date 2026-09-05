"""Ajutoare comune pentru uneltele agentului."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .. import config
from ..db import get_conn
from ..money import bani_to_ron


class ToolError(Exception):
    """Eroare de business, raportata agentului ca text, nu ca exceptie."""


def conn() -> sqlite3.Connection:
    return get_conn()


def out(payload: Any) -> str:
    """Serializeaza rezultatul unei unelte. Agentul primeste JSON, nu obiecte."""
    return json.dumps(payload, ensure_ascii=False, default=str)


def today() -> str:
    return date.today().isoformat()


def parse_date(value: str | None, *, default: str | None = None) -> str:
    """Valideaza o data ISO (YYYY-MM-DD). Gol => `default` sau ziua curenta."""
    if not value:
        return default or today()
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ToolError(f"Data '{value}' nu e in formatul YYYY-MM-DD.") from None


def add_days(iso_date: str, days: int) -> str:
    return (datetime.strptime(iso_date, "%Y-%m-%d").date() + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    d1 = datetime.strptime(start, "%Y-%m-%d").date()
    d2 = datetime.strptime(end, "%Y-%m-%d").date()
    return (d2 - d1).days


def period(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Normalizeaza un interval; implicit anul curent pana azi."""
    start = parse_date(date_from, default=f"{date.today().year}-01-01")
    end = parse_date(date_to, default=today())
    if start > end:
        raise ToolError("Data de inceput e dupa data de sfarsit.")
    return start, end


def ron(bani: int) -> float:
    """Suma in RON, pentru payload-urile intoarse agentului."""
    return bani_to_ron(bani)


def money_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Converteste orice cheie `*_bani` in echivalentul ei in RON."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key.endswith("_bani") and isinstance(value, int):
            result[key[: -len("_bani")] + "_ron"] = ron(value)
        else:
            result[key] = value
    return result


def require_vat_rate(vat_rate: int | None) -> int:
    rate = config.DEFAULT_VAT_RATE if vat_rate is None else int(vat_rate)
    if rate < 0 or rate > 100:
        raise ToolError("Cota de TVA trebuie sa fie intre 0 si 100.")
    return rate


def safe(fn):
    """Transforma erorile de business in raspunsuri, nu in exceptii.

    Agentul poate corecta o eroare descrisa in text (client inexistent, stoc
    insuficient); o exceptie ar opri bucla. Erorile neasteptate se propaga.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError as exc:
            return out({"eroare": str(exc)})
        except (sqlite3.IntegrityError, ValueError) as exc:
            return out({"eroare": f"{type(exc).__name__}: {exc}"})

    return wrapper
