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
./run.sh                     # text mode
./run.sh voice               # spoken conversation — just start talking
./run.sh voice --wake claps  # clap twice to get his attention
./run.sh voice --wake enter  # press enter to talk
./run.sh calibrate           # tune the mic threshold for your room
./run.sh doctor              # environment check
./run.sh legacy              # the original clap-to-start demo
```

Inside the text REPL: `/reset` clears context, `/usage` shows token and cache
counts, `/exit` quits. In voice mode, say "adiós" or press Ctrl-C.

Voice needs microphone permission (macOS asks the first time). If Jarvis keeps
missing you or triggers on room noise, run `./run.sh calibrate` and put the
suggested `JARVIS_VAD_THRESHOLD` in `.env`.

## Status

| Phase | | |
|---|---|---|
| F0 | Scaffold, config, doctor | done |
| F1 | Agentic loop — shell, files, memory, web | done |
| F3 | Voice — streaming TTS, VAD speech input, barge-in | done |
| F2 | Permission tiers, taint tracking, session persistence | next |
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
