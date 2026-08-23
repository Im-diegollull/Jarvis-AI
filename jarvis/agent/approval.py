"""Permission policy for tool calls.

Three tiers, per CLAUDE.md section 6:

``AUTO``     execute without asking
``CONFIRM``  ask Diego first  (wired up in F2 — currently treated as AUTO)
``DENY``     refuse in code, never negotiable through the prompt

Only ``DENY`` is fully implemented in F1. It exists this early because F1 is
the phase that first hands a real shell to a real machine, and a denylist that
arrives after the shell does is a denylist that arrives too late.
"""

import re
from enum import Enum
from pathlib import Path

from jarvis import config


class Tier(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class Denied(Exception):
    """Raised when a tool call hits a hard limit."""


# ── Catastrophic or unrecoverable shell commands ─────────────────────────────
# Deliberately narrow: these are the things with no undo. Ordinary destructive
# work (rm -rf build/, git reset --hard) is CONFIRM territory, handled in F2.
_DENIED_COMMANDS: list[tuple[str, str]] = [
    (r"\bsudo\b|\bdoas\b", "privilege escalation"),
    (r"\brm\s+(-\w+\s+)*(/|~|\$HOME)/?\*?(\s|$)", "recursive delete of home or root"),
    (r"\bmkfs(\.\w+)?\b", "filesystem format"),
    (r"\bdiskutil\s+(erase|reformat|partition)", "disk erase"),
    (r"\bdd\b[^\n]*\bof=/dev/", "raw write to a block device"),
    (r":\(\)\s*\{.*\|.*&.*\}\s*;?\s*:", "fork bomb"),
    (r"\bchmod\s+(-\w+\s+)*777\s+/(\s|$)", "world-writable root"),
    (r"\bcurl\b[^\n|]*\|\s*(sudo\s+)?(ba|z|fi)?sh\b", "piping a download into a shell"),
    (r"\bwget\b[^\n|]*\|\s*(sudo\s+)?(ba|z|fi)?sh\b", "piping a download into a shell"),
    (r"\bkillall\s+(-\w+\s+)*(kernel_task|WindowServer|loginwindow)", "killing a core process"),
    (r"\bgit\s+(-\w+\s+)*push\b[^\n]*--force", "force push"),
    (r"\bgit\s+(-\w+\s+)*(commit|push)\b", "git commit/push — Diego does his own commits"),
    (r"\bhistory\s+-c\b|\brm\b[^\n]*\.(zsh|bash)_history", "erasing shell history"),
    (r"\bfind\s+(/|~|\$HOME)\S*\s[^\n]*-(delete|exec\w*)\b", "recursive delete of home or root"),
    (r"rmtree\s*\(\s*[\"']?(/|~|\$HOME|/Users/)", "scripted recursive delete of home or root"),
]

_DENIED_COMMAND_RES = [(re.compile(p, re.IGNORECASE), why) for p, why in _DENIED_COMMANDS]

# ── Paths that never enter the agent's context, read or write ────────────────
_SECRET_DIRS = (
    config.HOME / ".ssh",
    config.HOME / ".aws",
    config.HOME / ".gnupg",
    config.HOME / ".config" / "gh",
    config.HOME / "Library" / "Keychains",
    config.HOME / "Library" / "Cookies",
    config.HOME / "Library" / "Application Support" / "Google" / "Chrome" / "Default",
    config.CREDENTIALS_DIR,
    Path("/System"),
    Path("/private/etc/sudoers.d"),
)

_SECRET_NAMES = re.compile(
    r"(^|/)(\.env(\.\w+)?|.*\.pem|.*\.key|id_(rsa|ed25519|ecdsa)|"
    r"credentials\.json|token\.json|\.netrc|\.htpasswd)$",
    re.IGNORECASE,
)


def _mentions_secret_path(text: str) -> str | None:
    """Best-effort scan of a shell command for secret paths."""
    lowered = text.replace("$HOME", str(config.HOME)).replace("~", str(config.HOME))
    for secret in _SECRET_DIRS:
        if str(secret).lower() in lowered.lower():
            return str(secret)
    if re.search(r"(^|[\s'\"=])[^\s'\"]*\.env(\s|$|['\"])", lowered):
        return ".env"
    return None


def check_command(command: str) -> None:
    """Raise :class:`Denied` if a shell command crosses a hard limit."""
    for pattern, why in _DENIED_COMMAND_RES:
        if pattern.search(command):
            raise Denied(
                f"Refused ({why}). This is a hard limit in jarvis/agent/approval.py, "
                f"not something I can talk myself out of. Ask Diego to run it himself."
            )
    secret = _mentions_secret_path(command)
    if secret is not None:
        raise Denied(
            f"Refused: that command touches {secret}, which holds credentials. "
            f"Secrets are out of reach by design."
        )


def resolve_path(raw: str) -> Path:
    """Resolve a model-supplied path and verify it is allowed.

    Guards against traversal, symlink escapes and secret files. Returns the
    canonical path; raises :class:`Denied` otherwise.
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    # strict=False so we can also validate paths that do not exist yet (create)
    resolved = candidate.resolve(strict=False)

    if not any(resolved.is_relative_to(root) for root in config.ALLOWED_ROOTS):
        raise Denied(
            f"Refused: {resolved} is outside every allowed root "
            f"({', '.join(str(r) for r in config.ALLOWED_ROOTS)}). "
            f"Set JARVIS_ROOT to widen it."
        )

    for secret in _SECRET_DIRS:
        if resolved == secret or resolved.is_relative_to(secret):
            raise Denied(f"Refused: {resolved} is inside a protected location ({secret}).")

    if _SECRET_NAMES.search(str(resolved)):
        raise Denied(f"Refused: {resolved.name} is a credentials file.")

    return resolved


# ── The allowlist: the actual defense ────────────────────────────────────────
# DENY above is a safety net for the obvious, and it is evadible by design —
# `find . -delete` and a one-line `shutil.rmtree` both walk straight through it.
# The real model is this allowlist: read-only commands run unattended, and
# *everything else* falls to CONFIRM. Widening this set is a security decision.

_READONLY_BINARIES = frozenset(
    """ls cat head tail grep egrep fgrep rg pwd which type file wc stat du df
    echo printf date cal whoami id uname hostname sw_vers ps top tree basename
    dirname realpath readlink sort uniq cut awk sed tr column jq yq diff cmp
    man help history env""".split()
)

_READONLY_GIT = frozenset("status log diff show branch remote stash config".split())

# Flags that turn a read-only command into a destructive one.
_UNSAFE_FLAGS = re.compile(r"(^|\s)-(delete|exec|execdir|ok|okdir|fls|fprint\w*)\b")

# Anything that can chain, redirect, or spawn another command escapes the
# per-segment check below, so it is never AUTO.
_UNSAFE_SHELL = re.compile(r"(;|&&|\|\||&\s*$|>|<|`|\$\(|\bxargs\b|\beval\b)")


def _is_readonly_command(command: str) -> bool:
    """True only if every pipeline segment is a known read-only invocation."""
    if _UNSAFE_SHELL.search(command) or _UNSAFE_FLAGS.search(command):
        return False

    for segment in command.split("|"):
        words = segment.split()
        if not words:
            return False
        binary = words[0]
        if binary == "git":
            if len(words) < 2 or words[1] not in _READONLY_GIT:
                return False
            continue
        if binary == "find":
            continue  # unsafe flags were already rejected above
        if binary not in _READONLY_BINARIES:
            return False
    return True


def tier_for(tool_name: str, tool_input: dict) -> Tier:
    """Classify a tool call. F2 turns CONFIRM into an actual prompt.

    Fails closed: anything not positively recognised as read-only is CONFIRM.
    """
    if tool_name == "bash":
        if tool_input.get("restart"):
            return Tier.AUTO
        return (
            Tier.AUTO
            if _is_readonly_command(str(tool_input.get("command", "")))
            else Tier.CONFIRM
        )

    if tool_name == "str_replace_based_edit_tool":
        return Tier.AUTO if tool_input.get("command") == "view" else Tier.CONFIRM

    if tool_name == "memory":
        return Tier.AUTO if tool_input.get("command") == "view" else Tier.CONFIRM

    return Tier.AUTO
