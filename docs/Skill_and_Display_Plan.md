# GrokBox Skill Extension & Display Architecture

## The Next Phase: Tool Use and Display Graphics

To make the GrokBox a truly capable smart assistant, we need to bridge the gap between spoken queries, external API execution, and visual screen rendering.

We want a system where Grok can:
1. Control hardware (Smart Lights)
2. Interface with private accounts (Spotify)
3. Fetch live data (Weather, Stocks)
4. Accompany answers with beautiful visuals directly on the Pi's monitor.

Because the system is deliberately designed as decoupled micro-services (`grokbox_daemon.py` representing the Brain, and `grokbox_gui.py` representing the Display), we must employ an architecture that supports modular expansion without breaking the core STT/TTS loops.

---

## 1. The Skill Manager Framework

We will not hardcode tools into the main daemon. Instead, we will build a dynamic **Tool/Skill Interface**.

### Structure
```
/Code/grokbox/skills/
├── __init__.py
├── skill_base.py     # Base abstract class defining standard tool properties
├── spotify.py        # Plays music
├── weather.py        # Gets local radar
└── hue_lights.py     # Controls local Zigbee bulbs
```

### Flow 
1. The **Skill Manager** initializes alongside the `grokbox_daemon.py`. It imports all `.py` files inside the `/skills/` directory.
2. It aggregates their expected JSON Schemas into a single array.
3. When the user speaks, the daemon passes the transcribed text *and* the array of available `tools` to the `v1/chat/completions` API endpoint.
4. If the prompt triggers a tool, xAI returns a `tool_call` instead of standard conversational text.
5. The `Skill Manager` intercepts the `tool_call`, matches the requested function string (e.g. `play_spotify()`), executes the respective Python function in the background, appends the result to the chat history array, and triggers a follow-up completion request to xAI so Grok can naturally synthesize the result.

---

## 2. Display Rendering & The IPC Event Stream

When a skill fetches visual data (like a PNG map or a Spotify album cover), the daemon cannot *force* the UI to draw it directly, as they run in completely separate PID memory spaces (and different users, often). 

Instead, we will exploit our existing, highly-robust logging tailer format as an **Inter-Process Communication (IPC)** bridge. 

### The Event Protocol
We will establish specific trigger keywords that the daemon drops into the standard output queue when a specific media action occurs.

**[SHOW_IMAGE]**
1. The `weather.py` skill triggers. It hits the OpenWeather API, downloads `radar.png` into `/tmp/grok_media/radar.png`.
2. The skill logs a specific string: `log.info("[SHOW_IMAGE] /tmp/grok_media/radar.png | 15")`  *(The '15' signifies seconds to display).*
3. The `grokbox_gui.py` regex parser reads the log, spots the string, intercepts the path, and temporarily spins up a fullscreen `Toplevel` widget overlay layered on top of the dashboard containing the Pillow-rendered image. 
4. The image automatically destroys itself via `.after(15000)` back into the dashboard seamlessly.

**[SHOW_WIDGET]**
1. For more complex elements (like a responsive Spotify player showing transport controls and cover art), we can hardcode specific Tkinter frames in `grokbox_gui.py` that sit hidden.
2. The daemon logs: `log.info("[SHOW_WIDGET] spotify | The Beatles | Abbey Road | /tmp/grok_media/abbey_road.jpg")`
3. The GUI catches it, unpacks the variables, populates the respective labels inside the hidden widget frame, and calls `.place()` or `.pack()` to bring it to the foreground temporarily.

---

## 3. Recommended Implementation Order

### Phase 1: Skill Injection Engine
- Create `skills/` directory.
- Update the main `xai` request function in `grokbox_daemon.py` to support `tools` and `tool_choice` parameters.
- Build a generic fallback handler so if a tool crashes, Grok says *"I encountered an error trying to do that."* rather than breaking the STT daemon loop entirely.

### Phase 2: First Audio Skill (Spotify)
- Build `skills/spotify.py` utilizing `spotipy`.
- Require OAuth authentication handling.
- Verify Grok can successfully execute a play/pause/skip command and confirm execution audibly.

### Phase 3: GUI IPC Upgrade — DONE
- Pillow installed in venv for image rendering inside Tkinter
- `[SHOW_IMAGE]` and `[CLOSE_IMAGES]` regex handlers implemented in `grokbox_gui.py`
- Images display in windowed `Toplevel` overlays on the right half of the screen
- Multiple images can be open simultaneously with keyboard controls (ESC close, Q close all, S save)

### Phase 4: First Visual Skill (Image Search) — DONE
- Built `skills/image_search.py` using SerpAPI Google Images (instead of weather map)
- `search_image(query)` downloads image to `/tmp/` and emits `[SHOW_IMAGE]` log signal
- `close_images()` emits `[CLOSE_IMAGES]` for voice-commanded dismissal
- Retry logic: tries up to 5 original URLs, falls back to Google-hosted thumbnail
- Persistent `requests.Session` with urllib3 retry for Pi network reliability
