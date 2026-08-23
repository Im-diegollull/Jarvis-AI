"""The text editor tool — Anthropic-defined, executed locally.

Every model-supplied path goes through :func:`approval.resolve_path` before it
touches the filesystem. Nothing here calls ``open()`` on a raw path.
"""

import shutil
from pathlib import Path

from jarvis.agent import approval
from jarvis.agent.registry import ToolRegistry

DEFINITION = {
    "type": "text_editor_20250728",
    "name": "str_replace_based_edit_tool",
    "max_characters": 40_000,
}

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}


def _view(path: Path, view_range: list[int] | None) -> str:
    if path.is_dir():
        entries = sorted(
            p for p in path.iterdir() if p.name not in _SKIP_DIRS and not p.name.startswith(".")
        )
        listing = "\n".join(f"{'d' if p.is_dir() else '-'} {p.name}" for p in entries)
        return f"Directory {path}:\n{listing}" if listing else f"Directory {path} is empty."

    if not path.exists():
        raise approval.Denied(f"No such file: {path}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return f"{path} is not a UTF-8 text file ({path.stat().st_size} bytes)."

    start, end = 1, len(lines)
    if view_range:
        start = max(1, view_range[0])
        end = len(lines) if view_range[1] == -1 else min(len(lines), view_range[1])

    width = len(str(end))
    body = "\n".join(f"{i:>{width}}\t{lines[i - 1]}" for i in range(start, end + 1))
    return body or "(empty file)"


def _create(path: Path, file_text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if path.exists():
        backup_path = path.with_suffix(path.suffix + ".jarvis-bak")
        shutil.copy2(path, backup_path)
        backup = f" (previous version saved to {backup_path.name})"
    path.write_text(file_text, encoding="utf-8")
    return f"Wrote {len(file_text)} characters to {path}{backup}."


def _str_replace(path: Path, old_str: str, new_str: str) -> str:
    if not path.is_file():
        raise approval.Denied(f"No such file: {path}")
    content = path.read_text(encoding="utf-8")
    occurrences = content.count(old_str)
    if occurrences == 0:
        raise approval.Denied(f"old_str not found in {path}. Nothing was changed.")
    if occurrences > 1:
        raise approval.Denied(
            f"old_str appears {occurrences} times in {path}; it must match exactly once. "
            f"Include more surrounding context."
        )
    path.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
    return f"Edited {path}."


def _insert(path: Path, insert_line: int, insert_text: str) -> str:
    if not path.is_file():
        raise approval.Denied(f"No such file: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not 0 <= insert_line <= len(lines):
        raise approval.Denied(f"insert_line {insert_line} is out of range (0-{len(lines)}).")
    if insert_text and not insert_text.endswith("\n"):
        insert_text += "\n"
    lines.insert(insert_line, insert_text)
    path.write_text("".join(lines), encoding="utf-8")
    return f"Inserted at line {insert_line} of {path}."


def run(tool_input: dict) -> str:
    command = tool_input.get("command")
    path = approval.resolve_path(str(tool_input["path"]))

    match command:
        case "view":
            return _view(path, tool_input.get("view_range"))
        case "create":
            return _create(path, tool_input.get("file_text", ""))
        case "str_replace":
            return _str_replace(path, tool_input["old_str"], tool_input.get("new_str", ""))
        case "insert":
            return _insert(path, int(tool_input["insert_line"]), tool_input.get("insert_text", ""))
        case _:
            raise approval.Denied(f"Unsupported text editor command: {command}")


def register(registry: ToolRegistry) -> None:
    registry.add(DEFINITION, run)
