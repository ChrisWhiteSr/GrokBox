# GrokBox Display Redesign Plan

**Status:** In progress — core UI is live, advanced features pending
**Author:** Claude Sonnet 4.6 (plan), Claude Opus 4.6 (implementation)
**Visual reference:** `docs/ui_reference.jpg` — build to this image exactly.

---

## Design Philosophy

This is not a dashboard. It's an **ambient display that occasionally talks to you.**

When idle it's beautiful enough to leave on the wall all day.
When active it reacts visually to what Jarvis just said or did.
Text is secondary — annotations on top of a living image, not the main event.

---

## Reference Image

`docs/ui_reference.jpg` is the visual target. Study it carefully before writing
any CSS. Every element described below is visible in that image.

Key observations from the reference:
- The marina background fills 100% of the screen — breathtaking, cinematic
- The ticker is **large and dominant** — big bold text, high contrast
- The conversation scrim is **slim** — barely a strip, not competing
- The weather widget **floats** in the lower-right above the scrims
- The status panel top-right is a small dark glass pill — mic icon + label + chip icon
- The model selector top-left is a small dark glass pill — model name + chevron
- Nothing clutters the center of the image. That's the whole point.

---

## Screen Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [grok-4-fast ▾]                        [🎤 listening  🔲]     │
│                                                                 │
│                                                                 │
│                    AMBIENT LAYER                                │
│             (full-screen wallpaper/radar/album art)             │
│                                                                 │
│                                                          ┌────┐ │
│                                                          │5day│ │
│                                                          │wx  │ │
│                                                          └────┘ │
├─────────────────────────────────────────────────────────────────┤
│  *hey what's the weather looking like this week*                │  ← slim scrim
├─────────────────────────────────────────────────────────────────┤
│  S&P 500  +0.32%   NASDAQ  -0.15%   TSLA  +1.2%   AAPL  -0.4% ⚙│  ← bold ticker
└─────────────────────────────────────────────────────────────────┘
```

---

## Element Specs

### Top-Left: Model Selector Pill
- Dark glass pill: `background: rgba(0,0,0,0.6)`, `border-radius: 20px`, `backdrop-filter: blur(10px)`
- Text: current model name (read from daemon config), white, medium weight
- Dropdown chevron `▾` on the right
- On click: dropdown appears listing available xAI models
- On select: writes new `XAI_MODEL` value and POSTs to `/action/set_model`
- Available models pulled from `GROKBOX.md` or hardcoded list:
  ```
  grok-4-1-fast-non-reasoning  (default)
  grok-4-1-fast-reasoning
  grok-4-0709
  grok-3
  grok-3-mini
  ```

### Top-Right: Status Panel
- Dark glass pill, same style as model selector
- Three elements left to right:
  1. **Microphone icon** — glowing green when listening, red when not/paused, animated pulse when transcribing
  2. **Label** — "listening" / "paused" / "transcribing" / "thinking" — updates with state
  3. **Chip/system icon** — static, just visual chrome
- This is the ONLY place voice status appears. No other indicators anywhere.

### Ambient Layer (full screen, z-index 1)
See full ambient mode specs below. This layer is always running.

### 5-Day Weather Widget (floating, lower-right, z-index 3)
- Floats above the scrims, anchored to bottom-right
- `position: absolute; bottom: 130px; right: 24px`
- Dark glass card, 5 columns: MON TUE WED THU FRI
- Each column: day label, weather icon (emoji or SVG), high°/low°
- Data from `wttr.in` (already used by weather skill, zero cost)
- Updates on page load and every 30 minutes
- Always visible — not triggered by voice, just always there

### Conversation Scrim (slim strip, z-index 4)
- `height: ~52px` — slim, barely a strip
- `background: rgba(0,0,0,0.55)`
- Single line of italic dimmed text: what the user just said
- Appears on wake word trigger, fades out 10 seconds after Jarvis finishes speaking
- When Jarvis responds, her response text streams in on the RIGHT side of this same strip
- Typewriter animation on response text

### Market Ticker (bottom strip, z-index 4)
- `height: ~56px` — tall and prominent, heavier weight than the conversation scrim
- `background: rgba(0,0,0,0.88)` — nearly opaque, visually grounding the bottom
- Large bold text: symbol name + colored percentage + price
- Green `#00FF88` for positive, red `#FF4444` for negative
- Scrolls left continuously: `animation: ticker-scroll 40s linear infinite`
- Settings gear icon `⚙` pinned to far right — opens stock configurator modal
- Stock configurator modal: add/remove tickers, reorder, save to `~/.grokbox_tickers.json`

