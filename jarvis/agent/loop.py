"""The agentic loop.

A manual loop rather than the SDK tool runner, because we need three things the
runner does not expose cleanly: per-token streaming so F3 can start speaking
before the turn ends, an approval gate in front of each tool call, and explicit
``pause_turn`` handling for the server-side web tools.
"""

import anthropic

from jarvis import config
from jarvis.agent import prompt as prompt_module
from jarvis.agent.registry import ToolRegistry

# Server-side refusal fallbacks: if a safety classifier declines a turn,
# Anthropic reroutes it instead of handing us an empty response.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Events:
    """Callbacks the UI layer can override. Defaults are silent."""

    def on_thinking(self, text: str) -> None: ...
    def on_text(self, text: str) -> None: ...
    def on_turn_start(self) -> None: ...
    def on_turn_end(self, usage) -> None: ...
    def on_tool_start(self, name: str, tool_input: dict) -> None: ...
    def on_tool_end(self, name: str, result) -> None: ...


class Agent:
    def __init__(
        self,
        registry: ToolRegistry,
        events: Events | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.registry = registry
        self.events = events or Events()
        self.client = client or anthropic.Anthropic()
        self.messages: list[dict] = []
        self.system_messages_supported = True
        self.last_usage = None

    # ── public API ───────────────────────────────────────────────────────────

    def send(self, user_input: str) -> str:
        """Send one user turn and run the loop until Claude stops calling tools."""
        self.messages.append(
            {"role": "user", "content": [{"type": "text", "text": user_input}]}
        )
        self._inject_context()
        return self._run()

    def reset(self) -> None:
        self.messages.clear()

    # ── loop ─────────────────────────────────────────────────────────────────

    def _run(self) -> str:
        for _ in range(config.MAX_TOOL_ROUNDS):
            response = self._turn()
            self.messages.append({"role": "assistant", "content": response.content})
            self.last_usage = response.usage
            self.events.on_turn_end(response.usage)

            if response.stop_reason == "pause_turn":
                # A server tool ran long; resend to let it continue.
                continue

            if response.stop_reason == "refusal":
                detail = getattr(response, "stop_details", None)
                reason = getattr(detail, "explanation", None) or "no explanation given"
                return f"I can't help with that one — the request was declined ({reason})."

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return self._text_of(response)

            self.messages.append({"role": "user", "content": self._execute(tool_uses)})

        return (
            f"I stopped after {config.MAX_TOOL_ROUNDS} tool rounds without finishing. "
            f"Something is looping — check ~/.jarvis/logs/tools.jsonl."
        )

    def _turn(self):
        self._apply_cache_breakpoints()
        request = {
            "model": config.MODEL,
            "max_tokens": config.MAX_TOKENS,
            "system": [
                {
                    "type": "text",
                    "text": prompt_module.SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": config.EFFORT},
            "tools": self.registry.definitions(),
            "messages": self.messages,
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }

        self.events.on_turn_start()
        with self.client.beta.messages.stream(**request) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "thinking_delta":
                    self.events.on_thinking(event.delta.thinking)
                elif event.delta.type == "text_delta":
                    self.events.on_text(event.delta.text)
            return stream.get_final_message()

    def _execute(self, tool_uses: list) -> list[dict]:
        results = []
        for block in tool_uses:
            self.events.on_tool_start(block.name, block.input)
            result = self.registry.dispatch(block.name, block.input)
            self.events.on_tool_end(block.name, result)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result.content or "(no output)",
                    "is_error": result.is_error,
                }
            )
        return results

    # ── context & caching ────────────────────────────────────────────────────

    def _inject_context(self) -> None:
        """Append per-turn context as an operator message after the history.

        Putting it here rather than in the system prompt keeps the cached
        prefix byte-identical across turns.
        """
        context = prompt_module.volatile_context()
        if not self.system_messages_supported:
            self.messages[-1]["content"].insert(
                0, {"type": "text", "text": f"<context>\n{context}\n</context>"}
            )
            return
        self.messages.append({"role": "system", "content": context})

    def _apply_cache_breakpoints(self, keep: int = 2) -> None:
        """Keep a rolling set of breakpoints on the most recent turns.

        The API allows four; one is spent on the system block, so we keep two
        here and leave headroom.
        """
        marked = 0
        for message in reversed(self.messages):
            content = message.get("content")
            if not isinstance(content, list) or not content:
                continue
            block = content[-1]
            if not isinstance(block, dict):
                continue  # SDK response object — leave it alone
            if marked < keep:
                block["cache_control"] = {"type": "ephemeral"}
                marked += 1
            else:
                block.pop("cache_control", None)

    @staticmethod
    def _text_of(response) -> str:
        parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(p for p in parts if p.strip()) or "(no reply)"


def build_registry() -> ToolRegistry:
    """The F1 tool surface: shell, files, memory, web."""
    from jarvis.agent import memory
    from jarvis.tools import files, shell, web

    registry = ToolRegistry()
    shell.register(registry)
    files.register(registry)
    memory.register(registry)
    web.register(registry)
    return registry
