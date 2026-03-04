# GrokBox — Claude Code Context

Codebase: `/Code/grokbox/`. Architecture reference: `docs/GROKBOX.md`.
Venv: `/Code/grokbox/venv/`. Run everything inside it.

---

## Current State (Mar 4, 2026)

### Voice Pipeline — COMPLETE

Event-driven streaming pipeline with sub-2.5s TTFSW. Full details in `docs/How_to_speed_this_thing_up.md`.

Key components:
- **AudioEngine** (`scripts/audio_engine.py`) — centralized mic capture + speaker playback, consumer pattern
- **WakeWordDetector** (`scripts/pipeline.py`) — openWakeWord with echo gating (1.5s cooldown)
- **STTFeeder** (`scripts/pipeline.py`) — AssemblyAI Streaming v3 with echo gating (1.0s cooldown), session reuse
- **speak_streaming** (`scripts/pipeline.py`) — 3-thread TTS pipeline (sentence gen → Kokoro TTS → playback)
- **PipelineTimer** (`scripts/pipeline_timer.py`) — per-stage latency instrumentation

### Multi-Provider LLM — COMPLETE

Supports xAI Grok and OpenAI models, hot-swappable from the web UI. Model prefix routes to the correct API:
- `grok-*` → xAI API (`XAI_KEY`)
- `gpt-*`, `o1-*`, `o3-*`, `o4-*` → OpenAI API (`OPENAI_API_KEY`)

### Browser UI — COMPLETE (core features)

`scripts/grokbox_server.py` + `grokbox_ui/` — Flask + SocketIO on port 5000.

**What's built and running:**
- Journalctl tail → socket events (state, transcript, response, images, logs)
- Wallpaper rotation (curated Unsplash photos, 60s cycle, crossfade, voice commands)
- Live stock ticker (yfinance, configurable symbols via settings panel)
- Live 5-day weather (wttr.in Baltimore, 30min poll)
- Service health panel (Daemon, Kokoro, xAI, AssemblyAI, PipeWire, BT Speaker, Raspotify)
- Clock widget (12h format with date)
- Model selector dropdown (functional — POST to server, hot-swap without restart)
- Ticker settings panel (add/remove symbols, save)
- Spotify now-playing widget (art, track, prev/play/next controls)
- NVIDIA Shield TV remote widget (power, app launchers, d-pad)
- Image overlay + `[SHOW_IMAGE]` wallpaper background
- Log drawer (L key toggle)
- All keyboard shortcuts (volume, audio routing, wallpaper, fullscreen)
- Accessible from LAN via `http://10.0.0.183:5000`

**What's NOT built yet:**
- Chesapeake Bay radar ambient mode
- Spotify album art ambient mode
- Audio/BT manager modals (I and B keys)

### Skills — 5 active plugins

| Skill | File | Tools |
|---|---|---|
| Spotify | `skills/spotify.py` | play_spotify, pause_spotify, skip_track_spotify |
| Shield TV | `skills/shield.py` | shield_power, shield_launch_app, shield_watch, shield_remote |
| Web Search | `skills/web_search.py` | web_search |
| Image Search | `skills/image_search.py` | search_image, close_images |

Weather is handled server-side (wttr.in widget), not as a Grok tool.

---

## IPC Protocol (daemon → server)

The daemon logs these strings to journalctl. The server parses them and emits socket events.

```
starts listening for 'Hey Jarvis'     → state: listening
Wake word detected!                   → state: triggered
AssemblyAI streaming channel opened   → state: transcribing
[Partial]: <text>                     → transcript (partial)
[FINAL] <text>                        → transcript (final)
Querying [model-name]...              → state: querying
Grok responded in X.Xs: <text>        → response text + timing
Kokoro generated TTS / SYSTEM RESPONDING → state: responding
[SHOW_IMAGE] /path/to/file.jpg        → show_image + set as wallpaper
[CLOSE_IMAGES]                        → close image overlay
Pause command received                → state: paused
resumed from sleep                    → state: listening
```

---

## Key Files

```
/Code/grokbox/
├── scripts/
│   ├── grokbox_daemon.py       Core voice pipeline (streaming, skills, multi-provider LLM)
│   ├── grokbox_server.py       Flask + SocketIO web UI server (port 5000)
│   ├── audio_engine.py         Centralized audio I/O (mic capture, speaker playback)
│   ├── pipeline.py             WakeWordDetector, STTFeeder, speak_streaming
│   ├── pipeline_timer.py       Per-stage latency instrumentation
│   ├── grokbox_gui.py          OLD tkinter GUI (superseded, don't delete yet)
│   ├── shield_pair.py          One-time NVIDIA Shield TV pairing script
│   └── ...                     Setup/utility scripts
├── grokbox_ui/
│   ├── index.html              Browser UI layout
│   ├── style.css               Dark theme CSS
│   ├── app.js                  Client-side socket handlers + keyboard shortcuts
│   └── default_bg.jpg          Fallback wallpaper
├── skills/
│   ├── skill_manager.py        Dynamic skill loader + tool-call dispatcher
│   ├── spotify.py              Spotify playback control
│   ├── shield.py               NVIDIA Shield TV control (androidtvremote2)
│   ├── web_search.py           Tavily web search
│   └── image_search.py         SerpAPI Google Images → [SHOW_IMAGE]
├── tests/                      Test harness + multi-turn tests
└── docs/                       Project documentation
```

---

## Don't Touch

- `grokbox.service` — the daemon systemd unit
- The daemon's core wake word → STT → LLM → TTS pipeline structure
- `.shield-cert/` — Shield TV pairing credentials

---

## Environment

- Python 3.13, venv at `/Code/grokbox/venv/`
- Display: Wayland (labwc) + Xwayland on `:0`
- Audio: PipeWire via `wpctl`, mic at 16kHz
- User: `varmint`, `XDG_RUNTIME_DIR=/run/user/1000`
- Secrets: `/Code/grokbox/.env` (see `.env.example`)
- BT speaker MAC: `10:B7:F6:1B:A2:AB`
- Shield TV IP: `10.0.0.167`
- Kokoro TTS server: `http://10.0.0.226:5050/tts`
- Web UI server: `http://0.0.0.0:5000` (accessible on LAN)
