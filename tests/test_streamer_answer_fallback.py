"""An empty reply must be distinguishable from a discarded one — in the LOG.

`stream_agent_turn` clears `final_text` at a tool boundary, because text written
before a tool call is normally narration ("let me check the schema first") and
must not be persisted as the answer. That is right, and these tests pin it.

What was missing is that a turn which then produced NO answer reported `""`, and
the caller could not tell "the agent said nothing" from "the agent said
something and we dropped it". Those need opposite repairs, and PrepCrest's
authoring batch picked the wrong one for five rounds.

The fix is a record and a warning, NOT a substitution. Putting the dropped text
into the answer was considered and rejected: the answer flows into message.end,
into persisted history and into every surface's parser, and the tutor's client
refuses mid-turn text on purpose — "half a turn is not a degraded answer, it is
an answer that could parse into the wrong decision". So every assertion below
about `final_text` is an assertion that behaviour did NOT change.
"""

import asyncio

from api.services.agent_streamer import stream_agent_turn


PAYLOAD = '<<PREPCREST\n{"questions":[{"stem":"What is 2+2?"}]}\nPREPCREST>>'


class _Bus:
    def __init__(self):
        self._subs = {}

    def subscribe(self, event, cb):
        self._subs.setdefault(event, []).append(cb)

    def unsubscribe(self, event, cb):
        self._subs.get(event, []).remove(cb)

    async def publish(self, event, payload):
        for cb in list(self._subs.get(event, [])):
            await cb(payload)


class _Agent:
    """An agent whose turn is a fixed script of events."""

    def __init__(self, script):
        self.event_bus = _Bus()
        self._script = script

    async def _process_input(self, _payload):
        for event, data in self._script:
            await self.event_bus.publish(event, data)


def _run(script):
    """Returns the whole state, so a test can assert on the answer AND the
    diagnosis without two harnesses."""
    state = {"final_text": ""}

    async def drive():
        async for _ in stream_agent_turn(
                _Agent(script), "go", lambda k, **kw: f"{k}\n", state,
                timeout_s=5, log_ctx="test"):
            pass

    asyncio.run(drive())
    return state


_TOOL_CALL = [
    ("tool_start", {"tool_name": "skills_list", "tool_args": {}}),
    ("tool_end", {"tool_name": "skills_list"}),
]


# ── behaviour that must NOT change ───────────────────────────────────────

def test_text_written_before_a_tool_call_is_still_discarded():
    # The clear is the point of the mechanism, not a bug. An agent that narrates
    # "let me check the schema" and then acts must not persist the narration.
    assert _run([
        ("agent_token", {"delta": "Let me check the schema first."}),
        *_TOOL_CALL,
        ("agent_token", {"delta": "The answer is 4."}),
        ("agent_response", {"message": "The answer is 4."}),
    ])["final_text"] == "The answer is 4."


def test_a_turn_with_no_answer_after_its_tools_still_reports_empty():
    # THE assertion that this fix changed no contract. The dropped text is
    # recorded and logged; it is not substituted for the answer, because the
    # answer is read by three surfaces and one of them parses it for decisions.
    assert _run([
        ("agent_token", {"delta": PAYLOAD}),
        *_TOOL_CALL,
    ])["final_text"] == ""


def test_a_plain_turn_with_no_tools_is_untouched():
    assert _run([
        ("agent_token", {"delta": "Hello."}),
        ("agent_response", {"message": "Hello."}),
    ])["final_text"] == "Hello."


def test_the_agents_own_verdict_is_left_alone():
    # "[Agent reached the iteration limit]" is a real answer and a real failure.
    assert _run([
        ("agent_token", {"delta": PAYLOAD}),
        *_TOOL_CALL,
        ("agent_response", {"message": "[Agent reached 150 iteration limit]"}),
    ])["final_text"] == "[Agent reached 150 iteration limit]"


def test_a_turn_that_streamed_nothing_is_untouched():
    state = _run([("agent_response", {"message": "Hi."})])
    assert state["final_text"] == "Hi."
    assert not state.get("dropped_at_tool_chars")


# ── the diagnosis that was missing ───────────────────────────────────────

def test_the_discarded_length_is_recorded_so_the_silence_is_explainable():
    state = _run([
        ("agent_token", {"delta": PAYLOAD}),
        *_TOOL_CALL,
    ])

    assert state["final_text"] == ""
    assert state["dropped_at_tool_chars"] == len(PAYLOAD)


def test_a_turn_that_genuinely_said_nothing_records_nothing():
    # No invention: the record exists only for text that actually existed, so
    # the warning cannot cry wolf on a turn that really was silent.
    state = _run(_TOOL_CALL)

    assert state["final_text"] == ""
    assert not state.get("dropped_at_tool_chars")
