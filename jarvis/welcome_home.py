#!/usr/bin/env python3
"""
Jarvis - Welcome Home module.
Detects two claps, greets the user, drops a coding idea, and opens the workspace.
"""

import sounddevice as sd
import numpy as np
import subprocess
import webbrowser
import tempfile
import time
import random
import sys
import os

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

_eleven = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
JARVIS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George — British, deep (free tier)

# ── Audio tuning ──────────────────────────────────────────────────────────────
SAMPLE_RATE    = 44100
BLOCK_SIZE     = 1024
CLAP_THRESHOLD = 0.25   # RMS level that counts as a clap (0.0–1.0)
MIN_GAP        = 0.15   # seconds between claps (debounce)
MAX_GAP        = 1.8    # max seconds between two claps to count as a double
NUM_CLAPS      = 2

# ── Coding ideas Jarvis can suggest ───────────────────────────────────────────
CODING_IDEAS = [
    "Build a CLI tool that writes your git commit messages automatically from the diff using Claude.",
    "Create a VS Code extension that plays a victory sound every time your tests pass.",
    "Write a Python script that auto-organizes your Downloads folder by file type every night.",
    "Build a browser extension that gives you a three-bullet summary of any webpage you visit.",
    "Make a Discord bot that logs your daily coding hours and gives you XP and ranks.",
    "Build a terminal dashboard that shows your GitHub stats, open PRs, and streak in real time.",
    "Create a Pomodoro timer that auto-searches lo-fi music on YouTube between sessions.",
    "Write a scraper that monitors price drops on tech gear from your wishlist and texts you.",
    "Build a tool that converts any YouTube tutorial into timestamped notes with code snippets.",
    "Make a keyboard shortcut that pastes your most-used code snippets from a fuzzy search menu.",
    "Create an AI that reads your browser history and recommends what to learn next.",
    "Build a voice-controlled script runner so you can run npm commands without touching the keyboard.",
]


def say(text: str) -> None:
    """Stream TTS from ElevenLabs Jarvis voice and play via afplay."""
    audio = b"".join(
        _eleven.text_to_speech.convert(
            voice_id=JARVIS_VOICE_ID,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        tmp_path = f.name
    subprocess.run(["afplay", tmp_path], check=True)
    os.unlink(tmp_path)


def open_workspace() -> None:
    subprocess.Popen(["open", "-a", "Visual Studio Code"])
    time.sleep(0.4)
    webbrowser.open("https://www.google.com")
    time.sleep(0.4)
    webbrowser.open(
        "https://www.youtube.com/results?search_query=Should+I+Stay+or+Should+I+Go+The+Clash"
    )


def welcome_sequence() -> None:
    idea = random.choice(CODING_IDEAS)

    say("Welcome home, sir.")
    say("Here is tonight's coding idea.")
    say(idea)
    say("Opening your workspace.")

    print(f"\n  Idea: {idea}\n")
    print("  Opening VS Code, Google, and YouTube...")
    open_workspace()
    print("  Done. Let's get to work.\n")


def listen_for_claps() -> None:
    clap_times: list[float] = []
    last_clap_time: float = 0.0

    print("Jarvis is listening... Clap twice to activate.\n")

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="float32",
    ) as stream:
        while True:
            data, _ = stream.read(BLOCK_SIZE)
            rms = float(np.sqrt(np.mean(data ** 2)))
            now = time.time()

            if rms > CLAP_THRESHOLD and (now - last_clap_time) > MIN_GAP:
                clap_times.append(now)
                last_clap_time = now
                print(f"  Clap {len(clap_times)} detected  (rms={rms:.3f})")

                clap_times = [t for t in clap_times if now - t <= MAX_GAP]

                if len(clap_times) >= NUM_CLAPS:
                    print("\n  Double clap confirmed!\n")
                    clap_times = []
                    last_clap_time = 0.0
                    return


def main() -> None:
    print("=" * 50)
    print("  J.A.R.V.I.S — Welcome Home Module")
    print("  Clap twice to activate.")
    print("=" * 50 + "\n")

    while True:
        try:
            listen_for_claps()
            welcome_sequence()
            print("\nBack to listening...\n")
        except KeyboardInterrupt:
            print("\nJarvis standing by. Goodbye, sir.")
            sys.exit(0)


if __name__ == "__main__":
    main()
