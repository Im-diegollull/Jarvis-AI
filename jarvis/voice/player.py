"""Interruptible PCM playback.

Audio arrives from ElevenLabs as raw 16-bit PCM at 24 kHz and goes straight to
the output device. No temp files, no external player: that is what makes both
low latency and instant interruption possible.

The player also publishes a running estimate of its own output level, which is
what lets the barge-in monitor tell Diego's voice apart from the echo of
Jarvis's own speakers.
"""

import threading

import numpy as np
import sounddevice as sd

from jarvis import config


class Player:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._playing = threading.Event()
        self._output_rms = 0.0
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    @property
    def output_rms(self) -> float:
        """Loudness of what we are pushing to the speakers right now."""
        with self._lock:
            return self._output_rms

    def stop(self) -> None:
        self._stop.set()

    def play(self, chunks) -> bool:
        """Play an iterable of PCM byte chunks. Returns False if interrupted."""
        self._stop.clear()
        self._playing.set()
        finished = True
        stream = sd.RawOutputStream(
            samplerate=config.AUDIO_RATE, channels=1, dtype="int16"
        )
        try:
            stream.start()
            tail = b""
            for chunk in chunks:
                if self._stop.is_set():
                    finished = False
                    break
                data = tail + chunk
                usable = len(data) - (len(data) % 2)  # keep frames whole
                tail = data[usable:]
                data = data[:usable]
                if not data:
                    continue
                self._note_level(data)
                stream.write(data)
        finally:
            with self._lock:
                self._output_rms = 0.0
            self._playing.clear()
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError:
                pass
        return finished

    def _note_level(self, data: bytes) -> None:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size:
            with self._lock:
                self._output_rms = float(np.sqrt(np.mean(samples**2)))
