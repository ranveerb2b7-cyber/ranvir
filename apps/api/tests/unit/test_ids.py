import time
import uuid

from sellerscope.core.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_uuid7_embeds_current_millisecond_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    u = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= (u.int >> 80) <= after


def test_uuid7_is_time_ordered_across_milliseconds() -> None:
    a = uuid7()
    time.sleep(0.002)
    b = uuid7()
    assert a < b


def test_uuid7_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_uuid7_strictly_increasing_within_a_millisecond() -> None:
    ids = [uuid7() for _ in range(5_000)]
    assert ids == sorted(ids)
    assert all(u.version == 7 for u in ids)
