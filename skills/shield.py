"""
NVIDIA Shield TV control via androidtvremote2.
Provides Grok tool functions and shared connection helpers for the web UI server.
"""
import asyncio
import logging
import os
import threading
import time
import urllib.parse

from androidtvremote2 import AndroidTVRemote, CannotConnect, InvalidAuth, ConnectionClosed

log = logging.getLogger("grokbox.skills.shield")

SHIELD_IP = "10.0.0.167"
CERT_DIR = "/Code/grokbox/.shield-cert"
CERT_FILE = os.path.join(CERT_DIR, "shield_cert.pem")
KEY_FILE = os.path.join(CERT_DIR, "shield_key.pem")

# ---- App name -> package ID map ----

APP_MAP = {
    "youtube tv":   "com.google.android.youtube.tvunplugged",
    "yttv":         "com.google.android.youtube.tvunplugged",
    "plex":         "com.plexapp.android",
    "youtube":      "com.google.android.youtube.tv",
    "prime video":  "com.amazon.amazonvideo.livingroom",
    "amazon prime": "com.amazon.amazonvideo.livingroom",
    "spotify":      "com.spotify.tv.android",
    "apple tv":     "com.apple.atve.androidtv.appletv",
    "apple tv+":    "com.apple.atve.androidtv.appletv",
    "stremio":      "com.stremio.one",
    "smarttube":    "com.liskovsoft.smarttubetv.beta",
    "smart tube":   "com.liskovsoft.smarttubetv.beta",
}

# ---- Key command map (friendly name -> KEYCODE) ----

KEY_MAP = {
    "home":     "HOME",
    "back":     "BACK",
    "up":       "DPAD_UP",
    "down":     "DPAD_DOWN",
    "left":     "DPAD_LEFT",
    "right":    "DPAD_RIGHT",
    "select":   "DPAD_CENTER",
    "ok":       "DPAD_CENTER",
    "enter":    "DPAD_CENTER",
    "play":     "MEDIA_PLAY",
    "pause":    "MEDIA_PAUSE",
    "playpause":"MEDIA_PLAY_PAUSE",
    "stop":     "MEDIA_STOP",
    "next":     "MEDIA_NEXT",
    "previous": "MEDIA_PREVIOUS",
    "rewind":   "MEDIA_REWIND",
    "forward":  "MEDIA_FAST_FORWARD",
    "mute":     "VOLUME_MUTE",
    "vol_up":   "VOLUME_UP",
    "vol_down": "VOLUME_DOWN",
}

# ---- On-demand connection with auto-disconnect ----
# Connects only when a command is sent, disconnects after IDLE_TIMEOUT
# to avoid persistent WiFi traffic that interferes with BT audio.

IDLE_TIMEOUT = 30  # seconds before auto-disconnect

_loop = None
_loop_thread = None
_remote = None
_lock = threading.Lock()
_last_use = 0.0
_idle_timer = None


def _ensure_loop():
    """Start a dedicated asyncio event loop in a daemon thread."""
    global _loop, _loop_thread
    if _loop is not None:
        return
    _loop = asyncio.new_event_loop()
    _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True, name="shield-aio")
    _loop_thread.start()


def _run(coro):
    """Run an async coroutine on the background loop, blocking until done."""
    _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=15)


def _schedule_disconnect():
    """Reset the idle disconnect timer."""
    global _idle_timer, _last_use
    _last_use = time.time()
    if _idle_timer is not None:
        _idle_timer.cancel()
    _idle_timer = threading.Timer(IDLE_TIMEOUT, _auto_disconnect)
    _idle_timer.daemon = True
    _idle_timer.start()


def _auto_disconnect():
    """Disconnect if idle for IDLE_TIMEOUT seconds."""
    global _remote, _idle_timer
    with _lock:
        if _remote is not None and (time.time() - _last_use) >= IDLE_TIMEOUT:
            try:
                _remote.disconnect()
            except Exception:
                pass
            _remote = None
            _idle_timer = None
            log.info("Shield auto-disconnected (idle %ds)", IDLE_TIMEOUT)


