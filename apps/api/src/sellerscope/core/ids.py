"""Time-ordered UUIDv7 identifiers (RFC 9562). PostgreSQL 16 has no native generator."""

from __future__ import annotations

import secrets
import time
import uuid

_TS_MASK = (1 << 48) - 1
_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> uuid.UUID:
    ts_ms = time.time_ns() // 1_000_000
    rand = secrets.randbits(74)
    rand_a = rand >> 62
    rand_b = rand & _RAND_B_MASK
    value = ((ts_ms & _TS_MASK) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
