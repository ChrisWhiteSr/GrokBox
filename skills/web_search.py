import logging
import json
import os
import urllib.request
from dotenv import load_dotenv

load_dotenv("/Code/grokbox/.env")
log = logging.getLogger("grokbox.skills.web_search")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Searches the web for current information. Use this when the user asks about news, facts, people, events, how-to questions, or anything that might need up-to-date information beyond your training data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, e.g. 'latest SpaceX launch' or 'how to reset a Raspberry Pi'"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


def web_search(query: str):
    if not TAVILY_API_KEY:
        return "Web search is not configured — missing TAVILY_API_KEY."

    log.info(f"Web search: {query}")
    try:
        payload = json.dumps({
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
        }).encode()

        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        results = data.get("results", [])
        if not results:
            return "No search results found. Tell the user you couldn't find anything."

        lines = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            lines.append(f"- {title}: {content}")

        summary = "\n".join(lines)
        return (
            f"Search results for '{query}':\n{summary}\n\n"
            "Summarize these results naturally in 2-3 spoken sentences. "
            "Do not use links, citations, or formatting."
        )
    except Exception as e:
        log.error(f"Web search failed: {e}")
        return "Web search failed. Tell the user you couldn't reach the search engine right now."
