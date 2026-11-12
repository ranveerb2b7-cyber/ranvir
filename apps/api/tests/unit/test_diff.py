"""Table-driven tests for change detection (scanning/diff.py)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from sellerscope.connectors.mock import MockConnector
from sellerscope.scanning.diff import OfferView, SnapshotView, diff

SELLERS = {name: uuid.uuid5(uuid.NAMESPACE_DNS, name) for name in "ABCDE"}


def snap(
    sellers: str = "",
    *,
    status: str = "ok",
    total: int | None = -1,
    truncated: bool | None = False,
    prices: dict[str, str] | None = None,
    buy_box: str | None = None,
    ids_known: bool = True,
) -> SnapshotView:
    prices = prices or {}
    offers = [
        OfferView(
            SELLERS[s] if ids_known else None,
            s if ids_known else None,
            Decimal(prices.get(s, "100")),
            "INR",
            s == buy_box,
        )
        for s in sellers
    ]
    return SnapshotView(
        uuid.uuid4(),
        status,
        len(sellers) if total == -1 else total,
        truncated,
        len(set(sellers)) if ids_known else None,
        offers,
    )


def kinds(changes: list) -> list[tuple[str, str | None, str | None]]:  # type: ignore[type-arg]
    names = {v: k for k, v in SELLERS.items()}
    return [
        (
            c.event_type.value,
            names.get(c.seller_profile_id),
            c.confidence.value if c.confidence else None,
        )
        for c in changes
    ]


CASES = [
    ("first scan is a baseline", None, snap("AB"), "ok", []),
    ("identical scans", snap("AB"), snap("AB"), "ok", []),
    (
        "new seller, complete lists",
        snap("AB"),
        snap("ABC"),
        "ok",
        [("offer_count_changed", None, "high"), ("seller_newly_observed", "C", "high")],
    ),
    (
        "new seller but previous list was truncated: medium confidence",
        snap("AB", total=30, truncated=True),
        snap("ABC", total=30, truncated=True),
        "partial",
        [("seller_newly_observed", "C", "medium")],
    ),
    (
        "seller gone from a COMPLETE list: no longer observed",
        snap("ABC"),
        snap("AB"),
        "ok",
        [("offer_count_changed", None, "high"), ("seller_no_longer_observed", "C", "high")],
    ),
    (
        "seller missing from a TRUNCATED list: inconclusive, never 'gone'",
        snap("ABC", total=40, truncated=True),
        snap("AB", total=40, truncated=True),
        "partial",
        [("seller_not_observed_inconclusive", "C", "low")],
    ),
    (
        "completeness unknown: inconclusive",
        snap("ABC"),
        snap("AB", total=None, truncated=None),
        "ok",
        [("seller_not_observed_inconclusive", "C", "low")],
    ),
    (
        "seller ids missing in new scan: no seller events at all",
        snap("ABC"),
        snap("AB", ids_known=False),
        "ok",
        [("offer_count_changed", None, "high")],
    ),
    (
        "seller ids missing in old scan: no seller events at all",
        snap("AB", ids_known=False),
        snap("ABC"),
        "ok",
        [("offer_count_changed", None, "high")],
    ),
    (
        "unknown total offer count is not a change",
        snap("AB", total=None, truncated=None),
        snap("AB", total=7),
        "ok",
        [],
    ),
    (
        "price change for the same seller",
        snap("AB", prices={"A": "100"}),
        snap("AB", prices={"A": "90"}),
        "ok",
        [("price_changed", "A", "high")],
    ),
    (
        "buy box moves",
        snap("AB", buy_box="A"),
        snap("AB", buy_box="B"),
        "ok",
        [("buy_box_changed", "B", "high")],
    ),
    ("unknown buy box is not a change", snap("AB", buy_box="A"), snap("AB"), "ok", []),
    (
        "product becomes unavailable: one event, no seller events",
        snap("ABC"),
        snap("", status="unavailable", total=None, truncated=None),
        "ok",
        [("scan_unavailable", None, None)],
    ),
    (
        "still unavailable: no repeated event",
        snap("ABC"),
        snap("", status="not_found", total=None, truncated=None),
        "unavailable",
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "previous", "current", "last_status", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_diff_rules(
    name: str,
    previous: SnapshotView | None,
    current: SnapshotView,
    last_status: str,
    expected: list[tuple[str, str | None, str | None]],
) -> None:
    assert kinds(diff(previous, current, last_status)) == expected


def test_price_change_values_are_recorded() -> None:
    [change] = diff(snap("A", prices={"A": "100"}), snap("A", prices={"A": "120.5"}), "ok")
    assert change.old_value == {"seller_id": "A", "price": "100.00", "currency": "INR"}
    assert change.new_value == {"seller_id": "A", "price": "120.50", "currency": "INR"}


def test_mock_drift_rotates_sellers_between_epochs() -> None:
    connector = MockConnector()
    for i in range(500):
        asin = f"B0DRIFT{i:03d}"
        first, second = connector.snapshot(asin, 0), connector.snapshot(asin, 1)
        if first.status == "ok" and first.total_offer_count and first.total_offer_count > 1:
            a = {o.seller_id for o in first.offers}
            b = {o.seller_id for o in second.offers}
            assert a != b and len(a) == len(b)
            assert first.total_offer_count == len(first.offers)  # never inconsistent
            assert connector.snapshot(asin, 0).offers == first.offers  # deterministic
            return
    raise AssertionError("no drifting listing found")
