from __future__ import annotations

import hashlib


def hash_customer_identifier(raw_identifier: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{raw_identifier}".encode()).hexdigest()


def ltv_band_from_identifier(raw_identifier: str, salt: str) -> str:
    bucket = int(hash_customer_identifier(raw_identifier, salt)[:8], 16) % 100
    if bucket < 50:
        return "low"
    if bucket < 85:
        return "medium"
    return "high"
