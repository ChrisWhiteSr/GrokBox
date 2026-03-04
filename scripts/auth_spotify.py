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

url = auth.get_authorize_url()

with open("/Code/grokbox/spotify_url.txt", "w") as f:
    f.write(url)
