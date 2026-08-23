"""Backend for the Anthropic memory tool.

Claude addresses memory as a virtual ``/memories`` directory; we map that onto
``~/.jarvis/memory``. This is what lets Jarvis remember Diego between restarts.

Commands: ``view``, ``create``, ``str_replace``, ``insert``, ``delete``, ``rename``.
"""

import shutil
from pathlib import Path

from jarvis import config
from jarvis.agent.approval import Denied
from jarvis.agent.registry import ToolRegistry

DEFINITION = {"type": "memory_20250818", "name": "memory"}

_PREFIX = "/memories"


def _resolve(raw: str) -> Path:
    """Map a ``/memories/...`` path onto the real memory directory."""
    text = str(raw).strip()
    if not text.startswith(_PREFIX):
        raise Denied(f"Memory paths must start with {_PREFIX}/ — got {text!r}.")

    relative = text[len(_PREFIX):].lstrip("/")
    resolved = (config.MEMORY_DIR / relative).resolve(strict=False)
    root = config.MEMORY_DIR.resolve(strict=False)
    if resolved != root and not resolved.is_relative_to(root):
        raise Denied(f"Refused: {text} escapes the memory directory.")
    return resolved


def _display(path: Path) -> str:
    root = config.MEMORY_DIR.resolve(strict=False)
    return _PREFIX if path == root else f"{_PREFIX}/{path.relative_to(root)}"


def _view(path: Path, view_range: list[int] | None) -> str:
    if not path.exists():
        return f"{_display(path)} does not exist yet."
    if path.is_dir():
        entries = sorted(path.rglob("*"))
        if not entries:
            return f"{_display(path)} is empty."
        return "\n".join(
            f"{'d' if p.is_dir() else '-'} {_display(p)}" for p in entries
        )

    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = 1, len(lines)
    if view_range:
        start = max(1, view_range[0])
        end = len(lines) if view_range[1] == -1 else min(len(lines), view_range[1])
    return "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1)) or "(empty)"


def run(tool_input: dict) -> str:
    command = tool_input.get("command")

    if command == "view":
        return _view(_resolve(tool_input["path"]), tool_input.get("view_range"))

    if command == "create":
        path = _resolve(tool_input["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tool_input.get("file_text", ""), encoding="utf-8")
        return f"Saved {_display(path)}."

    if command == "str_replace":
        path = _resolve(tool_input["path"])
        if not path.is_file():
            raise Denied(f"{_display(path)} does not exist.")
        content = path.read_text(encoding="utf-8")
        old = tool_input["old_str"]
        if content.count(old) != 1:
            raise Denied(
                f"old_str must match exactly once in {_display(path)} "
                f"(found {content.count(old)})."
            )
        path.write_text(content.replace(old, tool_input.get("new_str", ""), 1), encoding="utf-8")
        return f"Updated {_display(path)}."

    if command == "insert":
        path = _resolve(tool_input["path"])
        if not path.is_file():
            raise Denied(f"{_display(path)} does not exist.")
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        index = int(tool_input["insert_line"])
        if not 0 <= index <= len(lines):
            raise Denied(f"insert_line {index} out of range (0-{len(lines)}).")
        text = tool_input.get("insert_text", "")
        if text and not text.endswith("\n"):
            text += "\n"
        lines.insert(index, text)
        path.write_text("".join(lines), encoding="utf-8")
        return f"Inserted into {_display(path)}."

    if command == "delete":
        path = _resolve(tool_input["path"])
        if not path.exists():
            return f"{_display(path)} does not exist."
        if path == config.MEMORY_DIR.resolve(strict=False):
            raise Denied("Refusing to delete the whole memory directory.")
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        return f"Deleted {_display(path)}."

    if command == "rename":
        source = _resolve(tool_input["old_path"])
        target = _resolve(tool_input["new_path"])
        if not source.exists():
            raise Denied(f"{_display(source)} does not exist.")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return f"Renamed {_display(source)} to {_display(target)}."

    raise Denied(f"Unsupported memory command: {command}")


def bootstrap() -> None:
    """Seed the memory directory with a starting note on first run."""
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    seed = config.MEMORY_DIR / "about_diego.md"
    if not seed.exists():
        seed.write_text(
            "# Diego\n\n"
            "- Owner of this machine and of Jarvis.\n"
            "- Studies at Universidad de los Andes (Canvas: uandes.instructure.com).\n"
            "- Speaks Spanish day to day; code and filenames in English.\n"
            "- Does his own git commits — never commit for him.\n\n"
            "## Preferences\n\n(nothing recorded yet)\n\n"
            "## Ongoing\n\n(nothing recorded yet)\n",
            encoding="utf-8",
        )


def register(registry: ToolRegistry) -> None:
    bootstrap()
    registry.add(DEFINITION, run)
