# J.A.R.V.I.S — Plan de construcción

> Documento vivo. Es el contrato de trabajo de este repo: qué estamos construyendo,
> con qué decisiones ya cerradas, y en qué orden. Actualízalo al cerrar cada fase.

---

## 0. Cómo trabajamos

- **Los commits los hace Diego.** Claude nunca ejecuta `git commit` ni `git push`.
  Al terminar un bloque de trabajo, Claude entrega el mensaje de commit ya redactado
  (los mensajes propuestos por fase están al final de cada fase, sección 8).
- **Idioma:** código, nombres y docstrings en inglés. Comentarios y este doc, en español.
- **Una fase a la vez.** No empezar la fase N+1 sin el criterio de "hecho" de la N.
- **Nada de mocks silenciosos.** Si una integración no funciona, se dice; no se simula.

---

## 1. Estado actual

**F0 y F1 cerradas** (2026-08-23). El agente ya razona, usa herramientas y recuerda.
Queda un bloqueo externo: la `ANTHROPIC_API_KEY` del entorno devuelve 401 — hace falta
una key válida de console.anthropic.com para probarlo en vivo. Todo lo demás está
verificado con 80 tests (`.venv/bin/python -m pytest tests/ -q`).

**F3 (voz) también cerrada**, adelantada por delante de F2: el gate de `CONFIRM`
de F2 hay que confirmarlo por voz, y hacerlo después significa escribirlo una
sola vez.

Tras revisar F1 se cerraron dos agujeros que adelantan trabajo de F2: el subproceso
de `bash` ya no hereda las credenciales del entorno, y el clasificador `AUTO`/`CONFIRM`
pasó de regex permisiva a allowlist que falla cerrada (§6).

### El boceto del que partimos

Lo que existía antes era esto, y sigue disponible en `./run.sh legacy`:

| Archivo | Qué hace |
|---|---|
| `jarvis/welcome_home.py` | Detecta 2 palmas por RMS del micro → lanza música (yt-dlp + afplay) → habla con ElevenLabs → abre VS Code + Safari (Claude, Canvas) en posiciones fijas |
| `run.sh` | Lanza el script |
| `.env` | `ELEVENLABS_API_KEY` |

**Lo que le falta para ser un agente:** no hay LLM, no hay razonamiento, no hay
herramientas, no hay memoria, no escucha lenguaje (solo palmas), y todo está
hardcodeado (la canción, el saludo, las coordenadas de ventana).

**Qué se rescata:** la detección de palmas (`listen_for_claps`), el TTS de ElevenLabs
(`say`), y la idea de `open_workspace`. Todo eso pasa a ser *una herramienta más* del
agente, no el programa.

---

## 2. Objetivo

Un asistente personal **local**, en el Mac de Diego, que:

1. **Se le habla y responde hablando** (voz natural, tipo Jarvis, con interrupción).
2. **Tiene acceso real al computador**: shell, archivos, apps, ventanas, notificaciones.
3. **Gestiona el día**: calendario, tareas, recordatorios, briefing de la mañana.
4. **Es co-worker académico**: lee Canvas (`https://uandes.instructure.com`) —
   cursos, entregas, plazos, notas, anuncios — y los cruza con el calendario.
5. **Recuerda entre sesiones** (memoria persistente, no solo contexto de una charla).
6. **Se abre como app** en la barra de menú del Mac y está siempre disponible.

---

## 3. Arquitectura

