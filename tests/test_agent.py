"""Teste pentru bucla agentului, cu un client fals - nu se apeleaza API-ul."""

from __future__ import annotations

from types import SimpleNamespace

from gestio.agent import GestioAgent
from gestio.tools import ALL_TOOLS


def block(**kwargs):
    return SimpleNamespace(**kwargs)


class FakeRunner:
    """Imita rulatorul de unelte: intoarce mesajele date, apoi se opreste."""

    def __init__(self, messages, tool_responses=None):
        self._messages = messages
        self._tool_responses = list(tool_responses or [])

    def __iter__(self):
        for message in self._messages:
            self._current = self._tool_responses.pop(0) if self._tool_responses else None
            yield message

    def generate_tool_call_response(self):
        return self._current


class FakeClient:
    def __init__(self, *runners):
        self.runners = list(runners)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._tool_runner))

    def _tool_runner(self, **kwargs):
        self.calls.append(kwargs)
        return self.runners.pop(0)


def test_uneltele_au_nume_unice_si_descrieri():
    names = [tool.name for tool in ALL_TOOLS]
    assert len(names) == len(set(names))
    for tool in ALL_TOOLS:
        assert tool.description and tool.description.strip()
        assert tool.input_schema["type"] == "object"


def test_agentul_aduna_textul_si_apelurile_de_unealta():
    messages = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[
                block(type="text", text="Verific stocul."),
                block(type="tool_use", name="raport_stoc", input={}),
            ],
        ),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[block(type="text", text="Ai 90 de saci de ciment.")],
        ),
    ]
    client = FakeClient(FakeRunner(messages, [{"role": "user", "content": "rezultat"}, None]))
    agent = GestioAgent(client=client, model="test-model")

    turn = agent.ask("cat ciment mai am?")

    assert turn.stop_reason == "end_turn"
    assert "Ai 90 de saci de ciment." in turn.text
    assert [call.name for call in turn.tool_calls] == ["raport_stoc"]
    assert agent.messages[0] == {"role": "user", "content": "cat ciment mai am?"}
    assert len(agent.messages) == 4  # user, assistant, tool_result, assistant


def test_agentul_reia_o_tura_intrerupta():
    paused = [SimpleNamespace(stop_reason="pause_turn", content=[block(type="text", text="...")])]
    finished = [SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="gata")])]
    client = FakeClient(FakeRunner(paused), FakeRunner(finished))
    agent = GestioAgent(client=client, model="test-model")

    turn = agent.ask("raport")

    assert turn.stop_reason == "end_turn"
    assert len(client.calls) == 2  # a fost pornit din nou dupa pause_turn


def test_refuzul_e_raportat_ca_atare():
    refused = [
        SimpleNamespace(
            stop_reason="refusal",
            content=[],
            stop_details=SimpleNamespace(explanation="motiv de politica"),
        )
    ]
    agent = GestioAgent(client=FakeClient(FakeRunner(refused)), model="test-model")

    turn = agent.ask("ceva")

    assert turn.refused is True
    assert "motiv de politica" in turn.text


def test_cererea_contine_uneltele_si_promptul_de_sistem():
    messages = [SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="ok")])]
    client = FakeClient(FakeRunner(messages))
    GestioAgent(client=client, model="test-model").ask("salut")

    request = client.calls[0]
    assert request["tools"] == list(ALL_TOOLS)
    assert request["thinking"] == {"type": "adaptive"}
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Data curenta" in request["system"][1]["text"]
    assert request["fallbacks"] == "default"


def test_reset_sterge_doar_conversatia():
    messages = [SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="ok")])]
    agent = GestioAgent(client=FakeClient(FakeRunner(messages)), model="test-model")
    agent.ask("salut")
    assert agent.messages

    agent.reset()
    assert agent.messages == []


def test_o_tura_esuata_nu_lasa_istoricul_stricat():
    class Exploding:
        def __init__(self):
            self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._boom))

        def _boom(self, **_kwargs):
            raise RuntimeError("conexiune intrerupta")

    agent = GestioAgent(client=Exploding(), model="test-model")
    try:
        agent.ask("salut")
    except RuntimeError:
        pass
    else:
        raise AssertionError("eroarea trebuia sa se propage")

    assert agent.messages == []