async def _async_connect():
    """Create and connect the AndroidTVRemote."""
    global _remote
    os.makedirs(CERT_DIR, exist_ok=True)
    remote = AndroidTVRemote(
        client_name="GrokBox",
        certfile=CERT_FILE,
        keyfile=KEY_FILE,
        host=SHIELD_IP,
        loop=_loop,
    )
    await remote.async_generate_cert_if_missing()
    try:
        await remote.async_connect()
    except InvalidAuth:
        log.error("Shield not paired — run the pairing script first")
        raise
    _remote = remote
    log.info("Connected to NVIDIA Shield at %s", SHIELD_IP)
    return remote


def get_remote():
    """Get the connected AndroidTVRemote instance (connects on demand)."""
    global _remote
    with _lock:
        if _remote is None:
            _run(_async_connect())
        _schedule_disconnect()
        return _remote


def _reconnect():
    """Force a reconnect on connection loss."""
    global _remote
    with _lock:
        _remote = None
    try:
        get_remote()
    except Exception as e:
        log.error("Shield reconnect failed: %s", e)


def get_shield_status():
    """Return cached shield status without connecting (no WiFi traffic)."""
    if _remote is not None:
        try:
            return {
                "is_on": _remote.is_on,
                "current_app": _remote.current_app or "",
            }
        except Exception:
            pass
    return {"is_on": None, "current_app": ""}


# ---- Grok tool functions (synchronous, return strings) ----

def shield_power(action: str = "toggle"):
    """Turn the Shield on, off, or toggle power."""
    try:
        remote = get_remote()
        action = action.lower().strip()
        if action == "on":
            remote.send_key_command("WAKEUP")
            return "Shield TV powered on."
        elif action == "off":
            remote.send_key_command("SLEEP")
            return "Shield TV powered off."
        else:
            remote.send_key_command("POWER")
            return "Shield TV power toggled."
    except (ConnectionClosed, OSError):
        _reconnect()
        return "Lost connection to Shield — reconnecting. Try again."
    except Exception as e:
        log.error("shield_power error: %s", e)
        return f"Failed to control Shield power: {e}"


def shield_launch_app(app_name: str):
    """Launch an app on the Shield by friendly name."""
    try:
        remote = get_remote()
        name = app_name.lower().strip()
        package = APP_MAP.get(name)
        if not package:
            return f"Unknown app '{app_name}'. Available: {', '.join(sorted(set(APP_MAP.values())))}"
        remote.send_launch_app_command(package)
        return f"Launching {app_name} on Shield TV."
    except (ConnectionClosed, OSError):
        _reconnect()
        return "Lost connection to Shield — reconnecting. Try again."
    except Exception as e:
        log.error("shield_launch_app error: %s", e)
        return f"Failed to launch app: {e}"


def shield_remote(command: str):
    """Send a remote control command to the Shield."""
    try:
        remote = get_remote()
        cmd = command.lower().strip()
        keycode = KEY_MAP.get(cmd)
        if not keycode:
            return f"Unknown command '{command}'. Available: {', '.join(sorted(KEY_MAP.keys()))}"
        remote.send_key_command(keycode)
        return f"Sent {command} to Shield TV."
    except (ConnectionClosed, OSError):
        _reconnect()
        return "Lost connection to Shield — reconnecting. Try again."
    except Exception as e:
        log.error("shield_remote error: %s", e)
        return f"Failed to send command: {e}"


# ---- App-specific search macros ----

# Apps where we can deep-link to a search URL directly
_URL_SEARCH_APPS = {
    "youtube":   "https://www.youtube.com/results?search_query={q}",
    "smarttube": "https://www.youtube.com/results?search_query={q}",
}

