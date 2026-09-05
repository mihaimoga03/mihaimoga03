"""Configurare centrala, citita din mediu cu valori implicite rezonabile."""

from __future__ import annotations

import os

# Modelul folosit de agent. Poate fi schimbat prin GESTIO_MODEL.
MODEL = os.environ.get("GESTIO_MODEL", "claude-opus-5")

# Fisierul SQLite in care traieste toata contabilitatea.
DB_PATH = os.environ.get("GESTIO_DB", "gestio.db")

# Cota standard de TVA (procent intreg). In Romania: 21 standard, 11 redusa.
DEFAULT_VAT_RATE = int(os.environ.get("GESTIO_VAT_RATE", "21"))

# Termenul implicit de plata pentru clienti noi, in zile.
DEFAULT_PAYMENT_TERMS_DAYS = int(os.environ.get("GESTIO_PAYMENT_TERMS", "30"))

# Seria implicita de facturare.
INVOICE_SERIES = os.environ.get("GESTIO_INVOICE_SERIES", "FACT")

# Datele firmei, folosite in antetul rapoartelor.
COMPANY_NAME = os.environ.get("GESTIO_COMPANY", "Firma mea SRL")
CURRENCY = os.environ.get("GESTIO_CURRENCY", "RON")

# Nivelul de efort al modelului: low, medium, high, xhigh, max.
EFFORT = os.environ.get("GESTIO_EFFORT", "high")

# Numarul maxim de tokeni pentru un raspuns.
MAX_TOKENS = int(os.environ.get("GESTIO_MAX_TOKENS", "16000"))

# Cate iteratii de unelte poate face agentul intr-o singura tura.
MAX_ITERATIONS = int(os.environ.get("GESTIO_MAX_ITERATIONS", "40"))
