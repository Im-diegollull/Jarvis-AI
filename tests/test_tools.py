"""Shell, file and memory tools against a real (temporary) filesystem."""

import pytest

from jarvis import config
from jarvis.agent import memory
from jarvis.agent.registry import ToolRegistry
from jarvis.tools import files, shell


def test_shell_runs_and_tracks_cwd(tmp_path):
    (tmp_path / "sub").mkdir()
    shell.run({"restart": True})
    assert "restarted" in shell.run({"restart": True})
    out = shell.run({"command": f"cd {tmp_path} && pwd"})
    assert str(tmp_path) in out
    # the cd persisted into the next call
    assert "sub" in shell.run({"command": "ls"})


def test_shell_reports_failure_honestly():
    out = shell.run({"command": "ls /definitely-not-here-xyz"})
    assert "exit code" in out


def test_shell_output_is_truncated(monkeypatch):
    monkeypatch.setattr(config, "SHELL_OUTPUT_LIMIT", 200)
    out = shell.run({"command": "seq 1 5000"})
    assert "truncated" in out and len(out) < 500


def test_file_lifecycle(tmp_path):
    target = tmp_path / "note.txt"
    files.run({"command": "create", "path": str(target), "file_text": "hola\nmundo\n"})
    assert target.read_text() == "hola\nmundo\n"

    assert "mundo" in files.run({"command": "view", "path": str(target)})

    files.run(
        {"command": "str_replace", "path": str(target), "old_str": "mundo", "new_str": "Diego"}
    )
    assert "Diego" in target.read_text()

    files.run(
        {"command": "insert", "path": str(target), "insert_line": 0, "insert_text": "# top"}
    )
    assert target.read_text().startswith("# top")


def test_create_backs_up_existing(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("original")
    files.run({"command": "create", "path": str(target), "file_text": "new"})
    assert (tmp_path / "a.txt.jarvis-bak").read_text() == "original"


def test_str_replace_requires_unique_match(tmp_path):
    target = tmp_path / "dup.txt"
    target.write_text("x\nx\n")
    from jarvis.agent.approval import Denied

    with pytest.raises(Denied):
        files.run({"command": "str_replace", "path": str(target), "old_str": "x", "new_str": "y"})


def test_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    memory.bootstrap()
    memory.run({"command": "create", "path": "/memories/likes.md", "file_text": "coffee\n"})
    assert "coffee" in memory.run({"command": "view", "path": "/memories/likes.md"})
    memory.run({"command": "rename", "old_path": "/memories/likes.md", "new_path": "/memories/p.md"})
    assert "p.md" in memory.run({"command": "view", "path": "/memories"})
    memory.run({"command": "delete", "path": "/memories/p.md"})
    assert "does not exist" in memory.run({"command": "view", "path": "/memories/p.md"})


def test_memory_cannot_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    from jarvis.agent.approval import Denied

    with pytest.raises(Denied):
        memory.run({"command": "view", "path": "/etc/passwd"})
    with pytest.raises(Denied):
        memory.run({"command": "view", "path": "/memories/../../../etc/passwd"})


def test_registry_turns_exceptions_into_error_results():
    registry = ToolRegistry()
    registry.add({"name": "boom"}, lambda _: (_ for _ in ()).throw(ValueError("nope")))
    result = registry.dispatch("boom", {})
    assert result.is_error and "nope" in result.content

    unknown = registry.dispatch("ghost", {})
    assert unknown.is_error


def test_registry_definitions_are_stable():
    from jarvis.agent.loop import build_registry

    first = build_registry().definitions()
    second = build_registry().definitions()
    assert first == second, "tool order must be deterministic or the cache breaks"


def test_bash_cannot_read_credentials_from_the_environment(monkeypatch):
    """API keys live in the Python process only — never in the subprocess."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-eleven-secret")
    assert "secret" not in shell.run({"command": "printenv"})
    assert "secret" not in shell.run({"command": "echo $ANTHROPIC_API_KEY"})
    assert "0" in shell.run({"command": "printenv | grep -c ANTHROPIC || true"})


def test_bash_still_has_a_usable_environment():
    assert "/" in shell.run({"command": "echo $HOME"})
    assert "bin" in shell.run({"command": "echo $PATH"})
