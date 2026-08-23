"""Jarvis command line.

    jarvis doctor     verify the environment
    jarvis chat       text REPL against the agent
    jarvis voice      spoken conversation
    jarvis calibrate  tune the microphone thresholds
"""

import argparse
import shutil
import subprocess
import sys

from jarvis import config


# ── doctor ───────────────────────────────────────────────────────────────────

def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {mark} {label}" + (f"  — {detail}" if detail else ""))
    return ok


def doctor() -> int:
    print("\n  J.A.R.V.I.S — environment check\n")
    results = []

    version = sys.version_info
    results.append(
        _check(
            "Python >= 3.11",
            version >= (3, 11),
            f"{version.major}.{version.minor}.{version.micro}",
        )
    )

    try:
        import anthropic

        results.append(_check("anthropic SDK", True, anthropic.__version__))
    except ImportError:
        results.append(_check("anthropic SDK", False, "pip install -e ."))
        anthropic = None

    results.append(
        _check(
            "ANTHROPIC_API_KEY",
            bool(config.ANTHROPIC_API_KEY),
            "set" if config.ANTHROPIC_API_KEY else "missing — required",
        )
    )
    _check(
        "ELEVENLABS_API_KEY",
        bool(config.ELEVENLABS_API_KEY),
        "set" if config.ELEVENLABS_API_KEY else "missing — needed from F3 (voice)",
    )
    _check(
        "CANVAS_API_TOKEN",
        bool(config.CANVAS_API_TOKEN),
        "set" if config.CANVAS_API_TOKEN else "missing — needed from F4 (Canvas)",
    )

    config.ensure_dirs()
    results.append(
        _check(
            "runtime directories",
            all(d.is_dir() for d in config.RUNTIME_DIRS),
            str(config.JARVIS_HOME),
        )
    )
    _check("workspace root", config.WORKSPACE_ROOT.is_dir(), str(config.WORKSPACE_ROOT))

    for binary, note in (("osascript", "macOS automation"), ("yt-dlp", "music, F5")):
        _check(f"{binary}", shutil.which(binary) is not None, note)

    if anthropic and config.ANTHROPIC_API_KEY:
        try:
            client = anthropic.Anthropic()
            model = client.models.retrieve(config.MODEL)
            results.append(
                _check("API reachable", True, f"{model.display_name}, {model.max_input_tokens:,} ctx")
            )
        except Exception as exc:
            results.append(_check("API reachable", False, f"{type(exc).__name__}: {exc}"))

    ok = all(results)
    print(
        "\n  \033[32mAll good.\033[0m Run: jarvis chat\n"
        if ok
        else "\n  \033[31mFix the failures above before continuing.\033[0m\n"
    )
    return 0 if ok else 1


# ── chat ─────────────────────────────────────────────────────────────────────

def chat() -> int:
    from jarvis.agent.loop import Agent, build_registry
    from jarvis.ui.console import ConsoleEvents

    config.ensure_dirs()
    registry = build_registry()
    events = ConsoleEvents()
    agent = Agent(registry, events=events)

    print("\n  \033[1mJ.A.R.V.I.S\033[0m — text mode")
    print(f"  {len(registry.tools)} tools · {config.MODEL} · Ctrl-C or /exit to quit\n")

    while True:
        try:
            user_input = input("\033[36m›\033[0m ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Standing by.\n")
            return 0

        if not user_input:
            continue
        if user_input in ("/exit", "/quit"):
            print("  Standing by.\n")
            return 0
        if user_input == "/reset":
            agent.reset()
            print("  Context cleared.\n")
            continue
        if user_input == "/usage":
            events.report_usage(agent.last_usage)
            continue

        try:
            agent.send(user_input)
        except KeyboardInterrupt:
            print("\n  [interrupted]\n")
        except Exception as exc:
            print(f"\n  \033[31m{type(exc).__name__}\033[0m: {exc}\n")
        events.finish()

    return 0


# ── voice ────────────────────────────────────────────────────────────────────

def voice(wake: str) -> int:
    from jarvis.ui import voice as voice_ui

    return voice_ui.run(wake=wake)


def calibrate() -> int:
    """Measure the room so VAD_THRESHOLD is a number, not a guess."""
    from jarvis.voice.stt import ambient_level
    from jarvis.voice.wake import measure_clap_headroom

    print("\n  Calibración del micrófono\n")
    input("  Quédate en silencio y pulsa enter… ")
    ambient = ambient_level(2.0)
    print(f"    ruido de fondo: {ambient:.4f}")

    input("\n  Ahora habla normal durante tres segundos, pulsa enter y habla… ")
    speech = ambient_level(3.0)
    print(f"    tu voz:         {speech:.4f}")

    input("\n  Ahora da dos palmas, pulsa enter y aplaude… ")
    clap = measure_clap_headroom(3.0)
    print(f"    palmas (pico):  {clap:.4f}")

    if speech <= ambient * 1.5:
        print("\n  \033[31mNo distingo tu voz del ruido de fondo.\033[0m "
              "Acércate al micro o busca un sitio más silencioso.")
        return 1

    threshold = round(ambient + (speech - ambient) * 0.35, 4)
    print(f"\n  Añade esto a tu .env:\n")
    print(f"    JARVIS_VAD_THRESHOLD={threshold}")
    if clap > 0.15:
        print(f"    # palmas ok (pico {clap:.2f}, umbral {config.CLAP_THRESHOLD})")
    else:
        print(f"    # palmas flojas (pico {clap:.2f}); usa 'jarvis voice --wake voice'")
    print()
    return 0


# ── entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="chat",
        choices=("chat", "voice", "doctor", "calibrate", "legacy"),
        help="chat (default), voice, doctor, calibrate, or legacy",
    )
    parser.add_argument(
        "--wake",
        default="voice",
        choices=("voice", "claps", "enter"),
        help="how to get Jarvis's attention in voice mode (default: voice)",
    )
    args = parser.parse_args()

    if args.command == "doctor":
        return doctor()
    if args.command == "calibrate":
        return calibrate()
    if args.command == "voice":
        return voice(args.wake)
    if args.command == "legacy":
        return subprocess.call([sys.executable, "-m", "jarvis.legacy.welcome_home"])
    return chat()


if __name__ == "__main__":
    raise SystemExit(main())
