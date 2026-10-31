"""
SSRF guard for server-to-server fetches.

Every URL this server fetches on a user's behalf — remote actor documents
(``/api/follow``, inbox ``keyId``), WebFinger lookups, and activity delivery
to remote inboxes — must pass :func:`check_fetch_url` first. Rules:

  • only ``http``/``https`` schemes
  • link-local (169.254.0.0/16 — cloud metadata endpoints), unspecified
    (0.0.0.0), multicast and reserved addresses are always refused
  • public hosts are only contacted over HTTPS; loopback/private hosts may
    use plain HTTP (local dev servers have no TLS certificate)

Hostnames are resolved and every resulting address is checked, so a hostname
that points at a metadata IP is refused as well. (DNS rebinding after this
check is out of scope for the MVP — httpx does not follow redirects by
default, so a redirect cannot be used to smuggle a forbidden target.)
"""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger("pheme.fetchguard")

_IP = ipaddress.IPv4Address | ipaddress.IPv6Address


def _forbidden_ip(ip: _IP) -> bool:
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved


def _public_ip(ip: _IP) -> bool:
    # Loopback/private stay reachable over HTTP for local dev federation;
    # link-local is already refused by _forbidden_ip.
    return not (ip.is_loopback or ip.is_private)


async def check_fetch_url(url: str) -> str | None:
    """Return a refusal reason if the server must not fetch *url*, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme!r} is not allowed"
    host = (parsed.hostname or "").strip("[]").lower()
    if not host:
        return "URL has no host"

    try:
        ip: _IP | None = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if _forbidden_ip(ip):
            return f"host {host} is a forbidden address"
        if parsed.scheme == "http" and _public_ip(ip):
            return f"public host {host} requires https"
        return None

    # Hostname — resolve and check every address.
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        return f"host {host} does not resolve: {exc}"

    ips: list[_IP] = []
    for info in infos:
        first = info[4][0]
        if not isinstance(first, str):
            continue
        addr = first.split("%", 1)[0]  # strip IPv6 zone id
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        return f"host {host} has no usable addresses"
    for ip in ips:
        if _forbidden_ip(ip):
            return f"host {host} resolves to forbidden address {ip}"
    if parsed.scheme == "http" and any(_public_ip(ip) for ip in ips):
        return f"public host {host} requires https"
    return None
