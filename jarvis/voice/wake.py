"""Wake paths and barge-in.

Two ways to get Jarvis's attention: clap twice (inherited from the original
sketch), or just start talking. Barge-in is the reverse — how Diego takes the
floor back while Jarvis is mid-sentence.
"""

import threading
import time

import numpy as np
import sounddevice as sd

from jarvis import config
from jarvis.voice.player import Player
from jarvis.voice.stt import _rms


def wait_for_claps(count: int = 2, cancel: threading.Event | None = None) -> bool:
    """Block until `count` claps land inside the gap window."""
    claps: list[float] = []
    last = 0.0

    with sd.InputStream(
        samplerate=config.AUDIO_RATE,
        blocksize=config.AUDIO_BLOCK,
        channels=1,
        dtype="float32",
    ) as stream:
        while True:
            if cancel is not None and cancel.is_set():
                return False
            block, _ = stream.read(config.AUDIO_BLOCK)
            now = time.monotonic()
            if _rms(block[:, 0]) > config.CLAP_THRESHOLD and (now - last) > config.CLAP_MIN_GAP:
                claps.append(now)
                last = now
                claps = [t for t in claps if now - t <= config.CLAP_MAX_GAP]
                if len(claps) >= count:
                    return True


class BargeInMonitor:
    """Interrupts the speaker when Diego talks over it.

    The MacBook's speakers bleed into its own microphone, so a naive threshold
    makes Jarvis interrupt himself. Instead we learn the echo level during the
    first moments of each utterance, then require the mic to beat it by a
    margin. Reliable on headphones, approximate on the built-in speakers.
    """

    _LEARN_SECONDS = 0.4

    def __init__(self, player: Player, on_interrupt) -> None:
        self.player = player
        self.on_interrupt = on_interrupt
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.triggered = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self.triggered.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        blocks_per_second = config.AUDIO_RATE / config.AUDIO_BLOCK
        learn_blocks = int(self._LEARN_SECONDS * blocks_per_second)
        trigger_blocks = int(config.BARGE_IN_MS / 1000 * blocks_per_second)

        echo = 0.0
        learned = 0
        loud = 0
        was_playing = False

        try:
            with sd.InputStream(
                samplerate=config.AUDIO_RATE,
                blocksize=config.AUDIO_BLOCK,
                channels=1,
                dtype="float32",
            ) as stream:
                while not self._stop.is_set():
                    block, _ = stream.read(config.AUDIO_BLOCK)
                    level = _rms(block[:, 0])
                    playing = self.player.is_playing

                    if not playing:
                        # Between utterances: forget the echo estimate.
                        was_playing = False
                        echo, learned, loud = 0.0, 0, 0
                        continue

                    if not was_playing:
                        was_playing = True
                        echo, learned, loud = 0.0, 0, 0

                    if learned < learn_blocks:
                        echo = max(echo, level)
                        learned += 1
                        continue

                    floor = max(config.VAD_THRESHOLD * 2, echo * config.BARGE_IN_FACTOR)
                    loud = loud + 1 if level > floor else 0
                    if loud >= trigger_blocks:
                        self.triggered.set()
                        self.on_interrupt()
                        loud = 0
                        learned = 0
        except sd.PortAudioError:
            pass  # the mic went away; barge-in is a nicety, not a requirement


def measure_clap_headroom(seconds: float = 3.0) -> float:
    """Peak level over a window — used by `jarvis calibrate`."""
    frames = int(config.AUDIO_RATE * seconds)
    recording = sd.rec(frames, samplerate=config.AUDIO_RATE, channels=1, dtype="float32")
    sd.wait()
    return float(np.max(np.abs(recording)))
