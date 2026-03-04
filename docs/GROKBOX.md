# GrokBox — DIY Smart Speaker

A custom AI smart speaker built on a **Raspberry Pi 5**. It uses a wake word to listen for voice commands, transcribes speech in real-time, sends it to an AI brain, and speaks the response back through a Bluetooth speaker — all with **sub-2.5-second time-to-first-spoken-word** thanks to a fully streaming pipeline.

---

## Architecture Overview

GrokBox is a thin client. The Pi handles only the microphone, wake word detection, and audio playback. All heavy AI processing is offloaded to external services.

```
Microphone (KT USB Audio, 16kHz mono)
        ↓
[1] Wake Word Detection     — openWakeWord, runs locally, "Hey Jarvis"
        ↓
[2] Speech-to-Text          — AssemblyAI Streaming v3 (WebSocket)
        ↓
[3] LLM Brain               — xAI Grok or OpenAI GPT (hot-swappable, with memory)
        ↓
[4] Text-to-Speech          — Kokoro ONNX server on host machine (10.0.0.226:5050)
        ↓
Bluetooth Speaker (Big Blue Party)
```

### Stage Details

| Stage | Technology | Where it runs |
|---|---|---|
| Wake word | openWakeWord (`hey_jarvis_v0.1.onnx`) | Local on Pi |
| STT | AssemblyAI Streaming v3 | Cloud (AssemblyAI) |
| LLM | xAI Grok or OpenAI GPT/o-series (multi-provider) | Cloud (xAI / OpenAI) |
| Tool Execution | `skills/` plugin framework | Local on Pi |
| TTS | Kokoro ONNX (`af_heart` voice) | LAN host at `10.0.0.226` |
| Audio playback | PyAudio (in-memory WAV) | Local on Pi |

---

## Hardware

| Component | Description |
|---|---|
| **Raspberry Pi 5** | Main compute, runs the daemon |
| **KT USB Audio Mic** | Primary microphone input at 16kHz mono |
| **Big Blue Party BT Speaker** | Primary audio output (MAC: `10:B7:F6:1B:A2:AB`) |
| **Host Machine (miniLobster)** | `10.0.0.226` — runs the Kokoro TTS server |

---

## Files

```
/Code/grokbox/
├── scripts/
│   ├── grokbox_daemon.py       Main voice pipeline daemon (wake word → STT → LLM → TTS)
│   ├── grokbox_server.py       Flask + SocketIO web UI server (port 5000)
│   ├── audio_engine.py         Centralized audio I/O (mic capture, speaker playback)
│   ├── pipeline.py             WakeWordDetector, STTFeeder, speak_streaming
│   ├── pipeline_timer.py       Per-stage latency instrumentation
│   ├── grokbox_gui.py          OLD tkinter GUI (superseded by web UI)
│   ├── shield_pair.py          One-time NVIDIA Shield TV pairing script
│   ├── connect_speaker.sh      Reconnects Bluetooth speaker + restarts daemon
│   ├── connect_speaker_boot.sh Auto-connects BT speaker on boot with retry logic
│   ├── auth_spotify.py         One-time Spotify OAuth URL generator
│   ├── auth_spotify_step2.py   One-time Spotify token cacher
│   └── debug_spotify_devices.py  Lists Spotify devices + playback status
├── skills/
│   ├── __init__.py
│   ├── skill_manager.py    Dynamic skill loader + tool-call dispatcher
│   ├── spotify.py          Spotify playback control via spotipy
│   ├── shield.py           NVIDIA Shield TV control (power, apps, remote, search)
│   ├── web_search.py       Web search via Tavily API
│   └── image_search.py     Google Image search + display via SerpAPI
├── grokbox_ui/
│   ├── index.html          Browser-based UI layout
│   ├── style.css           Dark ambient theme CSS
│   ├── app.js              Client-side socket handlers + keyboard shortcuts
│   └── default_bg.jpg      Fallback wallpaper image
├── tests/
│   ├── harness.py          Audio injection test harness
│   ├── multi_turn_test.py  Multi-turn conversation test
│   └── generate_test_audio.py  Test audio generator (record/synthesize/silence)
├── docs/                   Project documentation
├── .env.example            Template for API keys
├── config.json             Runtime config (ticker symbols, active model) — not committed
└── CLAUDE.md               Context file for AI assistants
```

