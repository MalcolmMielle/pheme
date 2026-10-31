"""
HTTP Signatures for ActivityPub server-to-server authentication.

When server A delivers an activity to server B's inbox, server A signs
the request with the *sending actor's* private key.  Server B fetches the
actor's public key, verifies the signature, and only then accepts the
activity.

The signature covers:
  - (request-target): the HTTP method + path
  - host: the target host
  - date: the current timestamp
  - digest: SHA-256 of the body (optional but recommended)

RFC reference: https://datatracker.ietf.org/doc/html/draft-cavage-http-signatures-12

Implementation detail
─────────────────────
We use `cryptography` for RSA-SHA256 signing and verification.  The
`Signature` header looks like:

  Signature: keyId="https://a.example/actor/alice#main-key",
             algorithm="rsa-sha256",
             headers="(request-target) host date digest",
             signature="Base64...""
"""

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


def generate_keypair() -> tuple[str, str]:
    """Generate a fresh RSA 2048-bit keypair.

    Returns (private_key_pem, public_key_pem).
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv_pem, pub_pem


def _build_signing_string(
    method: str,
    path: str,
    host: str,
    date: str,
    digest: str | None = None,
) -> str:
    """Assemble the string that must be signed."""
    lines = [
        f"(request-target): {method.lower()} {path}",
        f"host: {host}",
        f"date: {date}",
    ]
    if digest:
        lines.append(f"digest: {digest}")
    return "\n".join(lines)


def _public_key_from_pem(pem: str):
    """Load an RSA public key from a PEM string."""
    return serialization.load_pem_public_key(pem.encode())


def _private_key_from_pem(pem: str):
    """Load an RSA private key from a PEM string."""
    return serialization.load_pem_private_key(pem.encode(), password=None)


def sign_request(
    method: str,
    url: str,
    body: bytes,
    key_id: str,
    private_key_pem: str,
) -> dict[str, str]:
    """Sign an outbound HTTP request.

    Returns a dict of headers to add (``Date``, ``Digest``, ``Signature``).
    """
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    # The signature covers the Host header exactly as the HTTP client sends
    # it: the hostname, plus the port when it is not the scheme's default.
    # (urlparse().hostname strips the port, which made verification fail
    # against servers on non-standard ports — e.g. the two-instance
    # federation smoke test on ports 8000/8001.)
    host = parsed.hostname or "localhost"
    if parsed.port is not None and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        host = f"{host}:{parsed.port}"

    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    # Actually compute the digest of the body
    digest_obj = hashes.Hash(hashes.SHA256())
    digest_obj.update(body)
    digest_b64 = base64.b64encode(digest_obj.finalize()).decode()

    signing_string = _build_signing_string(
        method, path, host, date, f"SHA-256={digest_b64}"
    )

    private_key = _private_key_from_pem(private_key_pem)
    assert isinstance(private_key, RSAPrivateKey)
    signature_bytes = private_key.sign(
        signing_string.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = base64.b64encode(signature_bytes).decode()

    signature_header = (
        f'keyId="{key_id}",'
        f'algorithm="rsa-sha256",'
        f'headers="(request-target) host date digest",'
        f'signature="{signature_b64}"'
    )

    return {
        "Date": date,
        "Digest": f"SHA-256={digest_b64}",
        "Signature": signature_header,
    }


def parse_signature_header(signature: str) -> dict[str, str]:
    """Parse a ``Signature`` header into its ``key="value"`` components."""
    parts: dict[str, str] = {}
    for part in signature.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        parts[key.strip()] = value.strip().strip('"')
    return parts


def verify_signature(
    method: str,
    path: str,
    headers: dict[str, str],
    public_key_pem: str,
    body: bytes | None = None,
    max_age_seconds: int = 12 * 3600,
) -> bool:
    """Verify an inbound signed request.

    ``headers`` should be a case-insensitive dict. When ``body`` is given,
    the ``Digest`` header must be its SHA-256 — otherwise the signature
    would not cover the payload. ``Date`` must be within
    ``max_age_seconds`` of now, bounding replay of captured requests.
    """
    # Normalise to lower-case keys
    lower_headers: dict[str, str] = {k.lower(): v for k, v in headers.items()}

    try:
        signature = lower_headers["signature"]
        date = lower_headers["date"]
    except KeyError:
        return False

    # Reject stale or unparsable dates (replay window).
    try:
        date_dt = parsedate_to_datetime(date)
    except (TypeError, ValueError):
        return False
    if date_dt.tzinfo is None:
        date_dt = date_dt.replace(tzinfo=timezone.utc)
    age = abs((datetime.now(timezone.utc) - date_dt).total_seconds())
    if age > max_age_seconds:
        return False

    host = lower_headers.get("host", "")
    digest = lower_headers.get("digest", "")

    # Bind the signature to the payload: the Digest header must match the
    # actual request body.
    if body is not None:
        if not digest:
            return False
        algo, _, claimed = digest.partition("=")
        if algo.strip().lower() != "sha-256":
            return False
        digest_obj = hashes.Hash(hashes.SHA256())
        digest_obj.update(body)
        actual = base64.b64encode(digest_obj.finalize()).decode()
        if claimed.strip() != actual:
            return False

    # Extract signature components
    sig_parts = parse_signature_header(signature)

    signature_b64 = sig_parts.get("signature", "")

    signing_string = _build_signing_string(method, path, host, date, digest)

    try:
        public_key = _public_key_from_pem(public_key_pem)
        assert isinstance(public_key, RSAPublicKey)
        signature_bytes = base64.b64decode(signature_b64)
        public_key.verify(
            signature_bytes,
            signing_string.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
