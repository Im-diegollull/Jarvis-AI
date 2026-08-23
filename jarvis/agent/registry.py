"""Tool registry: maps API tool definitions to local handlers.

Three kinds of tool live here:

* **Anthropic-defined client tools** (``bash``, ``str_replace_based_edit_tool``,
  ``memory``) — declared by ``type``/``name`` only, no ``input_schema``, executed
  by us.
* **Server tools** (``web_search``, ``web_fetch``) — declared and run on
  Anthropic's side; they never reach :meth:`ToolRegistry.dispatch`.
* **Custom tools** — our own, with a JSON schema. Arrive in F4.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis import config
from jarvis.agent.approval import Denied

Handler = Callable[[dict], str]


@dataclass(slots=True)
class Tool:
    definition: dict
    handler: Handler | None = None

    @property
    def name(self) -> str:
        return self.definition["name"]

    @property
    def server_side(self) -> bool:
        return self.handler is None


@dataclass(slots=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def add(self, definition: dict, handler: Handler | None = None) -> None:
        self.register(Tool(definition=definition, handler=handler))

    def definitions(self) -> list[dict]:
        """Definitions in a stable order — reordering would break the cache."""
        return [self.tools[name].definition for name in sorted(self.tools)]

    def dispatch(self, name: str, tool_input: dict) -> ToolResult:
        """Run a tool call. Never raises: failures come back as error results."""
        started = time.monotonic()
        tool = self.tools.get(name)

        if tool is None or tool.handler is None:
            result = ToolResult(f"Unknown tool: {name}", is_error=True)
        else:
            try:
                result = ToolResult(tool.handler(tool_input))
            except Denied as exc:
                result = ToolResult(str(exc), is_error=True)
            except Exception as exc:  # a broken tool must not kill the loop
                result = ToolResult(f"{type(exc).__name__}: {exc}", is_error=True)

        _audit(name, tool_input, result, time.monotonic() - started)
        return result


def _audit(name: str, tool_input: dict, result: ToolResult, elapsed: float) -> None:
    """Append one line to ~/.jarvis/logs/tools.jsonl. Every call, no exceptions."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": name,
        "input": tool_input,
        "is_error": result.is_error,
        "elapsed_ms": round(elapsed * 1000),
        "output": result.content[:2000],
    }
    try:
        config.TOOL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with config.TOOL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # logging must never break a tool call
