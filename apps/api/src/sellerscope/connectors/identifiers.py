"""Marketplace product identifier parsing and FORMAT validation.

Format validation only says an identifier is well-formed. Whether the product exists on the
marketplace is checked later through the authorized API (Catalog Items, milestone M7), so a
format-valid product is stored with identifier_status = "format_valid", never "verified".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
ISBN10_RE = re.compile(r"^[0-9]{9}[0-9X]$")
# Product-page path shapes on Amazon sites.
_URL_ASIN_RE = re.compile(
    r"/(?:dp|gp/product|gp/aw/d|product|exec/obidos/asin)/([A-Za-z0-9]{10})(?=[/?#]|$)",
    re.IGNORECASE,
)
AMAZON_IN_HOSTS = frozenset({"amazon.in", "www.amazon.in", "m.amazon.in"})
SHORT_LINK_HOSTS = frozenset({"amzn.in", "amzn.to", "a.co"})


class MarketplaceCode(StrEnum):
    AMAZON_IN = "amazon_in"


SUPPORTED_MARKETPLACES = tuple(MarketplaceCode)


class IdentifierError(StrEnum):
    EMPTY = "empty"
    INVALID_FORMAT = "invalid_format"
    URL_WITHOUT_ASIN = "url_without_asin"
    SHORT_LINK = "short_link_not_supported"
    NOT_AN_AMAZON_URL = "not_an_amazon_url"
    UNSUPPORTED_MARKETPLACE = "unsupported_marketplace"


ERROR_MESSAGES: dict[IdentifierError, str] = {
    IdentifierError.EMPTY: "Enter an ASIN or an Amazon.in product link.",
    IdentifierError.INVALID_FORMAT: "An ASIN is exactly 10 letters or digits (e.g. B0CHX1W1XY).",
    IdentifierError.URL_WITHOUT_ASIN: (
        "No ASIN found in this link. Use a product page link (…/dp/ASIN)."
    ),
    IdentifierError.SHORT_LINK: (
        "Short links (amzn.in, amzn.to) can't be read without visiting them. "
        "Open the link and paste the full product page address or the ASIN."
    ),
    IdentifierError.NOT_AN_AMAZON_URL: "This is not an Amazon product link.",
    IdentifierError.UNSUPPORTED_MARKETPLACE: "Only Amazon.in is supported at the moment.",
}


class IdentifierWarning(StrEnum):
    NON_INDIA_AMAZON_URL = "non_india_amazon_url"
    UNUSUAL_ASIN_FORMAT = "unusual_asin_format"
    ISBN_CHECKSUM_MISMATCH = "isbn_checksum_mismatch"


WARNING_MESSAGES: dict[IdentifierWarning, str] = {
    IdentifierWarning.NON_INDIA_AMAZON_URL: (
        "This link is from another Amazon site. The same ASIN may not exist on Amazon.in."
    ),
    IdentifierWarning.UNUSUAL_ASIN_FORMAT: (
        "Most ASINs start with 'B' (or are ISBN-10 numbers for books). Double-check this one."
    ),
    IdentifierWarning.ISBN_CHECKSUM_MISMATCH: (
        "This looks like a book ISBN-10 but its check digit doesn't match. Double-check it."
    ),
}


@dataclass(frozen=True, slots=True)
class IdentifierValidation:
    raw: str
    normalized: str | None
    error: IdentifierError | None = None
    warnings: tuple[IdentifierWarning, ...] = field(default_factory=tuple)
    from_url: bool = False

    @property
    def valid(self) -> bool:
        return self.error is None and self.normalized is not None


def _isbn10_checksum_ok(value: str) -> bool:
    total = sum((10 - i) * int(ch) for i, ch in enumerate(value[:9]))
    check = 10 if value[9] == "X" else int(value[9])
    return (total + check) % 11 == 0


def _validate_asin(
    asin: str, raw: str, *, from_url: bool, warnings: list[IdentifierWarning]
) -> IdentifierValidation:
    if not ASIN_RE.match(asin):
        return IdentifierValidation(raw, None, IdentifierError.INVALID_FORMAT, from_url=from_url)
    if ISBN10_RE.match(asin):
        if not _isbn10_checksum_ok(asin):
            warnings.append(IdentifierWarning.ISBN_CHECKSUM_MISMATCH)
    elif not asin.startswith("B"):
        warnings.append(IdentifierWarning.UNUSUAL_ASIN_FORMAT)
    return IdentifierValidation(raw, asin, None, tuple(warnings), from_url)


def parse_asin(raw: str) -> IdentifierValidation:
    """Accepts a bare ASIN (any case, surrounding spaces) or an Amazon product-page URL."""
    value = (raw or "").strip()
    if not value:
        return IdentifierValidation(raw, None, IdentifierError.EMPTY)

    looks_like_url = "/" in value or "." in value
    if not looks_like_url:
        return _validate_asin(value.upper(), raw, from_url=False, warnings=[])

    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        return IdentifierValidation(raw, None, IdentifierError.SHORT_LINK, from_url=True)
    if not (host == "amazon.in" or host.endswith(".amazon.in") or "amazon." in host):
        return IdentifierValidation(raw, None, IdentifierError.NOT_AN_AMAZON_URL, from_url=True)

    warnings: list[IdentifierWarning] = []
    if host not in AMAZON_IN_HOSTS:
        warnings.append(IdentifierWarning.NON_INDIA_AMAZON_URL)
    match = _URL_ASIN_RE.search(parsed.path)
    if not match:
        return IdentifierValidation(raw, None, IdentifierError.URL_WITHOUT_ASIN, from_url=True)
    return _validate_asin(match.group(1).upper(), raw, from_url=True, warnings=warnings)


def parse_identifier(marketplace: str, raw: str) -> IdentifierValidation:
    if marketplace == MarketplaceCode.AMAZON_IN:
        return parse_asin(raw)
    return IdentifierValidation(raw, None, IdentifierError.UNSUPPORTED_MARKETPLACE)