---

## Services

GrokBox runs as four systemd services that start automatically on boot.

### `grokbox.service` — Voice Pipeline Daemon

The core daemon. Listens for the wake word, runs the full STT → LLM → TTS pipeline.

```bash
sudo systemctl start grokbox
sudo systemctl stop grokbox
sudo systemctl restart grokbox
sudo systemctl status grokbox

# Live logs
journalctl -u grokbox -f
```

Runs as user `varmint` with `XDG_RUNTIME_DIR=/run/user/1000` and `PYTHONPATH=/Code/grokbox` so PipeWire audio routing and skill imports work correctly.

Service file: `/etc/systemd/system/grokbox.service`

### `grokbox-gui.service` — Web UI Display

Browser-based ambient display:
- `scripts/grokbox_server.py` — Flask + Flask-SocketIO server on port 5000
- `grokbox_ui/` — static HTML/CSS/JS served by Flask
- Tails `journalctl -u grokbox -f` and emits SocketIO events to connected browsers

Features: rotating Unsplash wallpapers with crossfade, live stock ticker (yfinance, configurable symbols), 5-day weather forecast (wttr.in), NVIDIA Shield TV remote control panel, Spotify now-playing widget, conversation transcripts, service health indicators, hot-swappable model selector (Grok + OpenAI), log drawer.

Accessible from any device on the LAN at `http://<pi-ip>:5000`.

The old tkinter GUI (`scripts/grokbox_gui.py`) is still in the repo but superseded.

```bash
sudo systemctl start grokbox-gui
sudo systemctl stop grokbox-gui
sudo systemctl restart grokbox-gui
sudo systemctl status grokbox-gui
```

Service file: `/etc/systemd/system/grokbox-gui.service`

**Note on display stack:** The Pi's desktop session is `rpd-labwc` (Raspberry Pi Desktop on Wayland). LightDM autologins user `varmint` into labwc, which provides Xwayland on `:0` for X11 app compatibility. The GUI service sets `DISPLAY=:0` and `XAUTHORITY=/home/varmint/.Xauthority` to render through Xwayland. The legacy `start_ui.sh` script (which used `xinit` + Openbox) is no longer used.

### `grokbox-bt.service` — Bluetooth Speaker Auto-Connect

Automatically connects the Big Blue Party Bluetooth speaker and sets it as the default PipeWire audio sink on boot. Uses retry logic (up to 5 attempts) to handle Bluetooth initialization timing.

```bash
sudo systemctl start grokbox-bt
sudo systemctl stop grokbox-bt
sudo systemctl status grokbox-bt

# Check logs
journalctl -u grokbox-bt --no-pager
```

Service file: `/etc/systemd/system/grokbox-bt.service`
Boot script: `/Code/grokbox/scripts/connect_speaker_boot.sh`

This is a `Type=oneshot` service — it runs once at boot, connects the speaker, and exits. `RemainAfterExit=yes` keeps it marked as active so systemd knows it completed.

### `raspotify.service` — Spotify Connect Receiver

Makes GrokBox appear as a Spotify Connect device called **"GrokBox"** on the local network. Any Spotify client (phone, desktop) can select it as an output device and stream music directly to the Pi.

Uses the `pulseaudio` backend to route audio through PipeWire, so it follows the default audio sink — if the BT speaker is connected, Spotify plays through it automatically. No need to manually switch output; it always plays on whatever speakers GrokBox is using.

```bash
sudo systemctl status raspotify
sudo systemctl restart raspotify

# Live logs
sudo journalctl -u raspotify -f
```

