from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from bot.config import settings

# Derive a cryptographically secure key signature wrapper from the primary bot credentials
_SIGNING_KEY = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
_HASH_PREFIX = "file_"
_HASH_LENGTH = 20


def generate_file_hash() -> str:
    """Generates a cryptographically strong, secure, and unique hex token prefix mapping string."""
    return f"{_HASH_PREFIX}{secrets.token_hex(_HASH_LENGTH)}"


def sign_payload(payload: str) -> str:
    """
    Computes an HMAC-SHA256 signature payload constraint for integrity verification.
    
    Appends a truncated hex digest checksum to prevent client-side parameter tampering.
    """
    sig = hmac.new(_SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def verify_signed_payload(signed: str) -> tuple[bool, str]:
    """
    Validates structural tracking integrity of signed inbound parameters using constant-time comparison.
    
    Protects downstream routing protocols against timing attacks and data modification.
    """
    try:
        payload, sig = signed.rsplit(".", 1)
    except ValueError:
        return False, ""

    expected_sig = hmac.new(
        _SIGNING_KEY, payload.encode(), hashlib.sha256
    ).hexdigest()[:16]

    # Utilize constant-time comparison to evaluate signature flags safely
    if not hmac.compare_digest(sig, expected_sig):
        return False, ""

    return True, payload


def generate_deep_link(file_hash: str, bot_username: str) -> str:
    """Constructs the absolute target uniform resource locator for Telegram deep-linking schemes."""
    return f"https://t.me/{bot_username}?start={file_hash}"