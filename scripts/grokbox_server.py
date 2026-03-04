"""
GrokBox Web UI Server
Flask + Flask-SocketIO serving the browser-based display.
Tails journalctl for the grokbox daemon and emits live events to the browser.
Rotates Unsplash wallpapers every 60 seconds.
"""
import os
import re
import json
import random
import subprocess
import threading
import time
import requests as req
import yfinance as yf
from flask import Flask, send_from_directory, jsonify, request, abort, send_file
from flask_socketio import SocketIO

import spotipy
from spotipy.oauth2 import SpotifyOAuth

import sys
sys.path.insert(0, "/Code/grokbox")

from dotenv import load_dotenv
load_dotenv("/Code/grokbox/.env")

app = Flask(__name__, static_folder="../grokbox_ui", static_url_path="")
app.config["SECRET_KEY"] = "grokbox-dev"
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------------------------------------------------------------------
# Wallpaper rotation
# ---------------------------------------------------------------------------

WALLPAPER_DIR = "/tmp/grokbox_wallpaper"
os.makedirs(WALLPAPER_DIR, exist_ok=True)

WALLPAPER_INTERVAL = 60  # seconds

# Curated Unsplash photo IDs — dark, moody, cinematic (no API key needed)
WALLPAPER_IDS = [
    "photo-1519681393784-d120267933ba",  # milky way mountains
    "photo-1470813740244-df37b8c1edcb",  # northern lights
    "photo-1468276311594-df7cb65d8df6",  # night city rain
    "photo-1505506874110-6a7a69069a08",  # dark ocean
    "photo-1507400492013-162706c8c05e",  # harbor boats night
    "photo-1488866022916-f7f2a032cd64",  # foggy mountains
    "photo-1470252649378-9c29740c9fa8",  # city skyline night
    "photo-1531366936337-7c912a4589a7",  # aurora borealis
    "photo-1534088568595-a066f410bcda",  # dark clouds ocean
    "photo-1500534314309-8f4c5bed8588",  # moody lake
    "photo-1493514789931-586cb221d7a7",  # dark starry sky
    "photo-1504608524841-42fe6f032b4b",  # foggy city
    "photo-1476820865390-c52aeebb9891",  # concert lights
    "photo-1478760329108-5c3ed9d495a0",  # dark forest
    "photo-1464802686167-b939a6910659",  # nebula space
]

_wallpaper_index = 0
_wallpaper_lock = threading.Lock()
_current_wallpaper = None  # path to current file
_next_wallpaper = None     # pre-fetched next


def _fetch_wallpaper(photo_id):
    """Download an Unsplash photo by ID, return local path or None."""
    url = f"https://images.unsplash.com/{photo_id}?w=1920&h=1080&fit=max&q=85"
    path = os.path.join(WALLPAPER_DIR, f"{photo_id}.jpg")
    if os.path.isfile(path) and os.path.getsize(path) > 1000:
        return path  # already cached
    try:
        r = req.get(url, timeout=15)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(path, "wb") as f:
                f.write(r.content)
            return path
    except Exception as e:
        print(f"Wallpaper fetch error: {e}", flush=True)
    return None


def _prefetch_next():
    """Pre-fetch the next wallpaper in the background."""
    global _next_wallpaper, _wallpaper_index
    with _wallpaper_lock:
        _wallpaper_index = (_wallpaper_index + 1) % len(WALLPAPER_IDS)
        pid = WALLPAPER_IDS[_wallpaper_index]
    path = _fetch_wallpaper(pid)
    if path:
        _next_wallpaper = path


def _wallpaper_rotation():
    """Background task: rotate wallpapers on a timer."""
    global _current_wallpaper, _next_wallpaper

    # Shuffle so it's not the same order every restart
    random.shuffle(WALLPAPER_IDS)

    # Fetch the first wallpaper
    _current_wallpaper = _fetch_wallpaper(WALLPAPER_IDS[0])

    # Pre-fetch the second one
    _prefetch_next()

    while True:
        time.sleep(WALLPAPER_INTERVAL)
        advance_wallpaper()


