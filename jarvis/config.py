"""Configuration, runtime paths and model settings.

Everything Jarvis writes at runtime lives under ``JARVIS_HOME`` (default
``~/.jarvis``), never inside the repo. Secrets come from the repo ``.env``
and are read once here — they are never exposed to the agent's tools.
"""

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
# override=True on purpose: the project .env is the source of truth. Without it
# a stale ANTHROPIC_API_KEY exported in the shell silently wins and you get a
# 401 while staring at a correct .env.
load_dotenv(REPO_ROOT / ".env", override=True)

HOME = Path.home()

# ── Runtime state (outside the repo) ─────────────────────────────────────────
JARVIS_HOME = Path(os.environ.get("JARVIS_HOME", HOME / ".jarvis")).expanduser()
MEMORY_DIR = JARVIS_HOME / "memory"
SESSIONS_DIR = JARVIS_HOME / "sessions"
LOGS_DIR = JARVIS_HOME / "logs"
CREDENTIALS_DIR = JARVIS_HOME / "credentials"

RUNTIME_DIRS = (JARVIS_HOME, MEMORY_DIR, SESSIONS_DIR, LOGS_DIR, CREDENTIALS_DIR)

TOOL_LOG = LOGS_DIR / "tools.jsonl"

# ── Model ────────────────────────────────────────────────────────────────────
MODEL = "claude-opus-5"
MAX_TOKENS = 32_000
EFFORT = "high"
MAX_TOOL_ROUNDS = 50  # circuit breaker for the agentic loop

# ── Filesystem reach ─────────────────────────────────────────────────────────
# The agent may read and edit anywhere under this root. Diego wants broad
# access to his own machine; the hard limits live in agent/approval.py.
WORKSPACE_ROOT = Path(os.environ.get("JARVIS_ROOT", HOME)).expanduser().resolve()

# Scratch space and mounted volumes are fair game too — they hold no secrets
# and agents legitimately need somewhere to stage work.
ALLOWED_ROOTS = (
    WORKSPACE_ROOT,
    Path("/tmp").resolve(),
    Path(tempfile.gettempdir()).resolve(),
    Path("/Volumes"),
)

# ── Shell ────────────────────────────────────────────────────────────────────
SHELL = os.environ.get("SHELL", "/bin/zsh")
SHELL_TIMEOUT = 120  # seconds per command
SHELL_OUTPUT_LIMIT = 30_000  # characters returned to the model

# ── Voice ────────────────────────────────────────────────────────────────────
VOICE_ID = os.environ.get("JARVIS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # George
TTS_MODEL = "eleven_flash_v2_5"   # ~650ms to first audio; multilingual
STT_MODEL = "scribe_v1"
STT_LANGUAGE = os.environ.get("JARVIS_LANGUAGE", "spa")

AUDIO_RATE = 24_000               # ElevenLabs pcm_24000, in and out
AUDIO_BLOCK = 1024

# Voice activity detection, tuned by `jarvis calibrate`
VAD_THRESHOLD = float(os.environ.get("JARVIS_VAD_THRESHOLD", 0.020))
VAD_START_MS = 150                # sustained speech needed to open a recording
VAD_SILENCE_MS = 900              # trailing silence that closes it
VAD_MAX_MS = 30_000               # hard cap on one utterance
VAD_MIN_MS = 400                  # shorter than this is a cough, not a sentence

# Barge-in: the mic must beat the estimated echo of our own speakers by this
# factor before we accept it as Diego interrupting.
BARGE_IN_FACTOR = 3.0
BARGE_IN_MS = 250

CLAP_THRESHOLD = 0.25
CLAP_MIN_GAP = 0.15
CLAP_MAX_GAP = 1.8

# ── Secrets (read here, never handed to a tool) ──────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "https://uandes.instructure.com")
CANVAS_API_TOKEN = os.environ.get("CANVAS_API_TOKEN")


def ensure_dirs() -> None:
    """Create the runtime directory tree if it does not exist yet."""
    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_DIR.chmod(0o700)
