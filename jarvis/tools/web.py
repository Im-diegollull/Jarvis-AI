"""Server-side web tools. Anthropic runs these; we only declare them."""

from jarvis.agent.registry import ToolRegistry

WEB_SEARCH = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 8,
}

WEB_FETCH = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 8,
    "max_content_tokens": 40_000,
}


def register(registry: ToolRegistry) -> None:
    registry.add(WEB_SEARCH)
    registry.add(WEB_FETCH)
