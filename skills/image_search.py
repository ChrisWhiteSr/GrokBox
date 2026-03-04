import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from dotenv import load_dotenv

load_dotenv("/Code/grokbox/.env")
log = logging.getLogger("grokbox.skills.image_search")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# Persistent session with retry logic for flaky Pi network
_session = requests.Session()
_retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry))

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_image",
            "description": "Search for an image and display it on the GrokBox screen. You MUST call this tool every time the user asks to see, show, or display any picture or image. You cannot display images without calling this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, e.g. 'Northern Lights', 'Golden Gate Bridge at sunset', 'cute corgi'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_images",
            "description": "Close all displayed images on the GrokBox screen. Use this when the user asks to close, dismiss, or clear the pictures.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def search_image(query: str):
    if not SERPAPI_KEY:
        return "Image search is not configured — missing SERPAPI_KEY."

    log.info(f"Searching Google Images for: {query}")
    try:
        resp = _session.get("https://serpapi.com/search", params={
            "engine": "google_images",
            "q": query,
            "api_key": SERPAPI_KEY,
        }, timeout=(10, 30))

        if resp.status_code != 200:
            log.error(f"SerpAPI error {resp.status_code}: {resp.text}")
            return f"Image search failed with status {resp.status_code}."

        data = resp.json()
        results = data.get("images_results", [])
        if not results:
            return f"No images found for '{query}'."

        # Unique filename so multiple images can coexist
        img_path = f"/tmp/grokbox_image_{int(time.time())}.jpg"

        # Try up to 5 original image URLs, then fall back to thumbnail
        for r in results[:5]:
            url = r.get("original")
            if not url:
                continue
            try:
                img_resp = _session.get(url, timeout=(5, 10), headers={"User-Agent": "Mozilla/5.0"})
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    with open(img_path, "wb") as f:
                        f.write(img_resp.content)
                    log.info(f"[SHOW_IMAGE] {img_path}")
                    return f"Displaying an image of {query} on the screen now."
            except Exception:
                continue

        # Fallback: use Google-hosted thumbnail (always available)
        thumb_url = results[0].get("thumbnail")
        if thumb_url:
            try:
                img_resp = _session.get(thumb_url, timeout=(5, 10))
                if img_resp.status_code == 200:
                    with open(img_path, "wb") as f:
                        f.write(img_resp.content)
                    log.info(f"[SHOW_IMAGE] {img_path}")
                    return f"Displaying an image of {query} on the screen now."
            except Exception:
                pass

        return f"Found images for '{query}' but couldn't download any of them."

    except Exception as e:
        log.error(f"Image search error: {e}")
        return "Something went wrong while searching for that image."


def close_images():
    log.info("[CLOSE_IMAGES]")
    return "All images have been closed and deleted. To show any new image, you MUST call search_image again."