---

## Ambient Modes

### A. Unsplash Wallpaper Rotation *(primary default)*
```python
UNSPLASH_QUERIES = [
    "jazz club moody",
    "foggy harbor night",
    "golden hour city",
    "chesapeake bay sunset",
    "rain window city lights",
    "concert stage lights",
    "blue hour architecture",
    "autumn forest path",
]
```
- Rotate every 90 seconds, 3-second CSS crossfade
- Pre-fetch next image while current displays
- Cache to `/tmp/grokbox_wallpaper/`
- Fallback to local cached images if offline

API key: `UNSPLASH_ACCESS_KEY` in `.env` (free at unsplash.com/developers)

### B. Chesapeake Bay Radar *(weather mode)*
- NOAA free animated radar, no API key
- KLWX station (Sterling VA) covers Baltimore + upper bay:
  `https://radar.weather.gov/ridge/standard/KLWX_loop.gif`
- Auto-activates when `get_weather` skill fires, stays for 5 minutes then reverts
- Also selectable as permanent idle mode via voice: *"switch to radar"*

### C. Sunrise/Sunset Gradient *(zero-dependency fallback)*
- Pure CSS gradient computed from Baltimore lat/lng + current time
- Always works offline, no API needed
- Active fallback when Unsplash is unreachable

### D. Spotify Album Art *(auto-override)*
- When raspotify detects playback, ambient switches to full-screen album art
- Fetch art URL from Spotify API (credential already in `.env`)
- Track name + artist lower-left corner overlay
- Auto-reverts to wallpaper when music stops
- Daemon logs `[AMBIENT_MODE] spotify` as faster trigger signal

---

## Market Ticker

### Data Source
**yfinance** — free Python library, no API key, no account needed:
```bash
pip install yfinance
```

### Default Tickers
```python
TICKER_SYMBOLS = [
    "^GSPC",    # S&P 500
    "^IXIC",    # NASDAQ
    "TSLA",
    "AAPL",
    "GOOGL",
    # User adds more via settings modal
]
```
Config persists to `~/.grokbox_tickers.json`.

### Update Frequency
Poll every 60 seconds via background thread. Emit `socketio.emit('tickers', data)`
to browser. Zero token cost — pure JSON numbers.

### Settings Modal (gear icon)
- Opens on gear icon click or `T` key
- Simple list: current tickers with remove buttons + text input to add new symbol
- Save button writes to `~/.grokbox_tickers.json` and reloads the ticker thread

---

## IPC Events (server → browser)

```javascript
{ event: 'state',      data: { state: 'listening'|'triggered'|'transcribing'|'querying'|'responding'|'idle' }}
{ event: 'transcript', data: { text: '...', final: false }}
{ event: 'transcript', data: { text: '...', final: true }}
{ event: 'response',   data: { text: '...', latency: 2.1 }}
{ event: 'show_image', data: { path: '/tmp/grokbox_image_xxx.jpg' }}
{ event: 'close_images', data: {}}
{ event: 'tickers',    data: [{ symbol, price, change, pct }, ...]}
{ event: 'ambient',    data: { mode: 'spotify'|'wallpaper'|'radar'|'gradient' }}
{ event: 'log',        data: { line: '...' }}
```

---

## Color Palette

```css
--bg:              #000000;
--glass:           rgba(0, 0, 0, 0.60);
--glass-heavy:     rgba(0, 0, 0, 0.88);
--accent:          #00FFCC;
--text:            #e6f1ff;
--text-dim:        #8892b0;
--mic-active:      #00FF88;
--mic-inactive:    #FF4444;
--ticker-up:       #00FF88;
--ticker-down:     #FF4444;
--ticker-flat:     #aaaaaa;
```

