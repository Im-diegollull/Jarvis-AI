"""Wake paths and barge-in.

Two ways to get Jarvis's attention: clap twice (inherited from the original
sketch), or just start talking. Barge-in is the reverse — how Diego takes the
floor back while Jarvis is mid-sentence.
"""

import logging
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
            block, overflowed = stream.read(config.AUDIO_BLOCK)
            if overflowed:
                continue
            now = time.monotonic()
            if _rms(block[:, 0]) > config.CLAP_THRESHOLD and (now - last) > config.CLAP_MIN_GAP:
                claps.append(now)
                last = now
                claps = [t for t in claps if now - t <= config.CLAP_MAX_GAP]
                if len(claps) >= count:
                    return True


class BargeInMonitor:
    """Interrupts the speaker when Diego talks over it.

    Two things make this harder than a threshold:

    * The MacBook's speakers bleed into its own microphone, so Jarvis hears
      himself. We learn the speaker-to-mic coupling during the first moments of
      actual audio and require the mic to beat the *predicted* echo, which
      scales with how loud the current passage is.
    * PortAudio does not like two input streams on one device. The monitor is
      therefore started only while Jarvis is speaking and stopped before the
      listener opens its own stream — they are never live at the same time.

    Reliable on headphones, approximate on the built-in speakers. Turn it off
    with ``jarvis voice --no-barge-in`` if it misfires.
    """

    _LEARN_SECONDS = 0.5
    _MIN_COUPLING_SAMPLES = 8

    def __init__(self, player: Player, on_interrupt) -> None:
        self.player = player
        self.on_interrupt = on_interrupt
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.triggered = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self.triggered.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        blocks_per_second = config.AUDIO_RATE / config.AUDIO_BLOCK
        learn_blocks = int(self._LEARN_SECONDS * blocks_per_second)
        trigger_blocks = max(1, int(config.BARGE_IN_MS / 1000 * blocks_per_second))

        couplings: list[float] = []
        loud = 0

        try:
            with sd.InputStream(
                samplerate=config.AUDIO_RATE,
                blocksize=config.AUDIO_BLOCK,
                channels=1,
                dtype="float32",
            ) as stream:
                while not self._stop.is_set():
                    block, overflowed = stream.read(config.AUDIO_BLOCK)
                    if overflowed:
                        continue  # a dropped buffer reads as noise; never act on it

                    output = self.player.output_rms
                    if output <= 0.005:
                        # Nothing audible coming out: either between sentences
                        # or waiting on the network. Nothing to talk over.
                        loud = 0
                        continue

                    level = _rms(block[:, 0])

                    if len(couplings) < learn_blocks:
                        couplings.append(level / output)
                        continue

                    # Predict how much of our own voice the mic should be
                    # hearing right now, and demand a clear margin over it.
                    coupling = float(np.percentile(couplings, 90))
                    predicted_echo = coupling * output
                    floor = max(
                        config.VAD_THRESHOLD * 2.5,
                        predicted_echo * config.BARGE_IN_FACTOR,
                    )

                    loud = loud + 1 if level > floor else 0
                    if loud >= trigger_blocks:
                        self.triggered.set()
                        self.on_interrupt()
                        return
        except sd.PortAudioError as exc:
            logging.getLogger("jarvis.voice").warning("barge-in disabled: %s", exc)


def measure_clap_headroom(seconds: float = 3.0) -> float:
    """Peak level over a window — used by `jarvis calibrate`."""
    frames = int(config.AUDIO_RATE * seconds)
    recording = sd.rec(frames, samplerate=config.AUDIO_RATE, channels=1, dtype="float32")
    sd.wait()
    return float(np.max(np.abs(recording)))
