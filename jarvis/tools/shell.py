"""The bash tool — Anthropic-defined, executed locally.

Keeps a working directory across calls so ``cd`` behaves the way Claude expects;
the API itself is stateless, so the session lives here.
"""

import os
import subprocess
from pathlib import Path

from jarvis import config
from jarvis.agent import approval
from jarvis.agent.registry import ToolRegistry

DEFINITION = {"type": "bash_20250124", "name": "bash"}

_cwd: Path = Path.cwd()

# The subprocess gets a rebuilt environment, not this process's. API keys live
# only in the Python process that calls the APIs; `printenv` inside the agent
# must come back empty. Passthrough is an allowlist on purpose.
_ENV_PASSTHROUGH = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM",
    "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ", "SSH_AUTH_SOCK",
)


def _sandbox_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_PASSTHROUGH}
    env["JARVIS_SANDBOX"] = "1"
    return env


def _truncate(text: str) -> str:
    limit = config.SHELL_OUTPUT_LIMIT
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return text[:limit] + f"\n\n[... {dropped} characters truncated ...]"


def run(tool_input: dict) -> str:
    global _cwd

    if tool_input.get("restart"):
        _cwd = Path.cwd()
        return f"Shell session restarted. Working directory: {_cwd}"

    command = str(tool_input.get("command", "")).strip()
    if not command:
        return "No command given."

    approval.check_command(command)

    # Track cd by asking the shell where it ended up, rather than parsing the
    # command — handles `cd x && cd y`, subshells, pushd, and everything else.
    wrapped = (
        f"{command}\n"
        f"__jarvis_rc=$?\n"
        f"printf '\\n__JARVIS_CWD__%s' \"$PWD\"\n"
        f"exit $__jarvis_rc"
    )

    try:
        proc = subprocess.run(
            [config.SHELL, "-c", wrapped],
            cwd=_cwd if _cwd.is_dir() else Path.home(),
            env=_sandbox_env(),
            capture_output=True,
            text=True,
            timeout=config.SHELL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {config.SHELL_TIMEOUT}s: {command}"

    stdout = proc.stdout
    if "__JARVIS_CWD__" in stdout:
        stdout, _, ending = stdout.rpartition("__JARVIS_CWD__")
        stdout = stdout.rstrip("\n")
        candidate = Path(ending.strip())
        if candidate.is_dir():
            _cwd = candidate

    parts = []
    if stdout:
        parts.append(stdout)
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        parts.append(f"[exit code {proc.returncode}]")
    if not parts:
        parts.append("(no output)")

    return _truncate("\n".join(parts))


def register(registry: ToolRegistry) -> None:
    registry.add(DEFINITION, run)