def advance_wallpaper():
    """Switch to the next wallpaper and pre-fetch another."""
    global _current_wallpaper, _next_wallpaper
    if _next_wallpaper and os.path.isfile(_next_wallpaper):
        _current_wallpaper = _next_wallpaper
        _next_wallpaper = None
        socketio.emit("wallpaper", {"url": "/wallpaper/current?" + str(time.time())})
    # Pre-fetch the next one in a thread so we don't block
    threading.Thread(target=_prefetch_next, daemon=True).start()


@app.route("/wallpaper/current")
def serve_wallpaper():
    """Serve the current wallpaper image."""
    if _current_wallpaper and os.path.isfile(_current_wallpaper):
        return send_file(_current_wallpaper, mimetype="image/jpeg")
    # Fallback to default
    return send_from_directory(app.static_folder, "default_bg.jpg")


@app.route("/action/next_wallpaper", methods=["POST"])
def next_wallpaper():
    """Force-advance to the next wallpaper (W key or voice command)."""
    advance_wallpaper()
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Shared config file
# ---------------------------------------------------------------------------

CONFIG_PATH = "/Code/grokbox/config.json"

def _load_config():
    """Load the shared config file."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "ticker_symbols": ["^GSPC", "^IXIC", "TSLA", "AAPL", "GOOGL"],
            "ticker_names": {"^GSPC": "S&P 500", "^IXIC": "NASDAQ"},
            "model": "grok-4-1-fast-non-reasoning",
        }

def _save_config(config):
    """Save the shared config file."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Stock ticker
# ---------------------------------------------------------------------------

TICKER_INTERVAL = 60  # seconds

_ticker_data = []
_ticker_refresh = threading.Event()  # signal to re-fetch immediately

def _fetch_tickers():
    """Fetch current prices and daily change for all ticker symbols."""
    global _ticker_data
    while True:
        try:
            config = _load_config()
            symbols = config.get("ticker_symbols", [])
            names = config.get("ticker_names", {})

            print("Fetching tickers...", flush=True)
            results = []
            for sym in symbols:
                try:
                    t = yf.Ticker(sym)
                    info = t.fast_info
                    price = info.last_price
                    prev = info.previous_close
                    if price and prev:
                        change = price - prev
                        pct = (change / prev) * 100
                        results.append({
                            "symbol": names.get(sym, sym),
                            "price": round(price, 2),
                            "change": round(change, 2),
                            "pct": round(pct, 2),
                        })
                except Exception as e:
                    print(f"Ticker {sym} error: {e}", flush=True)

            if results:
                _ticker_data = results
                socketio.emit("tickers", _ticker_data)
                print(f"Tickers updated: {len(results)} symbols", flush=True)
        except Exception as e:
            print(f"Ticker fetch error: {e}", flush=True)

        _ticker_refresh.wait(timeout=TICKER_INTERVAL)
        _ticker_refresh.clear()


# ---------------------------------------------------------------------------
# 5-day weather
# ---------------------------------------------------------------------------

_weather_data = []

def _fetch_weather():
    """Fetch 5-day forecast from wttr.in (free, no API key)."""
    global _weather_data
    while True:
        try:
            r = req.get("https://wttr.in/Baltimore?format=j1", timeout=10)
            if r.status_code == 200:
                data = r.json()
                from datetime import date, datetime
                today = date.today()
                days = [d for d in data.get("weather", [])
                        if datetime.strptime(d["date"], "%Y-%m-%d").date() >= today][:5]
                result = []
                day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                for d in days:
                    dt = datetime.strptime(d["date"], "%Y-%m-%d")
                    day_label = "TODAY" if dt.date() == today else day_names[dt.weekday()]
                    high = d.get("maxtempF", "?")
                    low = d.get("mintempF", "?")
                    # Weather code to emoji
                    code = d.get("hourly", [{}])[4].get("weatherCode", "116")
                    emoji = _weather_emoji(code)
                    result.append({
                        "day": day_label,
                        "icon": emoji,
                        "high": high,
                        "low": low,
                    })
                if result:
                    _weather_data = result
                    socketio.emit("weather", _weather_data)
        except Exception as e:
            print(f"Weather fetch error: {e}", flush=True)

        time.sleep(1800)  # 30 minutes