Config file: `/etc/raspotify/conf` (source copy at `/Code/grokbox/raspotify.conf`)

The stock raspotify service has strict sandboxing (`ProtectSystem=strict`, `PrivateUsers=true`, etc.) that blocks PipeWire socket access and `/tmp` writes needed for audio decryption. These are relaxed via a systemd drop-in override at `/etc/systemd/system/raspotify.service.d/override.conf`.

### Boot Order

```
network.target + sound.target
        ↓
grokbox.service (daemon — wake word listener)
bluetooth.target + pipewire
        ↓                ↓
grokbox-bt.service    graphical.target (LightDM → labwc → Xwayland)
(connect speaker)              ↓
                     grokbox-gui.service (tkinter on :0 via Xwayland)
raspotify.service (independent — after pipewire-pulse.socket)
```

### Service Configuration Files

| File | Purpose |
|---|---|
| `/etc/systemd/system/grokbox.service` | Voice daemon service unit |
| `/etc/systemd/system/grokbox-gui.service` | GUI service unit |
| `/etc/systemd/system/grokbox-bt.service` | Bluetooth auto-connect service unit |
| `/etc/systemd/system/raspotify.service.d/override.conf` | Raspotify PipeWire overrides |

---

## Using GrokBox

### Basic Operation

1. Say **"Hey Jarvis"** — you'll hear a short beep confirming the wake word triggered
2. Speak your question or command naturally
3. Pause — AssemblyAI detects end of speech automatically (350ms confident / 800ms max)
4. GrokBox streams the response from Grok and speaks it sentence-by-sentence via Kokoro TTS
5. **Follow-up window** — after each response, Jarvis listens for 6 more seconds without needing the wake word. Just keep talking for multi-turn conversations.

### Web UI Keyboard Controls

The browser-based UI has the following hotkeys (no mouse required):

| Key | Action |
|---|---|
| `UP ARROW` | Volume up +5% |
| `DOWN ARROW` | Volume down -5% |
| `E` | Switch audio output to External speaker (Big Blue Party) |
| `M` | Switch audio output to Monitor/HDMI |
| `W` | Next wallpaper |
| `Q` | Close image overlay |
| `L` | Toggle log drawer |
| `ESC` | Toggle fullscreen |

Voice commands for wallpaper: "new background", "change background", "change wallpaper", etc.

### Web UI Status Indicators

The status pill (top-right) shows a mic icon and label that reflects pipeline state:

| Mic Icon | Label | State |
|---|---|---|
| Green (steady) | listening | Listening for wake word |
| Green (steady) | wake word | Wake word triggered |
| Green (pulsing) | transcribing | Transcribing audio (AssemblyAI active) |
| Green (steady) | thinking | Querying Grok LLM |
| Green (steady) | speaking | Playing TTS response |
| Red (steady) | paused | Listening paused |

---

## Bluetooth Speaker Setup

The Bluetooth speaker auto-connects on boot via `grokbox-bt.service`. No manual intervention is normally needed.

If the speaker disconnects mid-session or audio stops working, run:

```bash
/Code/grokbox/scripts/connect_speaker.sh
```

This script:
1. Forces a `bluetoothctl` trust + pair + connect to MAC `10:B7:F6:1B:A2:AB`
2. Finds the Big Blue Party sink ID via `wpctl status` and sets it as default
3. Plays a test beep to confirm audio routing
4. Restarts `grokbox.service`

The boot version (`connect_speaker_boot.sh`) does the same but with retry logic (up to 5 attempts) and without the daemon restart (since the daemon starts independently via systemd ordering).

Alternatively, if the speaker is already connected but audio is going to the wrong output, press **`E`** on the GUI keyboard.

### Known Bluetooth A2DP Issue (Resolved)

Big Blue Party (and other A2DP speakers) may fail to connect with the error:

