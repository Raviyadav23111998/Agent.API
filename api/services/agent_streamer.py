"""
Shared agent-turn streamer — single source of truth for event→SSE mapping.
═══════════════════════════════════════════════════════════════════════════

Both chat_service (web / VS Code) and bot_service (embeddable widget) ran their
own near-identical copy of "subscribe to the agent's EventBus, run the turn,
drain the queue into SSE frames". They DRIFTED: chat gained plan/citations/cost
+ camelCase fields; the bot path was left behind. This module is the one place
that mapping lives, so a new event/field reaches every surface at once.

Contract:
  - The CALLER emits `message.start` (before) and `message.end` (after) — they
    differ slightly per surface (persistence, extra fields).
  - This generator yields every in-turn frame (camelCase fields) and writes the
    final answer to `state["final_text"]` (only the text AFTER the last tool
    batch — intermediate "let me try X" reasoning is streamed live but excluded
    from the persisted answer).
  - `final_usage_fields(agent)` builds the shared message.end usage (cost meter)
    so both surfaces report it identically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict

logger = logging.getLogger("agent.streamer")

_AGENT_EVENTS = ("agent_response", "agent_token", "agent_thinking",
                 "agent_activity", "tool_start", "tool_end",
                 "approval_request", "plan", "citations", "artifact")

_DELTA_CHUNK = 20


async def stream_agent_turn(agent: Any, user_input: str, sse: Callable[..., str],
                            state: Dict[str, Any], *, timeout_s: int = 3600,
                            ping_every: int = 10, log_ctx: str = "",
                            include_thinking: bool = True,
                            attachments: list = None):
    """Run one agent turn, yielding SSE frames. Populates state['final_text'].

    Does NOT emit message.start/message.end (callers own those + persistence).

    include_thinking: when False, the model's reasoning ("thinking") deltas are
    NOT forwarded — used for the customer-facing chat-bot widget, where exposing
    the agent's internal reasoning is undesirable. The answer still streams.
    """
    q: asyncio.Queue = asyncio.Queue()
    subs: Dict[str, Callable] = {}

    def _make(kind: str):
        async def _cb(payload):
            await q.put((kind, payload))
        return _cb

    for ev in _AGENT_EVENTS:
        cb = _make(ev)
        subs[ev] = cb
        agent.event_bus.subscribe(ev, cb)

    state.setdefault("final_text", "")
    msg_streamed = False

    try:
        _payload = {"user_input": user_input}
        if attachments:
            _payload["attachments"] = attachments
        task = asyncio.create_task(agent._process_input(_payload))
        elapsed = 0

        while not task.done() or not q.empty():
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if task.done():
                    break
                elapsed += 1
                if elapsed >= timeout_s:
                    yield sse("error",
                              message="Response timed out. Please try again with a simpler question.")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    return
                if elapsed % ping_every == 0:
                    yield sse("ping", elapsed=elapsed)
                continue

            if kind == "agent_token":
                delta = payload.get("delta", "")
                if delta:
                    state["final_text"] += delta
                    msg_streamed = True
                    yield sse("message.delta", content=delta)
            elif kind == "agent_thinking":
                delta = payload.get("delta", "")
                if delta and include_thinking:
                    yield sse("thinking.delta", content=delta)
            elif kind == "agent_activity":
                label = payload.get("label", "")
                if label:
                    yield sse("activity", label=label)
            elif kind == "agent_response":
                text = payload.get("message", "")
                if msg_streamed:
                    state["final_text"] = text
                    msg_streamed = False
                elif text:
                    state["final_text"] += text
                    for i in range(0, len(text), _DELTA_CHUNK):
                        yield sse("message.delta", content=text[i:i + _DELTA_CHUNK])
            elif kind == "tool_start":
                # Text written before a tool call is normally narration — "let
                # me check the schema first" — and must not become the persisted
                # answer. That is what this clear is for, and it stays.
                #
                # Its LENGTH is remembered, and deliberately not its content.
                #
                # A turn that ends here reports "" and the caller cannot tell
                # "the agent said nothing" from "the agent said something we
                # dropped" — those need opposite repairs, and PrepCrest's batch
                # picked the wrong one for five rounds. So the fact is recorded.
                #
                # Substituting the dropped text for the answer was the obvious
                # next step and is NOT taken, because the answer flows into
                # message.end, into persisted history and into every surface's
                # parser. The tutor decides whether a lesson was agreed from a
                # control block at the end of a reply, and mid-turn text is
                # exactly what its client refuses on purpose: "half a turn is not
                # a degraded answer — it is an answer that could parse into the
                # wrong decision." A diagnosis belongs in the log; it does not
                # belong in a contract three surfaces read.
                if state["final_text"]:
                    state["dropped_at_tool_chars"] = len(state["final_text"])
                state["final_text"] = ""
                msg_streamed = False
                yield sse("tool.start",
                          toolName=payload.get("tool_name"),
                          toolArgs=payload.get("tool_args", {}))
            elif kind == "tool_end":
                yield sse("tool.end", toolName=payload.get("tool_name"))
            elif kind == "approval_request":
                yield sse("approval.request",
                          approvalId=payload.get("approval_id"),
                          toolName=payload.get("tool_name"),
                          toolArgs=payload.get("tool_args", {}),
                          timeout_s=payload.get("timeout_s"))
            elif kind == "plan":
                yield sse("plan", steps=payload.get("steps", []))
            elif kind == "citations":
                yield sse("citations", sources=payload.get("sources", []))
            elif kind == "artifact":
                # Part 2 — media the model generated (image/audio/video). Surface
                # it live and record the file id so the caller can bind it to the
                # assistant message after the turn.
                fid = payload.get("file_id")
                if fid is not None:
                    state.setdefault("artifacts", []).append(fid)
                    yield sse("artifact", fileId=fid, kind=payload.get("kind"),
                              mediaType=payload.get("media_type"))

        if task.done() and not task.cancelled() and task.exception():
            exc = task.exception()
            logger.error("agent task failed (%s): %s", log_ctx, exc)
            yield sse("error", message=f"Agent error: {exc}")
        elif not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        for ev, cb in subs.items():
            agent.event_bus.unsubscribe(ev, cb)

        # The one case that is silent and should not be: the turn answered
        # nothing, but it HAD written something that a tool call discarded.
        # Nothing is changed about what the caller receives — this only stops
        # the next person debugging an empty reply from starting where the
        # PrepCrest batch started, at "the agent returned nothing", which was
        # never true and cost five rounds to disprove.
        _dropped = state.get("dropped_at_tool_chars") or 0
        if not state.get("final_text") and _dropped:
            logger.warning(
                "turn produced no answer after its tool calls (%s); %d characters "
                "were written before the first of them and discarded at the tool "
                "boundary — the reply is empty because it was cleared, not "
                "because the model was silent",
                log_ctx, _dropped)


def final_usage_fields(agent: Any) -> dict:
    """Shared message.end usage fields (token + cost meter) — identical on
    every surface."""
    return {
        "conversationTokens": int(getattr(agent, "_conversation_tokens_used", 0) or 0),
        "conversationCostUsd": round(
            float(getattr(agent, "_conversation_cost_usd", 0.0) or 0.0), 6),
    }
