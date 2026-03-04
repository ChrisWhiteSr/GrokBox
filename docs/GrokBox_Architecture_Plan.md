# GrokBox: DIY Smart Speaker Architecture

You are 100% correct—building this as a web-based app for a headless smart speaker would be a complete waste of overhead and add unnecessary latency. 

The ideal approach is a **standalone Linux daemon** (a native Python script running via `systemd`). It launches automatically on boot, runs invisibly in the background, and directly interacts with the hardware (microphone and Bluetooth speaker) via ALSA/PulseAudio with minimal latency.

Since you already have a mature and high-quality STT and TTS infrastructure running on your main rig, we can offload the heavy lifting back to the host machine. This transforms the GrokBox into a highly efficient "Thin Client" that simply listens, streams, and plays back!

---

## 🏗️ The "Thin Client" Architecture

By utilizing your existing `lobster-trap` tools over the local network, the GrokBox Python daemon will only need to run a tiny footprint locally. 

### 1. The Wake Word Engine (Local on GrokBox)
The GrokBox constantly listens for a wake word (e.g., "Hey Grok") without sending audio anywhere.
*   **Tech:** `openWakeWord`
*   **Why:** Very lightweight. Can run on the Pi 5 using less than 5% CPU while continuously monitoring the microphone stream via `pyaudio`.

### 2. Speech-to-Text (Offloaded via AssemblyAI)
Once the wake word triggers, we don't need to run Local Whisper on the Pi. We will reuse your exact setup from `lt_stt.py`!
*   **Tech:** `assemblyai` Universal Streaming API
*   **Flow:** The GrokBox daemon opens a WebSocket connection using the exact same AssemblyAI API key you use in `lt_stt.py`. It streams the user's voice directly to AssemblyAI, which returns blazing-fast, highly accurate transcriptions in real-time.

### 3. The LLM Brain (Cloud API)
We process the transcription to generate the response.
*   **Tech:** `xAI Grok API`
*   **Flow:** The transcribed text is sent to Grok. We can give it a specific system prompt like *"You are a helpful home assistant. Keep responses under 3 sentences so they are easy to listen to."*

### 4. Text-to-Speech (Offloaded to `miniLobster` Host)
Instead of forcing the Pi to generate speech, we simply ping your incredibly fast ONNX Kokoro server!
*   **Tech:** Your `kokoro_tts_server.py` at `http://<host_ip>:5050/tts`
*   **Flow:** The GrokBox daemon makes a quick HTTP POST request to your existing Kokoro API with the text payload. Your main rig does the heavy lifting instantly and returns the `.wav` audio. 

### 5. Audio Output Management (Local on GrokBox)
*   **Tech:** `PyAudio` or standard `aplay` connected via Bluetooth.
*   **Flow:** The incoming `.wav` bytes from the Kokoro server are blasted straight out to your paired Bluetooth speaker.

---

## ⚙️ Why This is the Ultimate Setup

1. **Zero Web Bloat**: The GrokBox just runs a Python script as `grokbox.service`. No Flask, no React, no browser required. Just raw TCP/UDP networking and audio byte streams.
2. **Instant Response Times**: Grok API + your local Kokoro instance on port 5050 + AssemblyAI streaming is a lethal combo for low latency. It will easily beat the Google Nest.
3. **Low Power Consumption**: By offloading STT and TTS, the Pi 5 will run cool and quiet, doing nothing but listening for the wake word with a tiny model until you speak to it.

## 🚀 How we build it next
1. I will write a standalone `grokbox_daemon.py` app that combines `pyaudio`, the AssemblyAI WebSocket, Grok API, and requests to your Kokoro server port `5050`.
2. We test it via the shared terminal.
3. We set it to run as a `systemd` background service on `10.0.0.182`/`10.0.0.183`.

---

## 🖥️ Graphical User Interface (GUI) Monitor

To take advantage of the monitor connected directly to the GrokBox, we have added a dedicated GUI overlay.

### What it does
The `grokbox_gui.py` is a natively running UI built on `tkinter`. It launches automatically on boot via the `grokbox-gui.service` systemd unit and renders through **Xwayland** on `DISPLAY=:0`.

**Display stack:** The Pi runs **labwc** (a Wayland compositor) via LightDM with autologin for user `varmint`. Labwc provides Xwayland for X11 app compatibility. The tkinter GUI runs as an X11 app through Xwayland — no separate X server, xinit, or standalone window manager is needed. *(The original approach used `xinit` + Openbox but this conflicted with labwc owning the display.)*

- **Real-time Diagnostics:** It continuously watches `journalctl -u grokbox -f` without needing separate logging.
- **Visual Feedback:** A pulsating status indicator shows when the wake word triggers, audio is streaming, LLM logic is firing, and TTS audio is playing.
- **Speech History:** Panels on the left live-feed the speech transcript (`USER AUDIO TRANSCRIPT`) and the generated language context from the backend (`GROK SYNTHESIS`).
- **Keyboard Navigation Options:** The GUI works without a mouse, and gives you physical audio control options!
    - `UP ARROW`: Volume Up +5%
    - `DOWN ARROW`: Volume Down -5%
    - `M`: Move speaker output to "Monitor" (HDMI display output)
    - `E`: Move speaker output to "External" (Big Blue Party or generic Bluetooth speaker)
    - `I`: Open mic input source selector
    - `B`: Open Bluetooth device manager
    - `ESC`: Toggle fullscreen / half-screen

### Running and Managing the GUI
The GUI is configured to load on startup via `grokbox-gui.service`, which starts after `graphical.target` (ensuring labwc and Xwayland are ready).
*   **Startup Service:** `grokbox-gui.service`
*   **To Check Status:**  `sudo systemctl status grokbox-gui.service`
*   **To Restart manually:** `sudo systemctl restart grokbox-gui.service`

If you'd like to toggle the fullscreen mode while on the GrokBox, hit **Escape** on the attached keyboard.