def _weather_emoji(code):
    """Convert wttr.in weather code to emoji."""
    code = str(code)
    mapping = {
        "113": "\u2600\ufe0f",     # sunny
        "116": "\u26c5",           # partly cloudy
        "119": "\u2601\ufe0f",     # cloudy
        "122": "\u2601\ufe0f",     # overcast
        "143": "\U0001f32b\ufe0f", # fog
        "176": "\U0001f326\ufe0f", # light rain
        "200": "\u26c8\ufe0f",     # thunderstorm
        "263": "\U0001f327\ufe0f", # drizzle
        "266": "\U0001f327\ufe0f", # light drizzle
        "293": "\U0001f326\ufe0f", # light rain
        "296": "\U0001f327\ufe0f", # rain
        "299": "\U0001f327\ufe0f", # moderate rain
        "302": "\U0001f327\ufe0f", # heavy rain
        "305": "\U0001f327\ufe0f", # heavy rain
        "308": "\U0001f327\ufe0f", # heavy rain
        "311": "\U0001f328\ufe0f", # freezing rain
        "326": "\U0001f328\ufe0f", # snow
        "329": "\u2744\ufe0f",     # heavy snow
        "332": "\u2744\ufe0f",     # heavy snow
        "338": "\u2744\ufe0f",     # heavy snow
        "350": "\U0001f328\ufe0f", # sleet
    }
    return mapping.get(code, "\u26c5")


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.route("/tmp_image")
def tmp_image():
    """Serve daemon-generated images (e.g. from image_search skill)."""
    path = request.args.get("path", "")
    if not path.startswith("/tmp/") or ".." in path:
        abort(403)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path)


# ---------------------------------------------------------------------------
# Action endpoints (keyboard shortcuts from browser)
# ---------------------------------------------------------------------------

BT_SPEAKER_MAC = "10:B7:F6:1B:A2:AB"

@app.route("/action/vol_up", methods=["POST"])
def vol_up():
    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"], capture_output=True)
    return jsonify(ok=True)


@app.route("/action/vol_down", methods=["POST"])
def vol_down():
    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"], capture_output=True)
    return jsonify(ok=True)


@app.route("/action/sink_external", methods=["POST"])
def sink_external():
    result = subprocess.run(
        ["bash", "-c", f"wpctl status | grep -i 'blue\\|{BT_SPEAKER_MAC}' | head -1 | grep -oP '^\\s*\\K\\d+'"],
        capture_output=True, text=True,
    )
    sink_id = result.stdout.strip()
    if sink_id:
        subprocess.run(["wpctl", "set-default", sink_id], capture_output=True)
    return jsonify(ok=True, sink=sink_id)


@app.route("/action/sink_monitor", methods=["POST"])
def sink_monitor():
    result = subprocess.run(
        ["bash", "-c", "wpctl status | grep -i 'hdmi\\|analog\\|built-in' | head -1 | grep -oP '^\\s*\\K\\d+'"],
        capture_output=True, text=True,
    )
    sink_id = result.stdout.strip()
    if sink_id:
        subprocess.run(["wpctl", "set-default", sink_id], capture_output=True)
    return jsonify(ok=True, sink=sink_id)


@app.route("/action/restart_daemon", methods=["POST"])
def restart_daemon():
    subprocess.run(["sudo", "systemctl", "restart", "grokbox"], capture_output=True)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Config API endpoints (ticker symbols, model)
# ---------------------------------------------------------------------------

@app.route("/api/ticker-symbols", methods=["GET"])
def get_ticker_symbols():
    config = _load_config()
    return jsonify(symbols=config.get("ticker_symbols", []))


@app.route("/api/ticker-symbols", methods=["POST"])
def set_ticker_symbols():
    data = request.get_json(force=True)
    symbols = data.get("symbols", [])
    config = _load_config()
    config["ticker_symbols"] = symbols
    _save_config(config)
    # Trigger immediate re-fetch
    _ticker_refresh.set()
    return jsonify(ok=True)