```
a2dp-sink profile connect failed: Protocol not available
```

**Root cause:** WirePlumber's `bluez.lua` only creates the Bluetooth monitor when the logind seat state is `"active"`. On a headless Pi, the seat state is `"online"`, so the bluez5 SPA device is never created and no A2DP endpoints are registered.

**Fix (applied):** Disable seat monitoring so the Bluetooth monitor starts unconditionally:

```
# /etc/wireplumber/wireplumber.conf.d/50-bluetooth-no-seat.conf
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
```

See `docs/BT_DEBUG.md` for the full investigation log.

The Bluetooth Manager (`B`) supports:
- `ENTER` — connect to selected device (trust → pair → connect → auto-route audio)
- `D` — disconnect
- `R` — remove/unpair
- `S` — scan for new devices (10 seconds)

---

## Configuration

API keys are loaded from `.env` via `python-dotenv`. See `.env.example` for the full list.

Key constants in `grokbox_daemon.py`:

```python
KOKORO_SERVER  = "http://10.0.0.226:5050/tts"   # TTS server
VOICE          = "af_heart"      # Kokoro voice ID
SAMPLE_RATE    = 16000           # Mic sample rate (Hz)
```

The active model is stored in `config.json` and hot-swappable from the web UI dropdown — no daemon restart needed.

### Changing the LLM Model

Select a model from the web UI dropdown, or edit `config.json` directly. The daemon supports multi-provider routing — the model prefix determines which API is used:

| Model | Provider | Notes |
|---|---|---|
| `grok-4-1-fast-non-reasoning` | xAI | Default — newest, fastest, no reasoning chain |
| `grok-4-1-fast-reasoning` | xAI | With reasoning (slower) |
| `grok-4-0709` | xAI | Full Grok 4 |
| `grok-3` | xAI | Previous generation |
| `grok-3-mini` | xAI | Lightweight |
| `gpt-4o` | OpenAI | Fast, capable |
| `gpt-4o-mini` | OpenAI | Budget option |
| `gpt-4.1` | OpenAI | Latest GPT-4 series |
| `o4-mini` | OpenAI | Reasoning model |

Requires `XAI_KEY` for Grok models and `OPENAI_API_KEY` for OpenAI models in `.env`.

### Changing the Voice

Edit `VOICE` in `grokbox_daemon.py`. Available voices from the Kokoro server:

| Voice ID | Description |
|---|---|
| `af_heart` | Female, warm (default) |
| `af_bella` | Female, clear |
| `af_nova` | Female, bright |
| `am_michael` | Male, neutral |
| `am_adam` | Male, deep |
| `bf_emma` | British female |
| `bm_daniel` | British male |

Full list: `curl http://10.0.0.226:5050/voices`

---

## Troubleshooting

### No audio output
1. Press **`E`** on the GUI keyboard to route to Big Blue Party
2. If that fails, run `connect_speaker.sh` to reconnect the speaker
3. Check Kokoro server is running: `curl http://10.0.0.226:5050/health`

### Wake word not triggering
- Check the USB mic is connected: `lsusb | grep -i "KT\|audio"`
- Confirm the daemon is running: `sudo systemctl status grokbox`
- Check mic level: `alsamixer`

### STT not transcribing / session hangs
- Check AssemblyAI API key is valid
- Verify internet connectivity: `ping api.assemblyai.com`

### Grok not responding ("Sorry, I had trouble reaching my brain")
- Check xAI API key is valid and not rate-limited
- Verify internet: `ping api.x.ai`
- Check logs for the specific API error: `journalctl -u grokbox -f`

### Service crashing repeatedly
```bash
journalctl -u grokbox -n 50 --no-pager
```
Look for Python tracebacks after the startup ALSA noise (the ALSA errors on startup are normal and harmless).

---

## Skill Engine (Tool Use)

