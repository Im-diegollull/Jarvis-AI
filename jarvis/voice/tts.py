"""Speech output.

The agent streams text deltas; Jarvis must start talking before the turn ends.
:class:`Speaker` buffers deltas into whole sentences, queues each one, and a
worker thread streams it to ElevenLabs and plays it. By the time the model has
finished writing, the first sentence is already in the air.
"""

import logging
import queue
import re
import shutil
import subprocess
import threading

from elevenlabs.client import ElevenLabs

from jarvis import config
from jarvis.voice.player import Player

# Split after . ! ? … : ; or a newline, but not on an abbreviation or a decimal.
_SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+|\n+")
_MIN_SENTENCE = 10  # characters — below this, join with the next sentence


class Speaker:
    def __init__(self, player: Player | None = None, client: ElevenLabs | None = None):
        self.player = player or Player()
        self.client = client or ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        self._queue: queue.Queue[str] = queue.Queue()
        self._buffer = ""
        # Pending count under a Condition rather than an "idle" Event: with an
        # Event, a feed() landing between the worker emptying the queue and
        # setting the flag would leave wait() returning while audio is queued.
        self._pending = 0
        self._cond = threading.Condition()
        self._degraded = not config.ELEVENLABS_API_KEY
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ── input side ───────────────────────────────────────────────────────────

    def feed(self, delta: str) -> None:
        """Accept a text delta; speak whatever complete sentences it forms."""
        self._buffer += delta
        while True:
            sentence, rest = _next_sentence(self._buffer)
            if sentence is None:
                break
            self._buffer = rest
            self._enqueue(sentence)

    def flush(self) -> None:
        """Speak the trailing fragment left after the turn ends."""
        self._enqueue(self._buffer)
        self._buffer = ""

    def say(self, text: str) -> None:
        """Speak one line and wait for it — for prompts and confirmations."""
        self._enqueue(text)
        self.wait()

    def _enqueue(self, text: str) -> None:
        text = _spoken(text)
        if not text:
            return
        with self._cond:
            self._pending += 1
        self._queue.put(text)

    # ── control ──────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        """Stop mid-sentence and drop everything still queued."""
        self.player.stop()
        dropped = 0
        try:
            while True:
                self._queue.get_nowait()
                dropped += 1
        except queue.Empty:
            pass
        if dropped:
            with self._cond:
                self._pending -= dropped
                self._cond.notify_all()
        self._buffer = ""

    def wait(self, timeout: float | None = None) -> bool:
        """Block until everything queued has been spoken."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending <= 0, timeout)

    @property
    def is_speaking(self) -> bool:
        with self._cond:
            return self._pending > 0

    # ── worker ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            try:
                if text:
                    if self._degraded:
                        _say_offline(text)
                    else:
                        self.player.play(self._stream(text))
            except Exception as exc:
                # Never silent: a mute Jarvis with no error is undebuggable.
                logging.getLogger("jarvis.voice").warning("TTS failed: %s", exc)
                self._degrade(exc)
                try:
                    _say_offline(text)
                except Exception:
                    print(f"\n  [voz] no pude hablar: {text[:50]!r}", flush=True)
            finally:
                with self._cond:
                    self._pending -= 1
                    self._cond.notify_all()

    def _degrade(self, exc: Exception) -> None:
        """Switch to the offline voice for the rest of the session."""
        if self._degraded:
            return
        self._degraded = True
        reason = "sin cuota" if "quota" in str(exc).lower() or "401" in str(exc) else "sin conexión"
        print(
            f"\n  [voz] ElevenLabs {reason} — sigo con la voz del sistema "
            f"({config.TTS_FALLBACK_VOICE}).",
            flush=True,
        )

    def _stream(self, text: str):
        return self.client.text_to_speech.stream(
            voice_id=config.VOICE_ID,
            text=text,
            model_id=config.TTS_MODEL,
            output_format="pcm_24000",
            language_code=config.TTS_LANGUAGE,
            optimize_streaming_latency=4,
        )


def _next_sentence(buffer: str) -> tuple[str | None, str]:
    """First chunk worth speaking, and what is left.

    Walks the sentence boundaries and takes the earliest one that leaves a
    chunk with some body to it — so "Sí." rides along with the sentence after
    it instead of being spoken alone and sounding clipped. The terminating
    punctuation stays attached; the TTS needs it for intonation.
    """
    for match in _SENTENCE_END.finditer(buffer):
        candidate = buffer[: match.start()]
        if len(candidate.strip()) >= _MIN_SENTENCE:
            return candidate, buffer[match.end():]
    return None, buffer


_MARKDOWN = re.compile(r"[*_`#>]+")
_LINK = re.compile(r"https?://\S+")
_BULLET = re.compile(r"^\s*[-•*]\s+", re.MULTILINE)


def _say_offline(text: str) -> None:
    """macOS `say`. Blocks until spoken; no streaming, but it always works."""
    binary = shutil.which("say")
    if not binary:
        raise RuntimeError("macOS `say` not available")
    subprocess.run(
        [binary, "-v", config.TTS_FALLBACK_VOICE, text],
        check=True,
        timeout=120,
    )


def _spoken(text: str) -> str:
    """Strip what should never be read aloud, even if the model slips."""
    text = _LINK.sub("un enlace", text)
    text = _BULLET.sub("", text)
    text = _MARKDOWN.sub("", text)
    return " ".join(text.split())
