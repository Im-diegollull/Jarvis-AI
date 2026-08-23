"""Terminal rendering for the agent loop.

Streams thinking dim, answers bright, and tool calls as one-liners so it stays
readable while Claude works.
"""

import json

from jarvis.agent.loop import Events

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"

_MAX_ARG = 90


def _summarize(name: str, tool_input: dict) -> str:
    if name == "bash":
        if tool_input.get("restart"):
            return "restart"
        return str(tool_input.get("command", ""))
    if name in ("str_replace_based_edit_tool", "memory"):
        command = tool_input.get("command", "?")
        path = tool_input.get("path") or tool_input.get("old_path", "")
        return f"{command} {path}".strip()
    return json.dumps(tool_input, ensure_ascii=False)[:_MAX_ARG]


class ConsoleEvents(Events):
    def __init__(self) -> None:
        self._in_thinking = False
        self._wrote_text = False

    def on_turn_start(self) -> None:
        self._in_thinking = False

    def on_thinking(self, text: str) -> None:
        if not self._in_thinking:
            print(f"\n{DIM}  ┄ thinking ┄{RESET}")
            self._in_thinking = True
        print(f"{DIM}{text}{RESET}", end="", flush=True)

    def on_text(self, text: str) -> None:
        if self._in_thinking:
            print(f"\n{DIM}  ┄──────────┄{RESET}\n")
            self._in_thinking = False
        if not self._wrote_text:
            print()
            self._wrote_text = True
        print(text, end="", flush=True)

    def on_tool_start(self, name: str, tool_input: dict) -> None:
        if self._in_thinking:
            print(f"\n{DIM}  ┄──────────┄{RESET}")
            self._in_thinking = False
        summary = _summarize(name, tool_input)
        if len(summary) > _MAX_ARG:
            summary = summary[:_MAX_ARG] + "…"
        print(f"\n  {CYAN}▸{RESET} {BOLD}{name}{RESET} {DIM}{summary}{RESET}")

    def on_tool_end(self, name: str, result) -> None:
        colour = RED if result.is_error else GREEN
        first = (result.content or "").strip().splitlines()
        head = first[0] if first else ""
        if len(head) > _MAX_ARG:
            head = head[:_MAX_ARG] + "…"
        extra = f" (+{len(first) - 1} lines)" if len(first) > 1 else ""
        print(f"    {colour}└{RESET} {DIM}{head}{extra}{RESET}")

    def on_turn_end(self, usage) -> None:
        pass

    def finish(self) -> None:
        """Called after a full user turn completes."""
        if self._wrote_text:
            print("\n")
        self._wrote_text = False

    def report_usage(self, usage) -> None:
        if usage is None:
            print(f"  {DIM}No usage recorded yet.{RESET}\n")
            return
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        print(
            f"  {DIM}in {usage.input_tokens} · out {usage.output_tokens} · "
            f"cache read {cache_read} · cache write {cache_write}{RESET}\n"
        )
