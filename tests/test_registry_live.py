"""CI sanity check for the known-source registry (issue #21 acceptance).

Verifies every 'available' registry endpoint still answers — DNS
resolves, TLS handshakes, the server returns *something*. Auth-gated
APIs legitimately answer 401/403 to unkeyed requests, so the bar is
"the host is alive and serving," not "anonymous access works."

Marked ``network``: excluded from the default run, executed explicitly
(locally or in CI) with:

    python -m pytest -m network tests/test_registry_live.py
"""

from __future__ import annotations

import httpx
import pytest

from cartograph_ai.registry import load_registry
from cartograph_ai.stages.http_probe import DEFAULT_USER_AGENT

_LIVE_ENDPOINTS = [
    (domain, ep["url"])
    for domain, entry in load_registry()["sources"].items()
    if entry["status"] == "available"
    for ep in entry["endpoints"]
]


@pytest.mark.network
@pytest.mark.parametrize("domain,url", _LIVE_ENDPOINTS, ids=[u for _, u in _LIVE_ENDPOINTS])
def test_registry_endpoint_is_alive(domain: str, url: str):
    with httpx.Client(
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    ) as client:
        response = client.get(url)
    # The server answered: the registry entry points at live
    # infrastructure. 401/403 from auth-gated APIs and 404 on root
    # paths of path-structured APIs are acceptable; 5xx and transport
    # errors are not.
    assert response.status_code < 500, (
        f"{domain}: {url} answered {response.status_code}; "
        "registry entry may be stale"
    )
