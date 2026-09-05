"""Agentul: leaga modelul Claude de uneltele de contabilitate, clienti si stoc."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable

import anthropic

from . import config
from .tools import ALL_TOOLS

SYSTEM_PROMPT = f"""\
Esti asistentul de gestiune al firmei {config.COMPANY_NAME}. Te ocupi de trei lucruri:
contabilitate in partida dubla, evidenta clientilor si gestiunea stocului. Raspunzi
in limba romana, concis si la obiect, ca un contabil experimentat care vorbeste cu
patronul firmei.

Reguli de lucru:
- Nu inventa niciodata cifre. Orice numar pe care il spui trebuie sa vina dintr-o
  unealta pe care tocmai ai apelat-o. Daca nu ai datele, apeleaza unealta potrivita.
- Cand utilizatorul cere o operatiune (factura, receptie, incasare), executa-o cu
  uneltele, nu descrie doar cum s-ar face.
- O factura se construieste in trei pasi: `creeaza_factura`, apoi cate un
  `adauga_linie_factura` pentru fiecare pozitie, apoi `emite_factura`. Pana la
  emitere nimic nu atinge stocul sau contabilitatea.
- Inainte de o operatiune ireversibila care sterge valoare - `anuleaza_factura`,
  `ajusteaza_stoc` in minus - spune clar ce vei face si cere confirmarea, cu
  exceptia cazului in care utilizatorul a cerut-o deja explicit.
- Daca o unealta intoarce un camp `eroare`, explica problema in cuvinte simple si
  propune o solutie. Nu reincerca aceeasi comanda neschimbata.
- Sumele sunt in {config.CURRENCY}, fara TVA acolo unde uneltele cer valoarea neta.
  Cota standard de TVA este {config.DEFAULT_VAT_RATE}%.
- Datele calendaristice se scriu YYYY-MM-DD. Daca utilizatorul spune "azi", "ieri"
  sau "luna trecuta", calculeaza data efectiva inainte de a apela unealta.
- Cand prezinti mai multe randuri de date, foloseste un tabel scurt. Rotunjeste la
  doua zecimale si pune moneda o singura data, in capul coloanei.
- Semnaleaza din proprie initiativa ce vezi ingrijorator: facturi restante, stoc sub
  prag, marja negativa pe o vanzare.
"""


def _blocks(text: str) -> list[dict[str, Any]]:
    """Sistemul in doua blocuri: partea stabila se cacheaza, data curenta nu."""
    return [
        {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Data curenta este {date.today().isoformat()}."},
    ]


@dataclass
class ToolEvent:
    """Un apel de unealta, pentru afisare in interfata."""

    name: str
    arguments: dict[str, Any]


@dataclass
class Turn:
    """Rezultatul unei ture de conversatie."""

    text: str
    tool_calls: list[ToolEvent] = field(default_factory=list)
    stop_reason: str | None = None
    refused: bool = False


class GestioAgent:
    """Conversatie cu stare peste uneltele de gestiune.

    Istoricul e pastrat local, nu doar in interiorul rulatorului de unelte, ca sa
    poata continua intre ture si sa poata relua o tura intrerupta de `pause_turn`.
    """

    MAX_RESTARTS = 3

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        tools: Iterable[Any] | None = None,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model or config.MODEL
        self.tools = list(tools) if tools is not None else list(ALL_TOOLS)
        self.messages: list[dict[str, Any]] = []

    def reset(self) -> None:
        """Sterge istoricul conversatiei, pastrand baza de date neatinsa."""
        self.messages.clear()

    def ask(self, user_input: str, on_tool: Callable[[ToolEvent], None] | None = None) -> Turn:
        """Trimite o intrebare agentului si ruleaza uneltele pana la raspunsul final."""
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        calls: list[ToolEvent] = []
        chunks: list[str] = []

        try:
            last = self._run(calls, chunks, on_tool)
        except Exception:
            # O tura esuata nu are voie sa lase istoricul intr-o stare din care
            # cererea urmatoare ar fi respinsa de API.
            del self.messages[checkpoint:]
            raise

        if last is None:
            return Turn(text="Nu am primit niciun raspuns de la model.", tool_calls=calls)

        if last.stop_reason == "refusal":
            reason = getattr(getattr(last, "stop_details", None), "explanation", None)
            return Turn(
                text=f"Cererea a fost refuzata: {reason or 'motiv nespecificat'}",
                tool_calls=calls,
                stop_reason="refusal",
                refused=True,
            )

        return Turn(text="\n\n".join(chunks).strip(), tool_calls=calls, stop_reason=last.stop_reason)

    def _run(
        self,
        calls: list[ToolEvent],
        chunks: list[str],
        on_tool: Callable[[ToolEvent], None] | None,
    ):
        """Ruleaza uneltele pana la un mesaj final, reluand turele intrerupte."""
        last = None
        for _ in range(self.MAX_RESTARTS):
            runner = self.client.beta.messages.tool_runner(
                model=self.model,
                max_tokens=config.MAX_TOKENS,
                max_iterations=config.MAX_ITERATIONS,
                system=_blocks(SYSTEM_PROMPT),
                tools=self.tools,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": config.EFFORT},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            for message in runner:
                last = message
                # Istoricul e oglindit local: rulatorul isi tine propria copie, dar
                # nu o expune, iar fara ea nu am putea relua o tura pusa pe pauza.
                self.messages.append({"role": "assistant", "content": message.content})
                for block in message.content:
                    if block.type == "text" and block.text.strip():
                        chunks.append(block.text.strip())
                    elif block.type == "tool_use":
                        event = ToolEvent(name=block.name, arguments=dict(block.input or {}))
                        calls.append(event)
                        if on_tool:
                            on_tool(event)
                response = runner.generate_tool_call_response()
                if response is not None:
                    self.messages.append(response)

            if last is None or last.stop_reason != "pause_turn":
                break
        return last