@app.route("/api/model", methods=["GET"])
def get_model():
    config = _load_config()
    return jsonify(model=config.get("model", "grok-4-1-fast-non-reasoning"))


@app.route("/api/model", methods=["POST"])
def set_model():
    data = request.get_json(force=True)
    model = data.get("model", "")
    if model:
        config = _load_config()
        config["model"] = model
        _save_config(config)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Spotify now-playing
# ---------------------------------------------------------------------------

SPOTIFY_POLL_INTERVAL = 5  # seconds

_spotify_auth = SpotifyOAuth(
    client_id=os.environ.get("SPOTIPY_CLIENT_ID", ""),
    client_secret=os.environ.get("SPOTIPY_CLIENT_SECRET", ""),
    redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", "https://google.com/callback/"),
    scope="user-read-playback-state user-modify-playback-state",
    cache_path="/Code/grokbox/.cache-spotify",
    open_browser=False,
)
_sp = spotipy.Spotify(auth_manager=_spotify_auth)
_spotify_data = None  # last emitted state


def _poll_spotify():
    """Background: poll Spotify for current playback state."""
    global _spotify_data
    while True:
        try:
            pb = _sp.current_playback()
            if pb and pb.get("item"):
                item = pb["item"]
                album = item.get("album", {})
                images = album.get("images", [])
                art_url = images[0]["url"] if images else ""
                data = {
                    "is_playing": pb.get("is_playing", False),
                    "track": item.get("name", ""),
                    "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                    "album": album.get("name", ""),
                    "art_url": "/api/spotify-art?url=" + art_url if art_url else "",
                    "progress_ms": pb.get("progress_ms", 0),
                    "duration_ms": item.get("duration_ms", 0),
                }
                _spotify_data = data
                socketio.emit("spotify", data)
            else:
                if _spotify_data is not None:
                    _spotify_data = None
                    socketio.emit("spotify", None)
        except Exception as e:
            print(f"Spotify poll error: {e}", flush=True)

        time.sleep(SPOTIFY_POLL_INTERVAL)


@app.route("/api/spotify-art")
def spotify_art():
    """Proxy album art from Spotify CDN to avoid CORS issues."""
    url = request.args.get("url", "")
    if not url.startswith("https://i.scdn.co/"):
        abort(403)
    try:
        r = req.get(url, timeout=10)
        return r.content, 200, {"Content-Type": r.headers.get("Content-Type", "image/jpeg")}
    except Exception:
        abort(502)


@app.route("/api/spotify/play", methods=["POST"])
def spotify_play():
    try:
        _sp.start_playback()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/spotify/pause", methods=["POST"])
def spotify_pause():
    try:
        _sp.pause_playback()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/spotify/next", methods=["POST"])
def spotify_next():
    try:
        _sp.next_track()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/spotify/prev", methods=["POST"])
def spotify_prev():
    try:
        _sp.previous_track()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


# ---------------------------------------------------------------------------
# NVIDIA Shield TV control
# ---------------------------------------------------------------------------

SHIELD_POLL_INTERVAL = 15  # seconds (reads cached state only, no WiFi traffic)
_shield_data = None  # last emitted state

# Lazy import — shield module connects on first use
_shield_mod = None

def _get_shield():
    global _shield_mod
    if _shield_mod is None:
        try:
            from skills.shield import (
                shield_power as _sp_power,
                shield_launch_app as _sl_app,
                shield_remote as _sr_cmd,
                get_shield_status as _gs_status,
            )
            _shield_mod = {
                "power": _sp_power,
                "launch": _sl_app,
                "remote": _sr_cmd,
                "status": _gs_status,
            }
        except Exception as e:
            print(f"Shield module import failed: {e}", flush=True)
            return None
    return _shield_mod


def _poll_shield():
    """Background: poll Shield for power/app state."""
    global _shield_data
    while True:
        try:
            mod = _get_shield()
            if mod:
                data = mod["status"]()
                if data != _shield_data:
                    _shield_data = data
                    socketio.emit("shield", data)
        except Exception as e:
            print(f"Shield poll error: {e}", flush=True)
        time.sleep(SHIELD_POLL_INTERVAL)


