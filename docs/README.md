# GrokBox Smart Speaker

A custom DIY smart speaker and ambient display built on a Raspberry Pi 5. It functions as a "Thin Client", offloading heavy AI processing to external APIs and a local network TTS server to achieve sub-2.5-second time-to-first-spoken-word.

## How It Works

```
Microphone (KT USB Audio, 16kHz)
        |
[1] Wake Word Detection     -- openWakeWord, runs locally, "Hey Jarvis"
        |
[2] Speech-to-Text          -- AssemblyAI Streaming v3 (WebSocket)
        |
[3] LLM Brain               -- xAI Grok or OpenAI GPT (hot-swappable via UI)
        |
[4] Text-to-Speech          -- Kokoro ONNX server on LAN host (10.0.0.226)
        |
Bluetooth Speaker (Big Blue Party)
```

## Key Features

- **Voice assistant** -- wake word, streaming STT, tool-calling LLM, streaming TTS
- **Multi-provider LLM** -- xAI Grok and OpenAI GPT/o-series, switchable from the web UI
- **Skill plugins** -- Spotify, NVIDIA Shield TV, web search, image search, weather
- **Ambient web display** -- rotating Unsplash wallpapers, live stock ticker, 5-day weather, health monitoring
- **NVIDIA Shield TV control** -- power, app launching, d-pad navigation, content search macros
- **Spotify Connect** -- GrokBox appears as a castable speaker via Raspotify
- **Follow-up conversations** -- after each response, listens for 6 more seconds without needing the wake word

## Services

GrokBox runs as four systemd services that start automatically on boot:

| Service | Purpose |
|---|---|
| `grokbox` | Core voice pipeline daemon (wake word -> STT -> LLM -> TTS -> playback) |
| `grokbox-gui` | Web UI server (Flask + SocketIO on port 5000) + Chromium kiosk |
| `grokbox-bt` | Auto-connects Bluetooth speaker on boot and sets as default sink |
| `raspotify` | Spotify Connect receiver -- makes GrokBox a castable speaker |

```bash
sudo systemctl restart grokbox       # Restart the voice daemon
sudo systemctl restart grokbox-gui   # Restart the web UI
journalctl -u grokbox -f             # Live daemon logs
```

## Skills

GrokBox has a modular skill plugin system. The LLM uses tools automatically based on what you ask:

| Skill | Example |
|---|---|
| **Weather** | *"What's the weather in Boston?"* |
| **Spotify** | *"Play some Daft Punk"* / *"Skip this song"* / *"Pause"* |
| **Shield TV** | *"Turn on the Shield"* / *"Open YouTube TV"* / *"Put on Fox News"* |
| **Web Search** | *"Search the web for Pi 5 benchmarks"* |
| **Image Search** | *"Show me a picture of the Northern Lights"* |

## Web UI

The browser-based ambient display shows:
- Rotating Unsplash wallpapers with crossfade
- Live stock ticker (yfinance, configurable symbols)
- 5-day weather forecast
- Service health indicators (daemon, TTS, STT, BT, PipeWire, Spotify)
- NVIDIA Shield TV remote control panel
- Spotify now-playing widget with playback controls
- Real-time conversation transcript
- Hot-swappable model selector (Grok + OpenAI models)

Accessible from any device on the LAN at `http://<pi-ip>:5000`.

## Setup

1. Clone the repo and create a virtualenv
2. Copy `.env.example` to `.env` and fill in API keys
3. Install Python dependencies: `pip install -r requirements.txt` (if present) or see `docs/GROKBOX.md`
4. Start the Kokoro TTS server on a LAN host (see `docs/kokoro_tts_api.md`)
5. Enable and start the systemd services
6. For Shield TV: run `scripts/shield_pair.py` once to pair via PIN

See `docs/GROKBOX.md` for the full operations manual.
