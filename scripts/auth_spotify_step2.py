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

with open("/Code/grokbox/spotify_return_url.txt", "r") as f:
    r_url = f.read().strip()

if r_url:
    code = auth.parse_response_code(r_url)
    token = auth.get_access_token(code, as_dict=False)
    print("SPOTIFY TOKEN CACHED SUCCESSFULLY!")
else:
    print("No URL found.")
