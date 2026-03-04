import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

load_dotenv("/Code/grokbox/.env")

auth = SpotifyOAuth(
    client_id=os.environ["SPOTIPY_CLIENT_ID"],
    client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI", "https://google.com/callback/"),
    scope="user-modify-playback-state user-read-playback-state",
    cache_path="/Code/grokbox/.cache-spotify",
    open_browser=False
)

sp = spotipy.Spotify(auth_manager=auth)

devices = sp.devices()
print("=== Available Spotify Devices ===")
if devices and devices.get("devices"):
    for d in devices["devices"]:
        print(f"  Name: {d['name']}")
        print(f"  ID:   {d['id']}")
        print(f"  Type: {d['type']}")
        print(f"  Active: {d['is_active']}")
        print()
else:
    print("  NO DEVICES FOUND")

current = sp.current_playback()
if current:
    print(f"Currently playing: {current.get('is_playing')}")
    print(f"Device: {current.get('device', {}).get('name')}")
else:
    print("No active playback session.")