@app.route("/api/shield/power", methods=["POST"])
def shield_power():
    mod = _get_shield()
    if not mod:
        return jsonify(ok=False, error="Shield not available"), 503
    data = request.get_json(force=True)
    action = data.get("action", "toggle")
    result = mod["power"](action)
    return jsonify(ok=True, result=result)


@app.route("/api/shield/launch", methods=["POST"])
def shield_launch():
    mod = _get_shield()
    if not mod:
        return jsonify(ok=False, error="Shield not available"), 503
    data = request.get_json(force=True)
    app_name = data.get("app", "")
    if not app_name:
        return jsonify(ok=False, error="Missing app name"), 400
    result = mod["launch"](app_name)
    return jsonify(ok=True, result=result)


@app.route("/api/shield/key", methods=["POST"])
def shield_key():
    mod = _get_shield()
    if not mod:
        return jsonify(ok=False, error="Shield not available"), 503
    data = request.get_json(force=True)
    key = data.get("key", "")
    if not key:
        return jsonify(ok=False, error="Missing key"), 400
    result = mod["remote"](key)
    return jsonify(ok=True, result=result)


@app.route("/api/shield/status", methods=["GET"])
def shield_status():
    mod = _get_shield()
    if not mod:
        return jsonify(is_on=None, current_app="")
    return jsonify(**mod["status"]())


# ---------------------------------------------------------------------------
# Journalctl tail → SocketIO events
# ---------------------------------------------------------------------------

_LATENCY_RE = re.compile(r"Grok responded in ([\d.]+)s: (.+)")

# Voice commands that trigger wallpaper change
_BG_COMMANDS = ["new background", "change background", "next background",
                "switch background", "new wallpaper", "change wallpaper"]

def _parse_and_emit(line):
    """Parse a single journalctl line and emit the appropriate socket event."""

    msg = line
    info_match = re.search(r"\[(?:INFO|WARNING|ERROR)\]\s*(.*)", line)
    if info_match:
        msg = info_match.group(1)

    socketio.emit("log", {"line": line.rstrip()})

    # State: idle/listening
    if "starts listening for 'Hey Jarvis'" in msg or "Listening for wake word again" in msg:
        socketio.emit("state", {"state": "listening"})
        return

    # State: triggered
    if "Wake word detected" in msg:
        socketio.emit("state", {"state": "triggered"})
        return

    # State: transcribing
    if "AssemblyAI streaming channel opened" in msg:
        socketio.emit("state", {"state": "transcribing"})
        return

    # Partial transcript
    if "[Partial]:" in msg:
        text = msg.split("[Partial]:", 1)[1].strip().lstrip(".")
        socketio.emit("transcript", {"text": text, "final": False})
        return

    # Final transcript — also check for background change voice commands
    if "[FINAL]" in msg:
        text = msg.split("[FINAL]", 1)[1].strip()
        socketio.emit("transcript", {"text": text, "final": True})
        # Check for background change command
        lower = text.lower()
        if any(cmd in lower for cmd in _BG_COMMANDS):
            advance_wallpaper()
        return

    # State: querying
    if "Querying [" in msg:
        socketio.emit("state", {"state": "querying"})
        return

    # State: responding + response text
    m = _LATENCY_RE.search(msg)
    if m:
        latency = float(m.group(1))
        text = m.group(2).strip()
        socketio.emit("response", {"text": text, "latency": latency})
        socketio.emit("state", {"state": "responding"})
        return

    # TTS playing
    if "Kokoro generated TTS" in msg or "SYSTEM RESPONDING" in msg:
        socketio.emit("state", {"state": "responding"})
        return

    # Image display — set as wallpaper background only (no overlay)
    if "[SHOW_IMAGE]" in msg:
        global _current_wallpaper
        path = msg.split("[SHOW_IMAGE]", 1)[1].strip()
        if os.path.isfile(path):
            _current_wallpaper = path
            socketio.emit("wallpaper", {"url": "/tmp_image?path=" + path + "&t=" + str(time.time())})
        return

    # Close images (legacy — images now go to background only)
    if "[CLOSE_IMAGES]" in msg:
        return

    # Pause/sleep
    if "Pause command received" in msg or "Listening paused" in msg:
        socketio.emit("state", {"state": "paused"})
        return

    # Resume
    if "resumed from sleep" in msg or "Listening resumed" in msg:
        socketio.emit("state", {"state": "listening"})
        return