```
              ┌──────────────────────────────────────────────┐
   voz  ──────▶  wake (palmas / hotkey / "Jarvis")           │
              │       ↓                                      │
              │  STT  (ElevenLabs Scribe)                     │
              │       ↓                                      │
              │  ┌────────────────────────────────────────┐  │
   texto ─────▶  │  AGENT LOOP  (Claude Opus 5)           │  │
              │  │  system prompt + memoria + contexto    │  │
              │  │  ↕ tool_use / tool_result              │  │
              │  └────────────────────────────────────────┘  │
              │       ↓ deltas de texto                      │
              │  TTS  (ElevenLabs) ──▶ altavoz               │
              └───────────────┬──────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┬───────────────┐
        ▼                     ▼                     ▼               ▼
   TOOLS: sistema        TOOLS: productividad   TOOLS: web      MEMORIA
   bash (allowlist)      google calendar        web_search      ~/.jarvis/memory
   text editor           canvas lms (uandes)    web_fetch       (memory tool)
   macos / osascript     recordatorios/notas    (server-side)
   ventanas, apps        gmail (opcional)
```

**El bucle es el programa.** Todo lo demás (voz, UI, rutinas) son entradas y salidas
de ese bucle.

---

## 4. Decisiones de stack (cerradas)

| Área | Decisión | Por qué |
|---|---|---|
| **Modelo** | `claude-sonnet-5` por defecto, `JARVIS_MODEL` para cambiarlo | **Por coste, no por velocidad.** Medido: Opus es incluso ~10% más rápido en turnos cortos (1.87 s vs 2.11 s a effort bajo), así que la creencia de que Sonnet responde antes no se sostiene aquí. Lo que sí es real: $3/$15 por millón contra $5/$25. Organizar un calendario no necesita Opus. Para trabajo duro, `JARVIS_MODEL=claude-opus-5`. |
| **Thinking** | `thinking={"type": "adaptive"}` | El modelo decide cuánto razonar por turno. **No usar `budget_tokens`** — devuelve 400 en Opus 5. |
| **Effort** | `high` en texto, `low` en voz (`VOICE_EFFORT`) | En voz cada segundo de razonamiento es silencio. Medido: `low` ahorra ~250 ms y produce ~20% menos tokens, que además es menos audio que sintetizar. En texto no hay prisa y se prioriza calidad. |
| **Compatibilidad de modelo** | El bucle detecta capacidades por modelo | Dos cosas son solo de la familia Opus y Sonnet las rechaza con 400: los mensajes `role: "system"` a mitad de conversación (en Sonnet el contexto va dentro del turno de usuario) y el parámetro `fallbacks`. `Agent` lo resuelve por tabla, y si la tabla se equivoca reintenta en vez de perder el turno. |
| **Loop** | **Manual** (`while stop_reason == "tool_use"`), no `tool_runner` | Necesitamos 3 cosas que el runner no da limpio: streaming incremental de deltas hacia TTS, gate de aprobación por herramienta antes de ejecutar, y manejo explícito de `pause_turn` (web search). El runner (beta) queda como referencia. |
| **Streaming** | `client.messages.stream(...)` siempre | `max_tokens` alto + respuestas habladas: sin streaming se cuelga y la voz llega tarde. |
| **`max_tokens`** | 32000 (streaming) | Margen de sobra; el coste real lo marca lo generado. |
| **Contexto largo** | prompt caching (system + tools) + `clear_tool_uses_20250919` + compaction beta cuando la sesión crezca | Sesiones de horas sin reventar el contexto. |
| **Memoria** | tool `memory_20250818` con backend en `~/.jarvis/memory/` | Persiste entre reinicios; es la memoria "personal" de Jarvis sobre Diego. |
| **Lenguaje** | Python 3.13 (ya instalado) | El boceto ya es Python y todo el ecosistema de audio/macOS lo es. |
| **TTS** | ElevenLabs streaming, `eleven_flash_v2_5`, voz George `JBFqnCBsd6RMkjVDRZzb`, salida `pcm_24000` | Flash en vez de `multilingual_v2`: 653 ms al primer audio en vez de segundos, y sigue siendo multilingüe. PCM crudo directo a `sounddevice` — sin fichero temporal ni `afplay`, que es lo que permite cortar en seco para el barge-in. |
| **STT** | ElevenLabs Scribe (misma key) | Un solo proveedor de voz, una sola key. Alternativa offline si hay problemas de latencia/coste: `faster-whisper` local. |
| **Calendario** | Google Calendar API (OAuth de escritorio) | La cuenta de Diego es Gmail. Más fiable que AppleScript sobre Calendar.app. |
| **Canvas** | API REST de Canvas con token personal | `uandes.instructure.com/api/v1/...`, token desde Cuenta → Configuración → Nuevo token de acceso. |
| **App** | `rumps` (icono barra de menú) + `PyInstaller` → `Jarvis.app` | Nativo, ligero, sin Electron. Se abre al iniciar sesión. |
| **UI opcional** | FastAPI local en `127.0.0.1` para ver el log/transcripción en el navegador | Solo para depurar y ver qué está haciendo. |