# Apps where we launch first, then use SEARCH key + send_text
_MACRO_SEARCH_APPS = {
    "youtube tv": "com.google.android.youtube.tvunplugged",
    "yttv":       "com.google.android.youtube.tvunplugged",
    "plex":       "com.plexapp.android",
    "apple tv":   "com.apple.atve.androidtv.appletv",
    "stremio":    "com.stremio.one",
    "prime video": "com.amazon.amazonvideo.livingroom",
}


def shield_watch(query: str, app: str = "youtube tv"):
    """Search for and play content on the Shield. Handles deep links or search macros."""
    try:
        remote = get_remote()
        app_key = app.lower().strip()
        q = query.strip()

        # URL-based search (YouTube / SmartTube) — instant, no macro needed
        if app_key in _URL_SEARCH_APPS:
            url = _URL_SEARCH_APPS[app_key].format(q=urllib.parse.quote_plus(q))
            remote.send_launch_app_command(url)
            log.info("shield_watch: deep-link search '%s' on %s", q, app_key)
            return f"Searching for '{q}' on {app}."

        # Macro-based search: launch app → SEARCH key → type query → select
        if app_key in _MACRO_SEARCH_APPS:
            package = _MACRO_SEARCH_APPS[app_key]
            remote.send_launch_app_command(package)
            log.info("shield_watch: macro search '%s' on %s", q, app_key)
            time.sleep(5)  # wait for app to fully load
            remote.send_key_command(84)  # KEYCODE_SEARCH
            time.sleep(2)  # wait for search UI to appear
            remote.send_text(q)
            time.sleep(1)
            remote.send_key_command("DPAD_CENTER")  # submit search
            time.sleep(3)  # wait for search results to populate
            remote.send_key_command("DPAD_DOWN")  # move to first result
            time.sleep(0.3)
            remote.send_key_command("DPAD_CENTER")  # select it
            return f"Searching for '{q}' on {app} and selecting the first result."

        # Fallback — just launch the app
        package = APP_MAP.get(app_key)
        if package:
            remote.send_launch_app_command(package)
            return f"Launched {app} but search isn't supported for this app."

        return f"Unknown app '{app}'."

    except (ConnectionClosed, OSError):
        _reconnect()
        return "Lost connection to Shield — reconnecting. Try again."
    except Exception as e:
        log.error("shield_watch error: %s", e)
        return f"Failed to search on Shield: {e}"


# ---- Grok tool schemas ----

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "shield_power",
            "description": "Control NVIDIA Shield TV power. Can turn on, turn off, or toggle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "toggle"],
                        "description": "Power action: 'on' to wake, 'off' to sleep, 'toggle' to switch."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shield_launch_app",
            "description": "Launch an app on the NVIDIA Shield TV by name. Supported apps: YouTube TV, Plex, YouTube, Prime Video, Spotify, Apple TV, Stremio, SmartTube.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "App name, e.g. 'youtube tv', 'plex', 'prime video', 'spotify', 'youtube', 'apple tv', 'stremio', 'smarttube'."
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shield_watch",
            "description": "Search for and play specific content on the NVIDIA Shield TV. Use this when the user wants to watch a specific channel, show, or video. For YouTube TV this opens search and types the query automatically. For YouTube/SmartTube it deep-links to search results. Examples: 'put on Fox News' (app=youtube tv, query=Fox News), 'play cat videos' (app=smarttube, query=cat videos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, e.g. 'Fox News', 'CNN', 'Seinfeld', 'cat videos'."
                    },
                    "app": {
                        "type": "string",
                        "description": "Which app to search in. Default 'youtube tv' for live TV channels. Use 'smarttube' or 'youtube' for general videos, 'plex' for local library, 'stremio' for movies/shows.",
                        "default": "youtube tv"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shield_remote",
            "description": "Send a remote control command to the NVIDIA Shield TV. Supports navigation (home, back, up, down, left, right, select), media (play, pause, stop, next, previous, rewind, forward), and volume (mute, vol_up, vol_down).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Remote command: home, back, up, down, left, right, select, play, pause, stop, next, previous, rewind, forward, mute, vol_up, vol_down."
                    }
                },
                "required": ["command"]
            }
        }
    },
]
