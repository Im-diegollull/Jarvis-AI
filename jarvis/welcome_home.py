#!/usr/bin/env python3
"""
Jarvis - Welcome Home module.
Flujo: 👏👏 → música arranca → Jarvis saluda encima de la música.
La canción se pre-descarga al iniciar para que suene al instante.
"""

import sounddevice as sd
import numpy as np
import subprocess
import webbrowser
import threading
import tempfile
import glob
import time
import random
import sys
import os

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

_eleven      = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
JARVIS_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # George — British, deep (free tier)
YT_SEARCH    = "ytsearch1:Should I Stay or Should I Go The Clash official"
YT_DLP       = "/opt/homebrew/bin/yt-dlp"
MUSIC_CACHE  = "/tmp/jarvis_song"         # extensión añadida por yt-dlp

# ── Audio tuning ──────────────────────────────────────────────────────────────
SAMPLE_RATE    = 44100
BLOCK_SIZE     = 1024
CLAP_THRESHOLD = 0.25
MIN_GAP        = 0.15
MAX_GAP        = 1.8
NUM_CLAPS      = 2

# ── Coding ideas ──────────────────────────────────────────────────────────────
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

_music_proc:  subprocess.Popen | None = None
_music_ready: threading.Event         = threading.Event()
_is_active:   bool                    = False


# ── Music ─────────────────────────────────────────────────────────────────────

def _find_cached_track() -> str | None:
    files = glob.glob(f"{MUSIC_CACHE}.*")
    return files[0] if files else None


def _preload_worker() -> None:
    if _find_cached_track():
        print("  [music] Track already cached.")
        return
    print("  [music] Pre-downloading track in background...")
    try:
        subprocess.run(
            [YT_DLP, "-f", "bestaudio[ext=m4a]/bestaudio",
             "--no-playlist", "-o", f"{MUSIC_CACHE}.%(ext)s", YT_SEARCH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        print("  [music] Track ready.")
    except Exception as e:
        print(f"  [music] Pre-download failed: {e}")


def preload_music() -> None:
    threading.Thread(target=_preload_worker, daemon=True).start()


def _play_worker() -> None:
    global _music_proc
    track = _find_cached_track()
    if not track:
        print("  [music] Track not cached yet, downloading now...")
        _preload_worker()
        track = _find_cached_track()
    if not track:
        print("  [music] Could not find track, skipping music.")
        _music_ready.set()
        return
    _music_proc = subprocess.Popen(["afplay", track])
    _music_ready.set()   # señal: música está sonando
    _music_proc.wait()


def start_music() -> None:
    _music_ready.clear()
    threading.Thread(target=_play_worker, daemon=True).start()
    _music_ready.wait(timeout=10)   # espera a que realmente empiece a sonar


def stop_music() -> None:
    global _music_proc
    if _music_proc and _music_proc.poll() is None:
        _music_proc.terminate()
        _music_proc = None


# ── TTS ───────────────────────────────────────────────────────────────────────

def say(text: str) -> None:
    audio = b"".join(
        _eleven.text_to_speech.convert(
            voice_id=JARVIS_VOICE,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
    )
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        tmp = f.name
    subprocess.run(["afplay", tmp], check=True)
    os.unlink(tmp)


# ── Workspace ─────────────────────────────────────────────────────────────────

def open_workspace() -> None:
    subprocess.Popen(["open", "-a", "Visual Studio Code"])
    time.sleep(0.4)
    webbrowser.open("https://www.google.com")


# ── Welcome sequence ──────────────────────────────────────────────────────────

def welcome_sequence() -> None:
    global _is_active
    _is_active = True
    idea = random.choice(CODING_IDEAS)

    stop_music()
    start_music()     # música arranca y bloquea hasta que suena de verdad
    time.sleep(1.5)   # intro musical antes de que hable Jarvis

    say("Welcome home, sir. Congratulations, sir, on the opening ceremony. It was such a success. May I say how refreshing it is to finally see you in a video with your clothing on, sir.")
    say("Here is tonight's coding idea.")
    say(idea)
    say("Opening your workspace.")

    print(f"\n  Idea: {idea}\n")
    open_workspace()
    print("  Done. Let's get to work.\n")


def shutdown_sequence() -> None:
    global _is_active
    _is_active = False
    stop_music()
    say("Shutting down. Goodnight, sir.")
    print("  [Jarvis] Shutdown. Back to standby.\n")


# ── Clap detection ────────────────────────────────────────────────────────────

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


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 50)
    print("  J.A.R.V.I.S — Welcome Home Module")
    print("  Clap twice to activate.")
    print("=" * 50 + "\n")

    preload_music()   # descarga la canción en background mientras escucha

    while True:
        try:
            listen_for_claps()
            if _is_active:
                shutdown_sequence()
            else:
                welcome_sequence()
            print("Back to listening...\n")
        except KeyboardInterrupt:
            stop_music()
            print("\nJarvis standing by. Goodbye, sir.")
            sys.exit(0)


if __name__ == "__main__":
    main()
