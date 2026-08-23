"""Loop mechanics against a fake client — no network, no API key."""

import copy
from types import SimpleNamespace

import pytest

from jarvis import config
from jarvis.agent.loop import Agent
from jarvis.agent.registry import ToolRegistry


def block(**kwargs):
    return SimpleNamespace(**kwargs)


def message(content, stop_reason="end_turn"):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=None,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


class FakeStream:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self._response


class FakeClient:
    """Replays a scripted list of responses and records every request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **request):
        self.requests.append(copy.deepcopy(request))
        return FakeStream(self._responses.pop(0))


@pytest.fixture
def echo_calls():
    return []


@pytest.fixture
def registry(echo_calls):
    reg = ToolRegistry()
    reg.add(
        {"name": "echo", "description": "echo", "input_schema": {"type": "object"}},
        lambda payload: echo_calls.append(payload) or f"echoed {payload.get('text')}",
    )
    return reg


def test_plain_answer(registry):
    client = FakeClient([message([block(type="text", text="Listo.")])])
    agent = Agent(registry, client=client)
    assert agent.send("hola") == "Listo."


def test_tool_call_round_trip(registry, echo_calls):
    client = FakeClient(
        [
            message(
                [block(type="tool_use", id="t1", name="echo", input={"text": "hi"})],
                stop_reason="tool_use",
            ),
            message([block(type="text", text="Hecho.")]),
        ]
    )
    agent = Agent(registry, client=client)
    assert agent.send("echo hi") == "Hecho."
    assert echo_calls == [{"text": "hi"}]

    # the tool result went back as a user message keyed to the tool_use id
    result_msg = client.requests[1]["messages"][-1]
    assert result_msg["role"] == "user"
    assert result_msg["content"][0]["tool_use_id"] == "t1"
    assert result_msg["content"][0]["is_error"] is False


def test_tool_failure_comes_back_as_error_not_a_crash():
    reg = ToolRegistry()
    reg.add(
        {"name": "boom", "description": "b", "input_schema": {"type": "object"}},
        lambda _: (_ for _ in ()).throw(RuntimeError("disk on fire")),
    )
    client = FakeClient(
        [
            message(
                [block(type="tool_use", id="t1", name="boom", input={})],
                stop_reason="tool_use",
            ),
            message([block(type="text", text="Falló.")]),
        ]
    )
    assert Agent(reg, client=client).send("go") == "Falló."
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "disk on fire" in result["content"]


def test_pause_turn_resumes_without_tool_results(registry):
    client = FakeClient(
        [
            message([block(type="text", text="buscando")], stop_reason="pause_turn"),
            message([block(type="text", text="Encontrado.")]),
        ]
    )
    assert Agent(registry, client=client).send("busca") == "Encontrado."
    # second request must not have appended a tool_result turn
    assert client.requests[1]["messages"][-1]["role"] == "assistant"


def test_refusal_is_surfaced(registry):
    response = message([], stop_reason="refusal")
    response.stop_details = SimpleNamespace(explanation="policy", category="cyber")
    client = FakeClient([response])
    assert "declined" in Agent(registry, client=client).send("x")


def test_runaway_loop_is_capped(registry, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 3)
    looping = [
        message(
            [block(type="tool_use", id=f"t{i}", name="echo", input={"text": "x"})],
            stop_reason="tool_use",
        )
        for i in range(10)
    ]
    result = Agent(registry, client=FakeClient(looping)).send("loop")
    assert "stopped after 3 tool rounds" in result


def test_system_prompt_is_frozen_and_cached(registry):
    client = FakeClient(
        [message([block(type="text", text="a")]), message([block(type="text", text="b")])]
    )
    agent = Agent(registry, client=client)
    agent.send("uno")
    agent.send("dos")

    first, second = client.requests
    assert first["system"] == second["system"], "system prompt must be byte-identical"
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Current time" not in first["system"][0]["text"]


def test_volatile_context_goes_after_the_history(registry):
    client = FakeClient([message([block(type="text", text="a")])])
    agent = Agent(registry, client=client)
    agent.send("hola")
    messages = client.requests[0]["messages"]
    assert messages[-1]["role"] == "system"
    assert "Current time" in messages[-1]["content"]


def test_cache_breakpoints_stay_within_budget(registry):
    client = FakeClient([message([block(type="text", text=str(i))]) for i in range(6)])
    agent = Agent(registry, client=client)
    for i in range(6):
        agent.send(f"turno {i}")

    last = client.requests[-1]
    in_messages = sum(
        1
        for m in last["messages"]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and "cache_control" in b
    )
    in_system = sum(1 for b in last["system"] if "cache_control" in b)
    assert in_messages <= 3, "at most 3 rolling breakpoints in messages"
    assert in_messages + in_system <= 4, "the API allows 4 breakpoints total"