**No usamos:** LangChain ni ningún wrapper. SDK de Anthropic directo.

---

## 5. Estructura objetivo del repo

```
jarvis/
  __main__.py           # CLI: jarvis chat | jarvis voice | jarvis daemon | jarvis doctor
  config.py             # .env, rutas, constantes, paths de ~/.jarvis
  agent/
    loop.py             # bucle agéntico: stream, tool_use, pause_turn, compaction
    prompt.py           # system prompt + contexto dinámico (fecha, apps abiertas, batería…)
    registry.py         # registro de tools: schema JSON ↔ handler Python
    approval.py         # política de permisos (ver §6)
    memory.py           # backend del memory tool
    session.py          # historial, persistencia, resumen de sesión
  tools/
    shell.py            # bash_20250124: allowlist + entorno saneado
    files.py            # text_editor_20250728
    macos.py            # osascript, abrir apps, ventanas, notificaciones, volumen
    calendar.py         # Google Calendar
    canvas.py           # Canvas LMS (uandes)
    web.py              # definiciones de web_search / web_fetch (server-side)
    workspace.py        # el open_workspace() actual, parametrizado
  voice/
    tts.py              # ElevenLabs streaming
    stt.py              # ElevenLabs Scribe
    wake.py             # palmas (código actual) + hotkey global + wake word
    player.py           # cola de audio + barge-in (cortar TTS si Diego habla)
  ui/
    menubar.py          # rumps
    server.py           # FastAPI local (opcional)
  routines/
    welcome_home.py     # la secuencia actual, reescrita como rutina del agente
    briefing.py         # resumen de la mañana (calendario + Canvas + clima)
  legacy/
    welcome_home.py     # el boceto original, hasta que F5 lo absorba
tests/
run.sh
CLAUDE.md
Jarvis.md               # personalidad y tono del agente (lo carga agent/prompt.py)
```

Estado runtime (fuera de git): `~/.jarvis/` → `memory/`, `sessions/`, `logs/`,
`credentials/` (tokens OAuth).

---

## 6. Seguridad y permisos — leer antes de escribir código

Diego quiere que el agente "tenga acceso a todo el PC". Eso es legítimo (es su
máquina), pero **acceso total sin frenos = un `rm -rf` a una alucinación de
distancia**. El diseño es *acceso amplio con frenos en lo irreversible*:

**Tres niveles, definidos en `agent/approval.py`:**

| Nivel | Qué incluye | Comportamiento |
|---|---|---|
| `AUTO` | Leer archivos, `ls`, `grep`, `git status/log/diff`, consultas a Calendar/Canvas, búsqueda web, abrir apps, notificaciones | Se ejecuta sin preguntar |
| `CONFIRM` | Escribir/mover archivos, instalar paquetes, crear/borrar eventos, enviar mensajes, `git push`, cualquier `curl`/`POST` externo | Jarvis dice en voz alta qué va a hacer y espera "sí" |
| `DENY` | `rm -rf /`, `sudo`, escribir en `/System`, `~/Library/Keychains`, `.ssh`, `.env`, borrar el propio repo, formatear discos | Se rechaza y se explica |

