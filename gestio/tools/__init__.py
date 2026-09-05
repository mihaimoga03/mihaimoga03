"""Colectia de unelte pe care agentul le poate apela."""

from __future__ import annotations

from . import books, clients, inventory, invoices

ALL_TOOLS = [*clients.TOOLS, *inventory.TOOLS, *invoices.TOOLS, *books.TOOLS]

__all__ = ["ALL_TOOLS", "books", "clients", "inventory", "invoices"]