---

## Keyboard Shortcuts

```
UP / DOWN   → volume ±5%              POST /action/vol_up|vol_down
E           → BT speaker             POST /action/sink_external
M           → HDMI output            POST /action/sink_monitor
I           → mic selector modal
B           → audio/BT manager modal
T           → ticker settings modal
W           → cycle ambient mode
Q           → dismiss content layer
L           → toggle log drawer
ESC         → toggle fullscreen
```

---

## Technical Stack

```
grokbox_daemon.py
      │
      ▼
grokbox_server.py  ── Flask + Flask-SocketIO (localhost:5000)
      │
      ▼
Chromium (--kiosk http://localhost:5000)
      ├── grokbox_ui/index.html
      ├── grokbox_ui/style.css
      └── grokbox_ui/app.js
```

Install:
```bash
/Code/grokbox/venv/bin/pip install flask flask-socketio yfinance requests
```

---

## Implementation Order

1. ~~`grokbox_server.py` — Flask + SocketIO, journalctl tail, action endpoints, ticker thread, weather fetch~~ **DONE**
2. ~~`grokbox_ui/` static shell — get the layout matching `ui_reference.jpg` with static data first~~ **DONE**
3. ~~Unsplash wallpaper rotation + crossfade~~ **DONE** — 15 curated photo IDs, 60s rotation, pre-fetch, cached to `/tmp/grokbox_wallpaper/`
4. ~~Ticker crawl — yfinance, CSS scroll, color coding~~ **DONE** — S&P 500, NASDAQ, TSLA, AAPL, GOOGL, 60s poll
5. ~~Status panel — mic icon states wired to socket events~~ **DONE** — pulse/inactive/active states
6. ~~Conversation scrim — transcript + streaming response text~~ **DONE** — partials + final + response, auto-fade after 10s
7. ~~5-day weather widget — wttr.in, always visible~~ **DONE** — wttr.in Baltimore, 30min poll, emoji icons
8. Chesapeake Bay radar ambient mode — **NOT STARTED**
9. Spotify album art ambient mode — **NOT STARTED**
10. ~~Model selector dropdown — functional with POST to server, hot-swap without restart~~ **DONE**
11. ~~Ticker settings modal — add/remove symbols, save to config.json~~ **DONE**
12. Audio/BT manager modals — **NOT STARTED**
13. ~~Log drawer (L key, hidden by default)~~ **DONE**
14. `scripts/start_gui.sh` + updated systemd service — **NOT STARTED**
15. Retire `grokbox_gui.py` — **NOT STARTED** (superseded but still in repo)

### Additional features implemented (not in original plan):
- Voice commands for wallpaper change ("new background", "change wallpaper", etc.)
- W key for manual wallpaper advance
- `[SHOW_IMAGE]` results also set as wallpaper background
- Image overlay auto-dismisses after 8 seconds
- Server accessible from LAN (not just localhost)
- On-connect sends current wallpaper, ticker data, and weather to new clients
- **Clock widget** — 12h time + day/date, top center, updates every second
- **Health panel** — 7-service health indicators (Daemon, Kokoro, xAI, AssemblyAI, PipeWire, BT Speaker, Raspotify), 30s poll
- **Spotify now-playing widget** — album art, track/artist/album, prev/play/next controls
- **NVIDIA Shield TV remote** — power, 7 app launchers, d-pad navigation, current app display
- **Multi-provider LLM** — model dropdown includes both xAI Grok and OpenAI GPT/o-series models
- **Ticker settings panel** — add/remove symbols, save to persistent config

---

## Done When

- Matches `ui_reference.jpg` visually
- Wallpapers rotate with smooth crossfades
- Ticker scrolls live market data
- Mic status panel reflects actual daemon state
- 5-day weather always visible
- Chesapeake radar activates on weather queries
- Spotify album art takes over when music plays
- Model selector is functional
- All keyboard shortcuts work
- Old tkinter GUI retired
