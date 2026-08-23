# J.A.R.V.I.S

A local personal agent for macOS. Talks, listens, and has real access to the
machine: shell, files, web, calendar and Canvas.

Built on the Claude API (`claude-opus-5`) with a hand-rolled agentic loop.
The full plan lives in [CLAUDE.md](CLAUDE.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[voice]"
cp .env.example .env      # then fill in the keys
./run.sh doctor
```

## Use

```bash
./run.sh            # text mode (F1)
./run.sh doctor     # environment check
./run.sh legacy     # the original clap-to-start demo
```

Inside the REPL: `/reset` clears context, `/usage` shows token and cache counts,
`/exit` quits.

## Status

| Phase | | |
|---|---|---|
| F0 | Scaffold, config, doctor | done |
| F1 | Agentic loop — shell, files, memory, web | done |
| F2 | Permission tiers, audit log, session persistence | next |
| F3 | Voice — TTS, STT, wake word, barge-in | |
| F4 | Google Calendar, Canvas LMS, native macOS | |
| F5 | Routines and proactivity | |
| F6 | Menu bar app | |
| F7 | Computer use, MCP, subagents | |

## Safety

The agent has broad access on purpose, with the limits in code rather than in
the prompt (`jarvis/agent/approval.py`).

The defense is an **allowlist**, not a denylist: only recognised read-only
commands run unattended, and anything else — including redirection, chaining,
command substitution, `xargs` and `eval` — falls to confirmation. A denylist on
top catches the obvious catastrophes: privilege escalation, wiping the home
directory, reading credentials, git commits.

The `bash` subprocess runs with a rebuilt environment, so API keys held by the
Python process are not visible to it. Every tool call is logged to
`~/.jarvis/logs/tools.jsonl`. See CLAUDE.md section 6.