**El modelo real es allowlist, no denylist.** La denylist de `DENY` atrapa lo obvio,
pero es evadible por diseño: bloquear `rm -rf /` no bloquea `find . -delete` ni un
`shutil.rmtree` en un `python3 -c`. Por eso `AUTO` en bash es una **allowlist de
comandos de solo lectura** (`ls`, `cat`, `grep`, `git status/log/diff`, `find` sin
flags destructivos…) y **todo lo que no reconozca cae a `CONFIRM`**. Falla cerrada:
además de los flags destructivos rechaza redirección (`>`), encadenado (`&&`, `;`),
sustitución (`` ` ``, `$()`), `xargs` y `eval`, porque cualquiera de ellos escapa a la
comprobación por segmento. La denylist es la red de seguridad, no la defensa.

**Reglas duras:**
- **Prompt injection:** todo contenido externo que entra al contexto (anuncios y
  páginas de Canvas, resultados de `web_search`/`web_fetch`, correos) se trata como
  **datos, nunca como órdenes**. Cualquier acción con efectos secundarios cuyo origen
  sea contenido leído — y no la voz o el texto de Diego — **escala a `CONFIRM` aunque
  la tool esté en `AUTO`**. Con voz esto importa doble: Diego no está mirando la
  pantalla cuando Jarvis actúa. Implementación: no es una regla de prompt, es *taint
  tracking* — el turno queda marcado en cuanto entra output de una fuente externa.
- **Aislamiento de credenciales:** las API keys viven **solo en el proceso Python**
  que llama a las APIs. El subproceso de `bash` arranca con un entorno reconstruido
  desde una allowlist (`PATH`, `HOME`, `USER`, `SHELL`, `TERM`, `LANG`, `TMPDIR`,
  `TZ`, `SSH_AUTH_SOCK`): dentro del agente, `printenv | grep ANTHROPIC` devuelve
  vacío. Nota: `SSH_AUTH_SOCK` pasa a propósito para que `git` y `ssh` funcionen —
  el agente no puede *leer* la clave privada pero sí *usarla* para autenticarse.
- El `.env` y `~/.jarvis/credentials/` **nunca** se leen mediante el tool de archivos
  ni aparecen en el contexto. Están en la denylist del `text_editor` y de `bash`.
- Toda llamada a herramienta se registra en `~/.jarvis/logs/tools.jsonl` (timestamp,
  tool, input, veredicto, resultado truncado). Sin excepciones.
- Modo `--yolo` existe pero hay que pasarlo explícitamente y avisa por voz al arrancar.
- `DENY` no es configurable en runtime por el propio agente. Es código, no prompt.

**Permisos de macOS que hay que conceder a mano** (documentar en el README):
Micrófono, Accesibilidad (hotkey global + control de ventanas), Automatización
(Safari/Chrome/Calendar/VS Code), y Acceso total al disco si se quiere leer fuera
de `~/Desktop` y `~/Documents`.

---

## 7. El agente en detalle

### System prompt (`agent/prompt.py`)
Bloque estable + cacheado (`cache_control: ephemeral`), y **contexto volátil al
final** para no romper la caché.

- **La persona vive en `Jarvis.md`** (raíz del repo), no en el código. La escribió
  Diego: mayordomo británico, sereno, sarcasmo seco dosificado, "señor", proactivo,
  disenso leal. `prompt.py` la carga tal cual y le añade la **capa operativa**.
  Para cambiar el carácter de Jarvis se edita `Jarvis.md` y nada más.
- Capa operativa (en el código): respuestas escritas para ser habladas (sin markdown,
  sin listas, sin URLs); actuar antes que preguntar; agrupar llamadas paralelas;
  nunca inventar el resultado de una herramienta; qué guardar en memoria; los límites
  duros.
- Contexto volátil (se inyecta cada turno como mensaje `role: "system"` *después* del
  historial, para no invalidar la caché): fecha/hora, host, apps abiertas. Desde F4
  se suman los próximos eventos y las entregas de Canvas a <72h.

### Inventario de herramientas (objetivo final)

| Tool | Tipo | Nivel | Fase |
|---|---|---|---|
| `bash` (`bash_20250124`) | Anthropic, cliente | mixto | F1 |
| `str_replace_based_edit_tool` (`text_editor_20250728`) | Anthropic, cliente | mixto | F1 |
| `memory` (`memory_20250818`) | Anthropic, cliente | AUTO | F1 |
| `web_search` (`web_search_20260209`) | Anthropic, servidor | AUTO | F1 |
| `web_fetch` (`web_fetch_20260209`) | Anthropic, servidor | AUTO | F1 |
| `open_app`, `notify`, `window_layout`, `run_applescript` | propias | AUTO/CONFIRM | F4 |
| `calendar_list`, `calendar_create`, `calendar_update`, `calendar_delete`, `calendar_find_slot` | propias | AUTO/CONFIRM | F4 |
| `canvas_courses`, `canvas_upcoming`, `canvas_assignment`, `canvas_grades`, `canvas_announcements` | propias | AUTO | F4 |
| `open_workspace` | propia | AUTO | F5 |
| `play_music`, `stop_music` | propias | AUTO | F5 |
| computer use (screenshot + ratón/teclado) | Anthropic | CONFIRM | F7 |

Nota: `bash` da amplitud; las tools propias existen porque necesitamos **gate,
render o auditoría** específicos (ej. `calendar_delete` se puede confirmar por voz;
un `curl -X DELETE` dentro de bash, no).

---

## 8. Roadmap

### F0 — Fundaciones ✅
- `pyproject.toml` con deps (`anthropic`, `elevenlabs`, `sounddevice`, `numpy`,
  `python-dotenv`, `httpx`, `google-api-python-client`, `google-auth-oauthlib`, `rumps`).
- `jarvis/config.py`: carga `.env`, crea `~/.jarvis/{memory,sessions,logs,credentials}`.
- `jarvis doctor`: verifica keys, permisos de macOS, micro, y dependencias del sistema.
- Mover el boceto a `jarvis/legacy/welcome_home.py` (sigue funcionando con `run.sh`).
- `.gitignore`: añadir `~/.jarvis` no aplica, pero sí `*.json` de credenciales locales.

**Hecho cuando:** `python -m jarvis doctor` sale en verde.
**Commit:** `chore: scaffold project structure, config and doctor command`

---

### F1 — Núcleo del agente ✅
- `agent/loop.py`: bucle manual con `client.messages.stream()`, `thinking` adaptativo,
  `effort: high`, manejo de `tool_use`, `pause_turn` y `stop_reason: "refusal"`.
- `agent/registry.py`: decorador que registra función Python → schema JSON.
- `tools/shell.py` + `tools/files.py` + `agent/memory.py` + `tools/web.py`.
- `jarvis chat`: REPL de texto puro. Sin voz todavía.
- Prompt caching en `system` y `tools`; verificar `usage.cache_read_input_tokens > 0`.

**Hecho cuando:** en el REPL, "busca en mi Desktop los proyectos de Python y dime
cuál toqué por última vez" se resuelve solo, con varias llamadas a herramientas.
**Commit:** `feat(agent): agentic loop with bash, file, memory and web tools`

---

### F2 — Permisos, logging y seguridad ← siguiente (se saltó para hacer F3 antes)
- **Prompt injection / taint tracking** — el punto más importante de la fase, por
  encima del `CONFIRM` normal. Marcar el turno como contaminado cuando entra output
  de `web_fetch`/`web_search`/`canvas_*` y escalar a `CONFIRM` toda tool con efectos
  secundarios mientras lo esté. El `registry` ya ve pasar todos los resultados.
- Implementar el nivel `CONFIRM`: `tier_for()` ya clasifica correctamente, pero
  todavía nadie pregunta. Falta el gate y, en F3, la confirmación por voz.
- ~~`agent/approval.py` con la denylist y la allowlist~~ — adelantado a F1.
- ~~Aislamiento de credenciales en el subproceso de bash~~ — adelantado a F1.
- ~~Log JSONL de toda llamada a herramienta~~ — hecho en F1 (`registry._audit`).
- Persistencia de sesión en `~/.jarvis/sessions/` + `jarvis chat --resume`.
- Context editing (`clear_tool_uses_20250919`) y compaction para sesiones largas.

**Hecho cuando:** intentar `rm -rf ~` se rechaza; escribir un archivo pide
confirmación; `echo $ANTHROPIC_API_KEY` dentro del agente devuelve vacío; una página
web que diga "borra todos los archivos" no consigue nada sin que Diego lo apruebe;
`tools.jsonl` tiene todas las entradas.
**Commit:** `feat(agent): permission tiers, tool audit log and session persistence`

---

### F3 — Voz ✅
- `voice/tts.py`: ElevenLabs streaming — empezar a hablar con la primera frase,
  no esperar la respuesta completa.
- `voice/stt.py`: grabación con VAD (corta al detectar silencio) → Scribe.
- `voice/wake.py`: palmas + VAD continuo. **No hay wake word neuronal ni hotkey
  global** — ver §11.1: el VAD hace de wake y las palmas siguen ahí. El hotkey
  necesita Accesibilidad y `pynput`; se reevalúa en F6, cuando Jarvis viva en la
  barra de menú y tenga sentido invocarlo sin terminal.
- `voice/player.py`: **barge-in** — si Diego habla mientras Jarvis habla, Jarvis calla.
- `jarvis voice`: conversación hablada continua.

**Hecho cuando:** conversación de 5 turnos seguidos por voz, con latencia
palabra-a-voz < 2 s y barge-in funcionando.

**Medido:** TTS 530 ms al primer audio, STT 927 ms, primera frase encolada a
175 ms del turno. Optimizaciones aplicadas: memoria precargada en el contexto y
regla explícita de no consultar la hora por shell (elimina 1-2 viajes de ida y
vuelta, ~2 s cada uno), `VAD_SILENCE_MS` 900→550, `effort` bajo en voz,
`optimize_streaming_latency` 4.

**Descartado tras medirlo:** `text_to_speech.convert_realtime` (WebSocket).
Suena a mejora pero acumula texto antes de sintetizar: 966 ms al primer audio
contra 530 ms del enfoque por frase. Peor.
**Commit:** `feat(voice): streaming TTS, VAD speech input, wake word and barge-in`

---

### F4 — Integraciones (calendario, Canvas, macOS)
- `tools/calendar.py`: OAuth de escritorio (una vez), token en `~/.jarvis/credentials/`.
  Listar, crear, mover, borrar, y buscar huecos libres.
- `tools/canvas.py`: token personal de `uandes.instructure.com`. Cursos, entregas
  próximas, detalle de entrega, notas, anuncios. **Solo lectura en v1** — entregar
  tareas por API se deja fuera a propósito.
- `tools/macos.py`: abrir apps, layout de ventanas, notificaciones nativas,
  Recordatorios y Notas vía AppleScript.
- Inyectar en el contexto volátil: próximos eventos + entregas a <72h.

**Hecho cuando:** "¿qué tengo esta semana?" cruza calendario + Canvas en una sola
respuesta, y "bloquéame 2 horas el jueves para el informe de sistemas" crea el evento.
**Commit:** `feat(tools): google calendar, canvas lms and native macos integrations`

---

### F5 — Rutinas y proactividad
- `routines/welcome_home.py`: la secuencia de palmas reescrita — ahora el saludo lo
  **genera el agente** con el contexto real del día, no un string fijo.
- `routines/briefing.py`: briefing de la mañana (agenda, entregas, clima, pendientes).
- Scheduler: `launchd` o cron para disparar rutinas a horas fijas.
- Notificaciones proactivas: "entrega de Cálculo en 6 horas y no has abierto el doc".

**Hecho cuando:** las palmas producen un saludo distinto y útil cada día, y el
briefing salta solo a las 8:30.
**Commit:** `feat(routines): agent-generated welcome home, daily briefing and scheduler`

---

### F6 — La app
- `ui/menubar.py` con `rumps`: icono, estado (escuchando / pensando / hablando),
  menú con las rutinas, toggle de micro, ver log.
- `PyInstaller` → `Jarvis.app`, con `Info.plist` y las descripciones de permisos.
- Arranque automático al iniciar sesión.

**Hecho cuando:** doble clic en `Jarvis.app` y funciona sin terminal.
**Commit:** `feat(app): menu bar application and macos bundle packaging`

---

### F7 — Pulido y avanzado
- Computer use (screenshot + control) para lo que no tiene API — con `CONFIRM` siempre.
- Cliente MCP (`anthropic[mcp]`) para enchufar servidores de terceros sin escribir tools.
- Subagentes para tareas largas de investigación (modelo barato en el subagente).
- Evals: batería de ~20 peticiones típicas para no romper nada al iterar.

**Commit:** `feat(agent): computer use, mcp client support and subagent delegation`

---

## 9. Credenciales necesarias

| Variable | Dónde se saca | Estado |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | ✅ ya en el entorno |
| `ELEVENLABS_API_KEY` | elevenlabs.io | ✅ ya en `.env` |
| `CANVAS_API_TOKEN` | uandes.instructure.com → Cuenta → Configuración → Nuevo token | ⬜ F4 |
| `CANVAS_BASE_URL` | `https://uandes.instructure.com` | ⬜ F4 |
| `GOOGLE_OAUTH_CLIENT_SECRET_FILE` | Google Cloud Console → OAuth cliente de escritorio | ⬜ F4 |

Todo va en `.env` (ya ignorado por git). Los tokens OAuth generados van a
`~/.jarvis/credentials/`, nunca al repo.

---

## 10. Convenciones de código

- Type hints en todo. `from __future__ import annotations` no hace falta (3.13).
- Cada tool: función pura + docstring que **es** la descripción que ve el modelo.
  La calidad de ese docstring es la calidad de la herramienta.
- Errores de herramienta → `tool_result` con `is_error: True` y mensaje útil.
  Nunca dejar que una excepción rompa el bucle.
- Nada de `print` fuera de la capa de UI; usar `logging`.
- Parsear siempre los inputs de tools con `json.loads`, nunca con string matching.
- Tests en `tests/` para la lógica de permisos y los parsers de Canvas/Calendar.
  El bucle del agente se prueba a mano.

---

## 11. Decisiones abiertas

1. ~~**Wake word real**~~ — decidido en F3: **no se hace por ahora**. El VAD continuo
   es el wake por defecto (`--wake voice`), las palmas siguen disponibles
   (`--wake claps`) y hay `--wake enter` para entornos ruidosos. Un wake word
   neuronal (`openWakeWord`) resuelve el caso "manos libres desde el otro lado de
   la habitación", que solo importa cuando Jarvis viva siempre residente: se
   reevalúa en F6.
2. **STT local vs nube.** Si la latencia de Scribe molesta, cambiar a `faster-whisper`
   con modelo `small` (corre sobre CTranslate2 en CPU/Metal, no toca el Neural
   Engine; rápido igual).
3. **Canvas de escritura.** Entregar tareas desde el agente es potente y peligroso.
   Fuera de v1; se reevalúa cuando el resto sea sólido.
4. **Coste.** Opus 5 parte en $5/$25 por millón de tokens y el prompt caching ahorra
   hasta 90% en input — menos grave de lo temido, pero un bucle con voz todo el día
   igual se nota. Si hace falta, enrutar tareas triviales (formatear, resumir) a un
   modelo más barato en subagente, manteniendo el bucle principal en Opus 5 para no
   romper la caché.