GrokBox includes a modular skill plugin framework that gives Grok the ability to execute real actions. When a request is made, Grok is given a list of available tools (via the xAI `tools` parameter). If she decides to use one, the daemon executes the corresponding local Python function and feeds the result back to Grok to speak as a natural language reply.

### Architecture

- **`skills/skill_manager.py`** — Scans the `skills/` directory at daemon startup, imports all plugin modules, and registers their JSON tool schemas. Handles dispatching `tool_call` responses back to the correct Python function.
- **`skills/spotify.py`** — Controls Spotify playback via `spotipy`. Auto-routes to preferred devices (GrokBox, Denon AVR). OAuth token cached in `.cache-spotify`.
- **`skills/shield.py`** — Controls NVIDIA Shield TV via `androidtvremote2` (Google TV Remote Protocol v2). Supports power, app launching, d-pad navigation, and content search macros. On-demand connection with 30s auto-disconnect to avoid WiFi/BT coexistence interference.
- **`skills/web_search.py`** — Web search via Tavily API. Returns top 5 results formatted for TTS.
- **`skills/image_search.py`** — Google Image search via SerpAPI. Downloads images to `/tmp/` and logs `[SHOW_IMAGE]` for display.

### Available Tools

| Tool | Trigger phrase (example) |
|---|---|
| `play_spotify(query)` | *"Play some Daft Punk on Spotify"* |
| `pause_spotify()` | *"Pause the music"* |
| `skip_track_spotify()` | *"Skip this song"* |
| `shield_power(action)` | *"Turn on the Shield"* / *"Turn off the TV"* |
| `shield_launch_app(app_name)` | *"Open YouTube TV"* / *"Launch Plex"* |
| `shield_watch(query, app)` | *"Put on Fox News"* / *"Play cat videos on SmartTube"* |
| `shield_remote(command)` | *"Press home on the Shield"* / *"Go back"* |
| `web_search(query)` | *"Search the web for Pi 5 benchmarks"* |
| `search_image(query)` | *"Show me a picture of the Northern Lights"* |
| `close_images()` | *"Close the pictures"* |

### Adding a New Skill

1. Create `skills/my_skill.py`
2. Define a `TOOL_SCHEMAS` list with the OpenAI-style function JSON schema.
3. Implement the matching Python function(s) in the same file.
4. Restart `grokbox.service` — the `SkillManager` will auto-discover and load it.

### Spotify: Initial Setup / Re-Authentication

The Spotify token is cached in `.cache-spotify` and silently refreshed. If it ever expires:

```bash
# On the Pi, generate a new auth URL:
python3 /Code/grokbox/scripts/auth_spotify.py
# Read /Code/grokbox/spotify_url.txt — open that URL in a browser
# Copy the full redirect URL (https://google.com/callback/?code=...)
# Save it to:
echo 'https://google.com/callback/?code=...' > /Code/grokbox/spotify_return_url.txt
# Exchange the code for a token:
python3 /Code/grokbox/scripts/auth_spotify_step2.py
# Restart the daemon
sudo systemctl restart grokbox
```

### Image Search (Google Images via SerpAPI)

The `search_image(query)` skill searches Google Images and displays the result on the GrokBox monitor. Triggered by asking Jarvis to show a picture of anything.

- Uses SerpAPI with Google Images engine
- Tries up to 5 original image URLs, falls back to Google-hosted thumbnail if all fail
- Uses a persistent `requests.Session` with retry logic for reliability on the Pi
- Images display in windowed overlays on the right half of the screen
- Multiple images can be open simultaneously
- `close_images()` tool lets Jarvis close all images by voice command

Requires `SERPAPI_KEY` in `.env`.

### Conversation Memory

The daemon maintains a rolling history of the last 10 user/assistant exchanges. This gives Jarvis short-term memory within a session — she can follow up on previous questions, remember what was just discussed, and give contextual replies. Memory resets when the daemon restarts.

Configurable via `MAX_MEMORY_TURNS` in `grokbox_daemon.py`.

### Chained Tool Calls

