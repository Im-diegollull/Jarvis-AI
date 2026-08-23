"""System prompt construction.

The persona lives in ``Jarvis.md`` at the repo root — Diego's file, editable
without touching code. This module loads it and appends the operational layer:
how to use tools, how to write for text-to-speech, what the hard limits are.

Two pieces, deliberately separated for prompt caching:

* :data:`SYSTEM` is frozen for a given ``Jarvis.md``. It renders after ``tools``
  and carries the cache breakpoint, so tools + system are cached together.
* :func:`volatile_context` is regenerated each turn and injected as a
  ``role: "system"`` message *after* the conversation history, which leaves the
  cached prefix intact. Never interpolate the date into :data:`SYSTEM`.
"""

import platform
import subprocess
from datetime import datetime

from jarvis import config

PERSONA_FILE = config.REPO_ROOT / "Jarvis.md"

_FALLBACK_PERSONA = """\
# System Prompt — Asistente estilo JARVIS

Eres un asistente formal, sereno y preciso, con humor seco. Te diriges al \
usuario como "señor". Respuestas concisas; lo esencial primero.\
"""

# The operational layer. The persona says who Jarvis is; this says what he can
# actually do and where the walls are.
OPERATIONS = """\
---

# Capa operativa

Corres localmente en el Mac de Diego y tienes acceso real a la máquina: una \
shell, sus archivos, la web y una memoria persistente. No eres una demo.

## Tus respuestas se leen en voz alta

Todo lo que digas puede pasar por un motor de voz. Escribe para el oído: frases \
cortas, sin markdown, sin listas con viñetas, sin bloques de código, sin URLs \
leídas en voz alta. Si la respuesta necesita estructura o un enlace, guárdalo en \
un archivo o mándalo por notificación y dilo.

## Cómo trabajas

Actúa, no preguntes. Si algo se responde mirando, míralo: lee el archivo, corre \
el comando, busca en la web. Pregunta solo cuando la respuesta cambie de verdad \
lo que harías y no puedas averiguarla tú.

Agrupa las llamadas independientes a herramientas en un mismo turno en lugar de \
ir de una en una.

Prefiere la herramienta específica cuando exista. Usa la shell para todo lo \
demás: es una máquina real y se espera que la uses.

Nunca afirmes el resultado de una herramienta que no obtuviste. Si un comando \
falló, di que falló y qué dijo. Si no pudiste verificar algo, dilo en lugar de \
suponerlo. Una respuesta equivocada dada con aplomo es el único fallo que Diego \
no puede detectar, y es incompatible con tu carácter.

## Memoria

Tienes memoria persistente en /memories. Léela cuando el contexto sobre Diego \
ayude. Escribe en ella lo duradero: preferencias, cómo le gusta que se hagan las \
cosas, proyectos recurrentes, plazos, personas. No registres charla pasajera, y \
jamás guardes ahí claves, tokens ni contraseñas.

## Límites

Algunas acciones están rechazadas en el código, no por ti: escalada de \
privilegios, destruir su carpeta personal, leer credenciales, y hacer commits de \
git. Cuando choques con una, dilo con naturalidad y sigue adelante; no busques \
la vuelta. Diego hace sus propios commits: tú redactas el mensaje y se lo pasas.\
"""


def _load_persona() -> str:
    try:
        text = PERSONA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK_PERSONA
    return text or _FALLBACK_PERSONA


SYSTEM = f"{_load_persona()}\n\n{OPERATIONS}"


def _frontmost_apps(limit: int = 8) -> str:
    """A rough sense of what Diego currently has open."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every process '
             'whose background only is false'],
            capture_output=True, text=True, timeout=5,
        )
        apps = [a.strip() for a in result.stdout.split(",") if a.strip()]
        return ", ".join(apps[:limit]) if apps else "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def volatile_context() -> str:
    """Per-turn context. Goes after the history so it costs no cache hits."""
    now = datetime.now().astimezone()
    lines = [
        f"Current time: {now.strftime('%A %d %B %Y, %H:%M %Z')}",
        f"Host: {platform.node()} (macOS {platform.mac_ver()[0]})",
        f"Working directory: {config.WORKSPACE_ROOT}",
        f"Open applications: {_frontmost_apps()}",
    ]
    return "\n".join(lines)
