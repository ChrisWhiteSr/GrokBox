import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
from dotenv import load_dotenv

load_dotenv("/Code/grokbox/.env")
log = logging.getLogger("grokbox.skills.spotify")

SCOPE = "user-modify-playback-state user-read-playback-state"
CACHE_DIR = "/Code/grokbox/.cache-spotify"

auth_manager = SpotifyOAuth(
    client_id=os.environ["SPOTIPY_CLIENT_ID"],
    client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI", "https://google.com/callback/"),
    scope=SCOPE,
    cache_path=CACHE_DIR,
    open_browser=False
)

sp = spotipy.Spotify(auth_manager=auth_manager)

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "play_spotify",
            "description": "Starts or resumes audio playback on Spotify. Can also play a specific track, artist, or album if a search query is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query (e.g., 'The Beatles', 'Bohemian Rhapsody', 'workout playlist'). If empty, it just resumes the current paused track."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_spotify",
            "description": "Pauses the currently playing audio on Spotify.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skip_track_spotify",
            "description": "Skips to the next track in the current Spotify queue.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


_PREFERRED_DEVICES = ["GrokBox", "Denon AVR-S760H"]

def _get_device_id():
    """Pick the best available Spotify device.

    Priority order:
      1. Preferred devices (GrokBox local, then Denon AVR for house speakers)
      2. Any AVR/Speaker type (big speakers over phones)
      3. Active device
      4. Fallback by type priority
    """
    devices = sp.devices().get("devices", [])
    if not devices:
        return None

    # 1. Preferred devices by name — GrokBox first, then Denon
    for name in _PREFERRED_DEVICES:
        for d in devices:
            if d["name"] == name:
                log.info(f"Routing to preferred device: {d['name']} (id={d['id'][:8]}...)")
                return d["id"]

    # 2. Any AVR or Speaker type (house speakers > phone/TV)
    for d in devices:
        if d["type"] in ("AVR", "Speaker"):
            log.info(f"Routing to speaker device: {d['name']} ({d['type']})")
            return d["id"]

    # 3. Active device
    active = [d for d in devices if d["is_active"]]
    if active:
        log.info(f"Routing to active device: {active[0]['name']}")
        return active[0]["id"]

    # 4. Fallback by type priority
    priority = {"AVR": 0, "Speaker": 1, "Computer": 2, "Smartphone": 3, "TV": 4}
    devices_sorted = sorted(devices, key=lambda d: priority.get(d["type"], 99))
    chosen = devices_sorted[0]
    log.info(f"Fallback — auto-selecting: {chosen['name']} ({chosen['type']})")
    return chosen["id"]


def play_spotify(query: str = None):
    try:
        device_id = _get_device_id()
        if not device_id:
            return "No Spotify devices found. Open Spotify on any device and try again."

        # Transfer playback to GrokBox so the user doesn't have to switch manually
        try:
            sp.transfer_playback(device_id, force_play=False)
        except Exception:
            pass  # May fail if already active here; not critical

        if query:
            log.info(f"Searching Spotify for: {query}")
            results = sp.search(q=query, limit=1, type="track,artist,album,playlist")

            if results["tracks"]["items"]:
                track = results["tracks"]["items"][0]
                album_uri = track["album"]["uri"]
                track_uri = track["uri"]
                # Play the album starting at the requested track for continuous playback
                sp.start_playback(
                    device_id=device_id,
                    context_uri=album_uri,
                    offset={"uri": track_uri}
                )
                return f"Playing {track['name']} by {track['artists'][0]['name']} on Spotify."
            elif results["artists"]["items"]:
                uri = results["artists"]["items"][0]["uri"]
                sp.start_playback(device_id=device_id, context_uri=uri)
                return f"Playing {query} on Spotify."
            elif results["albums"]["items"]:
                uri = results["albums"]["items"][0]["uri"]
                sp.start_playback(device_id=device_id, context_uri=uri)
                return f"Playing {query} on Spotify."
            elif results["playlists"]["items"]:
                uri = results["playlists"]["items"][0]["uri"]
                sp.start_playback(device_id=device_id, context_uri=uri)
                return f"Playing {query} on Spotify."
            else:
                return f"Sorry, I couldn't find {query} on Spotify."
        else:
            sp.start_playback(device_id=device_id)
            return "Resumed Spotify playback."

    except spotipy.exceptions.SpotifyException as e:
        log.error(f"Spotify Error: {e}")
        return f"Spotify error: {e}"
    except Exception as e:
        log.error(f"General Error: {e}")
        return "An internal error occurred communicating with Spotify."


def pause_spotify():
    try:
        device_id = _get_device_id()
        sp.pause_playback(device_id=device_id)
        return "Paused Spotify playback."
    except spotipy.exceptions.SpotifyException as e:
        log.error(f"Spotify Error: {e}")
        return "Failed to pause. Ensure there is an active Spotify session."


def skip_track_spotify():
    try:
        device_id = _get_device_id()
        sp.next_track(device_id=device_id)
        return "Skipped to the next track on Spotify."
    except spotipy.exceptions.SpotifyException as e:
        log.error(f"Spotify Error: {e}")
        return "Failed to skip. Ensure there is an active Spotify session."