The daemon supports chained tool calls — if a single user request triggers multiple tools (e.g., "close the pictures and show me a Ferrari"), the daemon loops through up to 5 rounds of tool execution before returning the final text response.

### Display Signal Protocol

Skills trigger visual output on the GrokBox display by logging specially formatted IPC event strings. The web UI server (`grokbox_server.py`) tails `journalctl -u grokbox -f` and converts these log prefixes into SocketIO events:

| Log prefix | Socket event | Effect |
|---|---|---|
| `[SHOW_IMAGE] /path/to/file.jpg` | `show_image` | Display image as overlay AND set as wallpaper background |
| `[CLOSE_IMAGES]` | `close_images` | Close image overlay |

Additional daemon log patterns parsed into socket events: state changes, partial/final transcripts, response text with latency, pause/resume signals. See `CLAUDE.md` for the full IPC protocol.

---

## NVIDIA Shield TV Control

GrokBox can control an NVIDIA Shield TV on the local network via voice commands and the web UI remote panel.

### Setup

1. Shield TV must have "Android TV Remote Service" enabled (Settings → Device Preferences → About → Build number x7 → Developer options → toggle on)
2. Run the pairing script once: `python3 /Code/grokbox/scripts/shield_pair.py`
3. Enter the PIN shown on the TV screen
4. Pairing certs are saved to `.shield-cert/` for auto-reconnect

### Voice Commands

- *"Turn on the Shield"* / *"Turn off the TV"* → `shield_power`
- *"Open YouTube TV"* / *"Launch Plex"* → `shield_launch_app`
- *"Put on Fox News"* / *"Play cat videos on SmartTube"* → `shield_watch`
- *"Press home"* / *"Go back"* → `shield_remote`

### Supported Apps

YouTube TV, Plex, YouTube, Prime Video, Spotify, Apple TV, Stremio, SmartTube

### Web UI Remote

The Shield widget (lower-left of web UI) provides:
- Power toggle button with on/off indicator
- App launcher buttons (YTTV, PLEX, ATV, STRM, SMTB, AMZN, SPOT)
- D-pad navigation (up/down/left/right/select/back/home/play-pause)
- Current app name display

### Connection Management

The Shield connection is on-demand with a 30-second auto-disconnect to avoid WiFi/BT coexistence interference on the Pi 5's shared radio chip. The connection is only established when a command is sent, then automatically drops after idle.

---

## Kokoro TTS Server

The TTS server runs on `miniLobster` (`10.0.0.226`) and must be running for GrokBox to speak responses. See `kokoro_tts_api.md` for full API reference.

Quick health check:
```bash
curl http://10.0.0.226:5050/health
```

---

## AI Development Notes

This project was built and debugged collaboratively across multiple AI assistants:
- **Claude (Sonnet 4.6)** — daemon bugs, pipeline fixes, audio routing, Skill Engine architecture
- **Claude (Opus 4.6)** — Bluetooth A2DP root cause fix (WirePlumber seat-monitoring bug), Spotify Connect / raspotify audio routing through PipeWire, boot stack overhaul (labwc/Xwayland migration), Spotify skill fixes (device auto-routing), conversation memory, image search skill, chained tool call support, **streaming pipeline**: sentence-by-sentence TTS, 3-thread pipeline, in-memory PyAudio playback, echo suppression, follow-up listening window; **browser UI**: Flask+SocketIO server, dark ambient display, Unsplash wallpaper rotation, live stock ticker, live weather, health panel, Spotify now-playing widget; **NVIDIA Shield TV control**: androidtvremote2 integration, voice tools, web UI remote, search macros, on-demand connection management; **multi-provider LLM**: xAI + OpenAI routing, hot-swappable model selector; **echo gating**: post-playback mic cooldown for fast-responding models
- **Antigravity (Gemini 2.5)** — GUI, model selection, Openbox window manager, Skill Engine implementation, Spotify integration
