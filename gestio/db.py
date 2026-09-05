"""Stratul de persistenta: SQLite, schema si tranzactii."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    cui                 TEXT UNIQUE,
    reg_com             TEXT,
    address             TEXT,
    email               TEXT,
    phone               TEXT,
    payment_terms_days  INTEGER NOT NULL DEFAULT 30,
    active              INTEGER NOT NULL DEFAULT 1,
    note                TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    cui         TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sku               TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    unit              TEXT NOT NULL DEFAULT 'buc',
    vat_rate          INTEGER NOT NULL,
    sale_price_bani   INTEGER NOT NULL DEFAULT 0,
    stock_qty         REAL NOT NULL DEFAULT 0,
    avg_cost_bani     INTEGER NOT NULL DEFAULT 0,
    reorder_level     REAL NOT NULL DEFAULT 0,
    kind              TEXT NOT NULL DEFAULT 'marfa'
                          CHECK (kind IN ('marfa','consumabil','serviciu')),
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL REFERENCES products(id),
    date             TEXT NOT NULL,
    kind             TEXT NOT NULL
                         CHECK (kind IN ('receptie','iesire','consum','ajustare','stornare')),
    qty              REAL NOT NULL,
    unit_cost_bani   INTEGER NOT NULL,
    value_bani       INTEGER NOT NULL,
    balance_qty      REAL NOT NULL,
    ref_type         TEXT,
    ref_id           INTEGER,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consumptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       INTEGER,
    date         TEXT NOT NULL,
    cost_center  TEXT,
    reason       TEXT,
    value_bani   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consumption_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    consumption_id  INTEGER NOT NULL REFERENCES consumptions(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    qty             REAL NOT NULL,
    unit_cost_bani  INTEGER NOT NULL,
    value_bani      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    doc_no        TEXT,
    date          TEXT NOT NULL,
    net_bani      INTEGER NOT NULL,
    vat_bani      INTEGER NOT NULL,
    total_bani    INTEGER NOT NULL,
    paid_bani     INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    series       TEXT NOT NULL,
    number       INTEGER,
    client_id    INTEGER NOT NULL REFERENCES clients(id),
    issue_date   TEXT NOT NULL,
    due_date     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('ciorna','emisa','partial','achitata','anulata')),
    net_bani     INTEGER NOT NULL DEFAULT 0,
    vat_bani     INTEGER NOT NULL DEFAULT 0,
    total_bani   INTEGER NOT NULL DEFAULT 0,
    paid_bani    INTEGER NOT NULL DEFAULT 0,
    cogs_bani    INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (series, number)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id        INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    product_id        INTEGER REFERENCES products(id),
    description       TEXT NOT NULL,
    qty               REAL NOT NULL,
    unit_price_bani   INTEGER NOT NULL,
    vat_rate          INTEGER NOT NULL,
    net_bani          INTEGER NOT NULL,
    vat_bani          INTEGER NOT NULL,
    total_bani        INTEGER NOT NULL,
    cogs_bani         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id   INTEGER REFERENCES invoices(id),
    purchase_id  INTEGER REFERENCES purchases(id),
    direction    TEXT NOT NULL CHECK (direction IN ('incasare','plata')),
    date         TEXT NOT NULL,
    amount_bani  INTEGER NOT NULL,
    method       TEXT NOT NULL CHECK (method IN ('banca','numerar')),
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    ref_type      TEXT NOT NULL,
    ref_id        INTEGER,
    description   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id    INTEGER NOT NULL REFERENCES journal(id) ON DELETE CASCADE,
    account       TEXT NOT NULL,
    debit_bani    INTEGER NOT NULL DEFAULT 0,
    credit_bani   INTEGER NOT NULL DEFAULT 0,
    description   TEXT
);

CREATE INDEX IF NOT EXISTS idx_moves_product ON stock_moves(product_id, date);
CREATE INDEX IF NOT EXISTS idx_lines_invoice ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_journal_date  ON journal(date);
CREATE INDEX IF NOT EXISTS idx_jlines_acct   ON journal_lines(account);
CREATE INDEX IF NOT EXISTS idx_inv_client    ON invoices(client_id, status);
CREATE INDEX IF NOT EXISTS idx_cons_date     ON consumptions(date);
CREATE INDEX IF NOT EXISTS idx_clines_cons   ON consumption_lines(consumption_id);
"""

_local = threading.local()


def connect(path: str | None = None) -> sqlite3.Connection:
    """Deschide (si initializeaza) baza de date. Conexiunea e per-thread."""
    db_path = path or config.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_conn() -> sqlite3.Connection:
    """Conexiunea implicita a procesului, creata la prima utilizare."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def set_conn(conn: sqlite3.Connection) -> None:
    """Injecteaza o conexiune (folosit de teste, care ruleaza pe :memory:)."""
    _local.conn = conn


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    """Grupeaza scrierile: totul se comite impreuna sau nimic."""
    conn = conn or get_conn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    """Transforma un cursor in lista de dictionare, gata de serializat."""
    return [dict(r) for r in cur.fetchall()]


def one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict[str, Any] | None:
    """Prima linie a unei interogari, sau None."""
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None
