"""Interfata de linie de comanda pentru agentul Gestio."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import config
from .db import get_conn

BANNER = """\
Gestio - asistent de contabilitate, clienti si stoc
Baza de date: {db}   |   Model: {model}   |   TVA standard: {vat}%
Scrie intrebarea ta. Comenzi: /reset (sterge conversatia), /unelte, /iesire.
"""


def _agent():
    """Importa agentul tarziu, ca `gestio unelte` sa mearga fara cheie de API."""
    from .agent import GestioAgent

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "Atentie: nu am gasit ANTHROPIC_API_KEY in mediu. Daca ai rulat"
            " `ant auth login`, profilul salvat va fi folosit automat.",
            file=sys.stderr,
        )
    return GestioAgent()


def _print_turn(turn) -> None:
    if turn.text:
        print(f"\n{turn.text}\n")
    elif turn.tool_calls:
        print("\n(Am executat operatiunile, dar modelul nu a intors text.)\n")


def cmd_chat(_args: argparse.Namespace) -> int:
    agent = _agent()
    print(BANNER.format(db=config.DB_PATH, model=agent.model, vat=config.DEFAULT_VAT_RATE))
    while True:
        try:
            line = input("tu > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/iesire", "/exit", "/quit"):
            return 0
        if line == "/reset":
            agent.reset()
            print("Conversatia a fost stearsa. Datele raman neschimbate.\n")
            continue
        if line == "/unelte":
            for tool in agent.tools:
                print(f"  {tool.name}")
            print()
            continue
        try:
            turn = agent.ask(line, on_tool=lambda e: print(f"  ... {e.name}({_short(e.arguments)})"))
        except Exception as exc:  # o eroare de retea nu are voie sa incheie sesiunea
            print(f"\nEroare: {_explain(exc)}\n", file=sys.stderr)
            continue
        _print_turn(turn)


def _explain(exc: Exception) -> str:
    """Mesaj scurt si util pentru cele mai frecvente erori de API."""
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "cheie de API invalida sau lipsa. Seteaza ANTHROPIC_API_KEY sau ruleaza `ant auth login`."
    if isinstance(exc, anthropic.RateLimitError):
        return "limita de rata atinsa; incearca peste cateva secunde."
    if isinstance(exc, anthropic.APIConnectionError):
        return "nu am putut contacta API-ul; verifica conexiunea la internet."
    if isinstance(exc, anthropic.APIStatusError):
        return f"API a raspuns cu {exc.status_code}: {exc.message}"
    return f"{type(exc).__name__}: {exc}"


def _short(arguments: dict) -> str:
    text = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    return text if len(text) <= 90 else text[:87] + "..."


def cmd_ask(args: argparse.Namespace) -> int:
    agent = _agent()
    try:
        turn = agent.ask(" ".join(args.intrebare))
    except Exception as exc:
        print(f"Eroare: {_explain(exc)}", file=sys.stderr)
        return 1
    _print_turn(turn)
    return 1 if turn.refused else 0


def cmd_tools(_args: argparse.Namespace) -> int:
    from .tools import ALL_TOOLS

    for tool in ALL_TOOLS:
        first_line = (tool.description or "").strip().splitlines()[0]
        print(f"{tool.name:26} {first_line}")
    print(f"\n{len(ALL_TOOLS)} unelte disponibile.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from .seed import seed

    summary = seed(reset=args.reset)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    """Interogare directa, doar pentru citire - utila la depanare."""
    query = " ".join(args.query)
    if not query.lower().lstrip().startswith("select"):
        print("Sunt permise doar interogari SELECT.", file=sys.stderr)
        return 2
    for row in get_conn().execute(query).fetchall():
        print(json.dumps(dict(row), ensure_ascii=False, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gestio", description="Agent de contabilitate, clienti si stoc.")
    sub = parser.add_subparsers(dest="comanda")

    sub.add_parser("chat", help="Conversatie interactiva cu agentul.").set_defaults(func=cmd_chat)

    ask = sub.add_parser("ask", help="O singura intrebare, raspuns si iesire.")
    ask.add_argument("intrebare", nargs="+")
    ask.set_defaults(func=cmd_ask)

    sub.add_parser("unelte", help="Listeaza uneltele disponibile.").set_defaults(func=cmd_tools)

    seed = sub.add_parser("seed", help="Populeaza baza de date cu date demonstrative.")
    seed.add_argument("--reset", action="store_true", help="Sterge intai baza de date existenta.")
    seed.set_defaults(func=cmd_seed)

    sql = sub.add_parser("sql", help="Ruleaza un SELECT direct pe baza de date.")
    sql.add_argument("query", nargs="+")
    sql.set_defaults(func=cmd_sql)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_chat(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