def _tail_journalctl():
    """Background task: tail journalctl for grokbox.service and parse lines."""
    proc = subprocess.Popen(
        ["journalctl", "-u", "grokbox", "-f", "--no-pager", "-n", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    print("journalctl tail thread started", flush=True)
    for line in proc.stdout:
        try:
            _parse_and_emit(line)
        except Exception as e:
            print(f"Parse error: {e}", flush=True)


# ---------------------------------------------------------------------------
# System health monitor
# ---------------------------------------------------------------------------

HEALTH_INTERVAL = 30  # seconds
_health_data = {}

def _check_health():
    """Background task: check connectivity to all services."""
    global _health_data
    while True:
        health = {}

        # Daemon (systemd service)
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "grokbox"],
                capture_output=True, text=True, timeout=5,
            )
            health["Daemon"] = r.stdout.strip() == "active"
        except Exception:
            health["Daemon"] = False

        # Kokoro TTS server
        try:
            r = req.get("http://10.0.0.226:5050/tts", timeout=5)
            # A GET to the TTS endpoint may return 405 or 200 — either means it's alive
            health["Kokoro TTS"] = r.status_code in (200, 405, 400)
        except Exception:
            health["Kokoro TTS"] = False

        # xAI Grok API (just check DNS/connectivity, don't burn tokens)
        try:
            r = req.head("https://api.x.ai/v1/models", timeout=5,
                         headers={"Authorization": f"Bearer {os.environ.get('XAI_KEY', '')}"})
            health["xAI Grok"] = r.status_code in (200, 401, 403)
        except Exception:
            health["xAI Grok"] = False

        # AssemblyAI
        try:
            r = req.get("https://api.assemblyai.com/v2", timeout=5,
                        headers={"Authorization": os.environ.get("ASSEMBLYAI_KEY", "")})
            health["AssemblyAI"] = r.status_code in (200, 401, 403, 404)
        except Exception:
            health["AssemblyAI"] = False

        # PipeWire
        try:
            r = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=5,
                               env={**os.environ, "XDG_RUNTIME_DIR": "/run/user/1000"})
            health["PipeWire"] = r.returncode == 0
        except Exception:
            health["PipeWire"] = False

        # Bluetooth speaker
        try:
            r = subprocess.run(
                ["bluetoothctl", "info", "10:B7:F6:1B:A2:AB"],
                capture_output=True, text=True, timeout=5,
            )
            health["BT Speaker"] = "Connected: yes" in r.stdout
        except Exception:
            health["BT Speaker"] = False

        # Raspotify
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "raspotify"],
                capture_output=True, text=True, timeout=5,
            )
            health["Raspotify"] = r.stdout.strip() == "active"
        except Exception:
            health["Raspotify"] = False

        _health_data = health
        socketio.emit("health", _health_data)
        time.sleep(HEALTH_INTERVAL)


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    print("Browser connected", flush=True)
    socketio.emit("state", {"state": "listening"})
    if _current_wallpaper:
        socketio.emit("wallpaper", {"url": "/wallpaper/current?" + str(time.time())})
    if _ticker_data:
        socketio.emit("tickers", _ticker_data)
    if _weather_data:
        socketio.emit("weather", _weather_data)
    if _health_data:
        socketio.emit("health", _health_data)
    if _spotify_data:
        socketio.emit("spotify", _spotify_data)
    if _shield_data:
        socketio.emit("shield", _shield_data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    socketio.start_background_task(_tail_journalctl)
    socketio.start_background_task(_wallpaper_rotation)
    socketio.start_background_task(_fetch_tickers)
    socketio.start_background_task(_fetch_weather)
    socketio.start_background_task(_check_health)
    socketio.start_background_task(_poll_spotify)
    socketio.start_background_task(_poll_shield)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
