"""Tests for HTTP Signature signing and verification."""

import unittest

from app.activitypub.signing import generate_keypair, sign_request, verify_signature


class TestKeypairGeneration(unittest.TestCase):
    def test_generate_keypair_returns_pem_strings(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, str)
        assert isinstance(pub, str)
        assert "BEGIN PRIVATE KEY" in priv
        assert "BEGIN PUBLIC KEY" in pub

    def test_generate_keypair_unique(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestSignAndVerify(unittest.TestCase):
    def test_sign_and_verify_roundtrip(self):
        priv, pub = generate_keypair()
        body = b'{"type":"Create","actor":"https://example.com/actor/alice"}'
        url = "https://remote.example.com/actor/bob/inbox"

        headers = sign_request(
            method="POST",
            url=url,
            body=body,
            key_id="https://example.com/actor/alice#main-key",
            private_key_pem=priv,
        )

        assert "Date" in headers
        assert "Digest" in headers
        assert "Signature" in headers
        assert "rsa-sha256" in headers["Signature"]
        assert "keyId=" in headers["Signature"]

        # Verify with the public key
        ok = verify_signature(
            method="POST",
            path="/actor/bob/inbox",
            headers={
                "host": "remote.example.com",
                "date": headers["Date"],
                "digest": headers["Digest"],
                "signature": headers["Signature"],
            },
            public_key_pem=pub,
        )
        assert ok is True

    def test_verify_fails_with_wrong_key(self):
        priv1, _pub1 = generate_keypair()
        _priv2, pub2 = generate_keypair()
        body = b'{"type":"Create"}'
        url = "https://remote.example.com/inbox"

        headers = sign_request(
            method="POST",
            url=url,
            body=body,
            key_id="https://example.com/actor/alice#main-key",
            private_key_pem=priv1,
        )

        ok = verify_signature(
            method="POST",
            path="/inbox",
            headers={
                "host": "remote.example.com",
                "date": headers["Date"],
                "digest": headers["Digest"],
                "signature": headers["Signature"],
            },
            public_key_pem=pub2,
        )
        assert ok is False

    def test_verify_fails_with_missing_headers(self):
        _priv, pub = generate_keypair()
        ok = verify_signature(
            method="POST",
            path="/inbox",
            headers={},
            public_key_pem=pub,
        )
        assert ok is False

    def test_verify_fails_with_tampered_path(self):
        priv, pub = generate_keypair()
        body = b'{"type":"Create"}'
        url = "https://remote.example.com/inbox"

        headers = sign_request(
            method="POST",
            url=url,
            body=body,
            key_id="https://example.com/actor/alice#main-key",
            private_key_pem=priv,
        )

        # Verify with a different path
        ok = verify_signature(
            method="POST",
            path="/different-path",
            headers={
                "host": "remote.example.com",
                "date": headers["Date"],
                "digest": headers["Digest"],
                "signature": headers["Signature"],
            },
            public_key_pem=pub,
        )
        assert ok is False

    def test_sign_includes_query_string_in_path(self):
        priv, pub = generate_keypair()
        body = b"{}"
        url = "https://remote.example.com/inbox?foo=bar"

        headers = sign_request(
            method="POST",
            url=url,
            body=body,
            key_id="https://example.com/actor/alice#main-key",
            private_key_pem=priv,
        )

        ok = verify_signature(
            method="POST",
            path="/inbox?foo=bar",
            headers={
                "host": "remote.example.com",
                "date": headers["Date"],
                "digest": headers["Digest"],
                "signature": headers["Signature"],
            },
            public_key_pem=pub,
        )
        assert ok is True

    def test_sign_includes_non_default_port_in_host(self):
        """The signed Host header must match what the HTTP client sends.

        Servers on non-standard ports (e.g. the two-instance federation
        smoke test on 8000/8001) send `Host: host:port` — the signature
        has to cover the port too, or verification fails.
        """
        priv, pub = generate_keypair()
        body = b'{"type":"Create"}'
        url = "http://localhost:8001/actor/bob/inbox"

        headers = sign_request(
            method="POST",
            url=url,
            body=body,
            key_id="http://localhost:8000/actor/alice#main-key",
            private_key_pem=priv,
        )

        ok = verify_signature(
            method="POST",
            path="/actor/bob/inbox",
            headers={
                "host": "localhost:8001",
                "date": headers["Date"],
                "digest": headers["Digest"],
                "signature": headers["Signature"],
            },
            public_key_pem=pub,
        )
        assert ok is True
