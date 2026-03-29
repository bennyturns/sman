"""Intelligent request routing between local and cloud models."""

from __future__ import annotations

import re
from enum import Enum

from sman.config import LLMConfig


class RouteTarget(Enum):
    LOCAL = "local"
    CLOUD = "cloud"


# Patterns that indicate simple, single-tool requests (route to local)
SIMPLE_PATTERNS = [
    r"^(show|check|get|list|what is|what are|what'?s)\b.*(status|running|active|enabled|installed|listening|open|using)",
    r"^(restart|start|stop|reload)\s+\w+",
    r"^(install|remove|update)\s+\w+$",
    r"^(open|close|add|remove)\s+(port|firewall)",
    r"^(tail|show|read|cat)\s+(log|file|config)",
    r"^(who|uptime|free|df|top|ps)\b",
    r"^(enable|disable)\s+\w+",
    r"^(how much|disk|memory|cpu|load)\b",
]

# Patterns that indicate complex, multi-step requests (route to cloud)
COMPLEX_PATTERNS = [
    r"\b(configure|set up|setup|deploy|migrate)\b.*\b(as|for|with|from|to)\b",
    r"\bwhy\b.*(not|fail|error|broken|slow|can'?t|unable|down)",
    r"\btroubleshoot\b",
    r"\b(diagnose|investigate|analyze|audit)\b",
    r"\b(security|harden|secure|protect)\b",
    r"\b(proxy|relay|forward|redirect|load.?balanc)\b",
    r"\b(ssl|tls|certificate|cert)\b.*\b(set up|configure|generate|renew)\b",
    r"\b(backup|restore|replicate|cluster)\b.*\b(set up|configure)\b",
    r"\b(and|then|also|after that)\b",
    r"\b(optimize|tune|performance)\b",
    r"\bmultiple\b|\bseveral\b|\ball\b.*\bserv",
]


def classify_complexity(request: str) -> RouteTarget:
    """Classify a request as simple (local) or complex (cloud)."""
    lower = request.lower().strip()

    # Check complex patterns first (they're more specific)
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, lower):
            return RouteTarget.CLOUD

    # Check simple patterns
    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, lower):
            return RouteTarget.LOCAL

    # Default to cloud for ambiguous requests
    return RouteTarget.CLOUD


def get_route(request: str, config: LLMConfig, force: str | None = None) -> RouteTarget:
    """Determine where to route a request.

    Args:
        request: The user's natural language request
        config: LLM configuration
        force: Override routing - "local" or "cloud"

    Returns:
        RouteTarget indicating where to send the request
    """
    # Explicit override
    if force == "local":
        return RouteTarget.LOCAL
    if force == "cloud":
        return RouteTarget.CLOUD

    # If no local model configured, always use cloud
    if not config.local_provider or not config.local_model:
        return RouteTarget.CLOUD

    # If auto-routing disabled, use cloud
    if not config.auto_route:
        return RouteTarget.CLOUD

    return classify_complexity(request)
