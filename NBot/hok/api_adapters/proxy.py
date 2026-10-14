"""Explicit outbound routing helpers for external API adapters."""

import requests

from ..zstatic import clash_proxy_url


def direct_request(method, url, **kwargs):
    """Send one request directly without inheriting ambient proxy settings."""
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


def clash_request(method, url, **kwargs):
    """Send one request only through the configured Clash proxy."""
    if not clash_proxy_url:
        raise ValueError("Clash proxy configuration missing: Proxy.clash_url or HOK_CLASH_PROXY_URL")

    with requests.Session() as session:
        session.trust_env = False
        session.proxies.update({"http": clash_proxy_url, "https": clash_proxy_url})
        return session.request(method, url, **kwargs)


__all__ = ["clash_request", "direct_request"]
