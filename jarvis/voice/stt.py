"""Speech input: record until Diego stops talking, then transcribe.

Voice activity detection is plain RMS energy with hysteresis — open on sustained
speech, close on trailing silence. It is not clever, but it is predictable and
it adds no latency of its own.
"""

import io
import threading
import wave

import numpy as np
import sounddevice as sd
from elevenlabs.client import ElevenLabs

from jarvis import config


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))


class Listener:
    def __init__(self, client: ElevenLabs | None = None) -> None:
        self.client = client or ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    # ── capture ──────────────────────────────────────────────────────────────

    def record(self, cancel: threading.Event | None = None) -> bytes | None:
        """Wait for speech, record it, stop on silence. None if nothing was said."""
        blocks_per_second = config.AUDIO_RATE / config.AUDIO_BLOCK
        start_blocks = int(config.VAD_START_MS / 1000 * blocks_per_second)
        silence_blocks = int(config.VAD_SILENCE_MS / 1000 * blocks_per_second)
        max_blocks = int(config.VAD_MAX_MS / 1000 * blocks_per_second)
        min_blocks = int(config.VAD_MIN_MS / 1000 * blocks_per_second)

        captured: list[np.ndarray] = []
        preroll: list[np.ndarray] = []
        loud = quiet = 0
        speaking = False

        with sd.InputStream(
            samplerate=config.AUDIO_RATE,
            blocksize=config.AUDIO_BLOCK,
            channels=1,
            dtype="float32",
        ) as stream:
            while True:
                if cancel is not None and cancel.is_set():
                    return None

                block, _ = stream.read(config.AUDIO_BLOCK)
                block = block[:, 0]
                level = _rms(block)

                if not speaking:
                    # Keep a little audio from before the onset so the first
                    # syllable is not clipped off.
                    preroll.append(block)
                    if len(preroll) > start_blocks * 3:
                        preroll.pop(0)
                    loud = loud + 1 if level > config.VAD_THRESHOLD else 0
                    if loud >= start_blocks:
                        speaking = True
                        captured = list(preroll)
                    continue

                captured.append(block)
                quiet = quiet + 1 if level <= config.VAD_THRESHOLD else 0
                if quiet >= silence_blocks or len(captured) >= max_blocks:
                    break

        if len(captured) < min_blocks:
            return None
        return _to_wav(np.concatenate(captured))

    # ── transcription ────────────────────────────────────────────────────────

    def transcribe(self, wav: bytes) -> str:
        buffer = io.BytesIO(wav)
        buffer.name = "speech.wav"
        result = self.client.speech_to_text.convert(
            file=buffer,
            model_id=config.STT_MODEL,
            language_code=config.STT_LANGUAGE,
        )
        return (result.text or "").strip()

    def listen(self, cancel: threading.Event | None = None) -> str | None:
        wav = self.record(cancel)
        if wav is None:
            return None
        text = self.transcribe(wav)
        return text or None


def _to_wav(samples: np.ndarray) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(config.AUDIO_RATE)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def ambient_level(seconds: float = 2.0) -> float:
    """Measure the room, for `jarvis calibrate`."""
    frames = int(config.AUDIO_RATE * seconds)
    recording = sd.rec(frames, samplerate=config.AUDIO_RATE, channels=1, dtype="float32")
    sd.wait()
    return _rms(recording[:, 0])
