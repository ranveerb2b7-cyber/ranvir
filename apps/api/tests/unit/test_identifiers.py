import pytest

from sellerscope.connectors.identifiers import (
    IdentifierError,
    IdentifierWarning,
    parse_asin,
    parse_identifier,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("B0CHX1W1XY", "B0CHX1W1XY"),
        ("  b0chx1w1xy \n", "B0CHX1W1XY"),
        ("https://www.amazon.in/dp/B0CHX1W1XY", "B0CHX1W1XY"),
        (
            "https://www.amazon.in/Apple-iPhone-15-128-GB/dp/B0CHX1W1XY/ref=sr_1_1?crid=X",
            "B0CHX1W1XY",
        ),
        ("amazon.in/dp/B0CHX1W1XY", "B0CHX1W1XY"),
        ("https://m.amazon.in/gp/product/B0CHX1W1XY?psc=1", "B0CHX1W1XY"),
        ("https://www.amazon.in/gp/aw/d/B0CHX1W1XY", "B0CHX1W1XY"),
        ("https://www.amazon.in/product/b0chx1w1xy#reviews", "B0CHX1W1XY"),
        ("8172234988", "8172234988"),  # ISBN-10 (valid check digit)
    ],
)
def test_valid_asins(raw: str, expected: str) -> None:
    result = parse_asin(raw)
    assert result.valid, result
    assert result.normalized == expected


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("", IdentifierError.EMPTY),
        ("   ", IdentifierError.EMPTY),
        ("B0CHX1W1X", IdentifierError.INVALID_FORMAT),  # 9 chars
        ("B0CHX1W1XYZ", IdentifierError.INVALID_FORMAT),  # 11 chars
        ("B0CHX-W1XY", IdentifierError.INVALID_FORMAT),
        ("https://www.amazon.in/s?k=iphone", IdentifierError.URL_WITHOUT_ASIN),
        ("https://www.amazon.in/dp/B0CHX1W1XYZ", IdentifierError.URL_WITHOUT_ASIN),
        ("https://amzn.in/d/abc123", IdentifierError.SHORT_LINK),
        ("https://amzn.to/3xyz", IdentifierError.SHORT_LINK),
        (
            "https://www.flipkart.com/p/itm123?pid=ABCDEFGHIJKLMNOP",
            IdentifierError.NOT_AN_AMAZON_URL,
        ),
        ("https://evil.example/dp/B0CHX1W1XY", IdentifierError.NOT_AN_AMAZON_URL),
    ],
)
def test_invalid_inputs(raw: str, error: IdentifierError) -> None:
    result = parse_asin(raw)
    assert not result.valid
    assert result.error == error
    assert result.normalized is None


def test_other_amazon_site_is_accepted_with_warning() -> None:
    result = parse_asin("https://www.amazon.com/dp/B0CHX1W1XY")
    assert result.valid
    assert result.warnings == (IdentifierWarning.NON_INDIA_AMAZON_URL,)


def test_unusual_format_warns_but_is_accepted() -> None:
    result = parse_asin("A123456789")
    assert result.valid
    assert result.warnings == (IdentifierWarning.UNUSUAL_ASIN_FORMAT,)


def test_isbn_with_bad_check_digit_warns() -> None:
    result = parse_asin("8172234981")
    assert result.valid
    assert result.warnings == (IdentifierWarning.ISBN_CHECKSUM_MISMATCH,)


def test_unsupported_marketplace() -> None:
    assert parse_identifier("flipkart", "ABC").error == IdentifierError.UNSUPPORTED_MARKETPLACE
