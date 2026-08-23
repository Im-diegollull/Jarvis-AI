"""The spoken conversation loop.

Ties the agent to the microphone and the speakers:

    wake → listen → transcribe → agent (streaming) → speak sentence by sentence

The agent's text deltas go straight into the speaker's sentence buffer, so the
first sentence is spoken while the model is still writing the rest.
"""

import threading

from jarvis import config
from jarvis.agent.loop import Events
from jarvis.voice.stt import Listener
from jarvis.voice.tts import Speaker
from jarvis.voice.wake import BargeInMonitor, wait_for_claps

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


class VoiceEvents(Events):
    """Speaks the answer as it arrives; keeps the terminal as a quiet log."""

    def __init__(self, speaker: Speaker) -> None:
        self.speaker = speaker
        self._line_open = False

    def on_text(self, text: str) -> None:
        self.speaker.feed(text)
        if not self._line_open:
            print(f"  {GREEN}◂{RESET} ", end="", flush=True)
            self._line_open = True
        print(text, end="", flush=True)

    def on_tool_start(self, name: str, tool_input: dict) -> None:
        self._close_line()
        detail = tool_input.get("command") or tool_input.get("path") or ""
        print(f"  {CYAN}▸{RESET} {name} {DIM}{str(detail)[:70]}{RESET}")

    def on_tool_end(self, name: str, result) -> None:
        if result.is_error:
            head = (result.content or "").splitlines()[:1]
            print(f"    {RED}└{RESET} {DIM}{head[0][:70] if head else ''}{RESET}")

    def _close_line(self) -> None:
        if self._line_open:
            print()
            self._line_open = False

    def finish(self) -> None:
        self._close_line()
        self.speaker.flush()


def run(wake: str = "voice") -> int:
    """Continuous spoken conversation. `wake` is 'voice', 'claps' or 'enter'."""
    from jarvis.agent.loop import Agent, build_registry

    config.ensure_dirs()

    speaker = Speaker()
    listener = Listener()
    events = VoiceEvents(speaker)
    agent = Agent(build_registry(), events=events)

    monitor = BargeInMonitor(speaker.player, speaker.interrupt)
    monitor.start()

    print(f"\n  {BOLD}J.A.R.V.I.S{RESET} — voice mode")
    print(f"  wake: {wake} · {config.STT_LANGUAGE} · Ctrl-C to quit\n")

    try:
        while True:
            if not _wake(wake):
                continue

            print(f"  {DIM}escuchando…{RESET}")
            try:
                said = listener.listen()
            except Exception as exc:
                print(f"  {RED}micrófono{RESET}: {exc}")
                continue

            if not said:
                continue
            print(f"  {CYAN}›{RESET} {said}")

            if _is_goodbye(said):
                speaker.say("Hasta luego, señor.")
                speaker.wait(timeout=15)
                return 0

            try:
                agent.send(said)
            except Exception as exc:
                print(f"  {RED}{type(exc).__name__}{RESET}: {exc}")
                speaker.say("He tenido un problema técnico, señor.")
                continue
            finally:
                events.finish()

            speaker.wait(timeout=120)
            if monitor.triggered.is_set():
                print(f"  {DIM}[interrumpido]{RESET}")
                monitor.triggered.clear()
            print()

    except KeyboardInterrupt:
        speaker.interrupt()
        print("\n  Standing by.\n")
        return 0
    finally:
        monitor.stop()


def _wake(mode: str) -> bool:
    if mode == "claps":
        print(f"  {DIM}dos palmas para hablar…{RESET}")
        return wait_for_claps()
    if mode == "enter":
        try:
            input(f"  {DIM}enter para hablar…{RESET} ")
        except EOFError:
            raise KeyboardInterrupt
        return True
    return True  # 'voice': the VAD in listen() is the wake path


_GOODBYES = ("adiós", "adios", "hasta luego", "buenas noches", "apágate", "apagate")


def _is_goodbye(text: str) -> bool:
    lowered = text.lower().strip(" .!¡?¿")
    return any(lowered == g or lowered.startswith(g) for g in _GOODBYES)
