"""Time-ordered UUIDv7 identifiers (RFC 9562). PostgreSQL 16 has no native generator.

IDs from one process are strictly increasing, even within the same millisecond (the random
part is incremented, RFC 9562 §6.2 method 2), so rows inserted together keep their order.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_TS_MASK = (1 << 48) - 1
_RAND_BITS = 74
_RAND_MASK = (1 << _RAND_BITS) - 1
_lock = threading.Lock()
_last_ts = -1
_last_rand = 0


def uuid7() -> uuid.UUID:
    global _last_ts, _last_rand
    with _lock:
        ts_ms = time.time_ns() // 1_000_000
        if ts_ms > _last_ts:
            _last_ts, _last_rand = ts_ms, secrets.randbits(_RAND_BITS - 1)  # headroom to count
        else:
            _last_rand += 1 + secrets.randbelow(1 << 16)
            if _last_rand > _RAND_MASK:  # counter overflow: borrow the next millisecond
                _last_ts, _last_rand = _last_ts + 1, secrets.randbits(_RAND_BITS - 1)
        ts, rand = _last_ts, _last_rand
    rand_a, rand_b = rand >> 62, rand & ((1 << 62) - 1)
    value = ((ts & _TS_MASK) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
