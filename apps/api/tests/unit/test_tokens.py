"""Access-token verification: valid tokens, every rejection path, JWKS and HS256."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from sellerscope.auth.tokens import TokenVerifier
from sellerscope.core.config import AppEnv, Settings
from sellerscope.core.errors import AppError

ISSUER = "http://auth.test/auth/v1"
SECRET = "unit-test-hs256-secret-at-least-32-bytes-long"


def claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "email": "Alice@Example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "exp": int(time.time()) + 600,
        "iat": int(time.time()),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def hs_verifier() -> TokenVerifier:
    return TokenVerifier(
        Settings(app_env=AppEnv.TEST, auth_jwt_issuer=ISSUER, auth_jwt_secret=SECRET)  # type: ignore[arg-type]
    )


async def test_valid_hs256_token() -> None:
    c = claims()
    result = await hs_verifier().verify(jwt.encode(c, SECRET, algorithm="HS256"))
    assert str(result.user_id) == c["sub"]
    assert result.email == "alice@example.com"  # normalised


@pytest.mark.parametrize(
    ("payload", "key", "reason"),
    [
        (claims(exp=int(time.time()) - 120), SECRET, "expired"),
        (claims(), "wrong-secret-wrong-secret-wrong-secret!!", "Invalid token"),
        (claims(aud="something-else"), SECRET, "Invalid token"),
        (claims(iss="http://evil.test"), SECRET, "Invalid token"),
        (claims(role="anon"), SECRET, "not a user session"),
        (claims(role="service_role"), SECRET, "not a user session"),
        (claims(is_anonymous=True), SECRET, "not a user session"),
        (claims(email=None), SECRET, "no email"),
        (claims(sub="not-a-uuid"), SECRET, "Invalid subject"),
        (claims(exp=None), SECRET, "Invalid token"),
    ],
)
async def test_rejected_hs256_tokens(payload: dict[str, Any], key: str, reason: str) -> None:
    with pytest.raises(AppError) as err:
        await hs_verifier().verify(jwt.encode(payload, key, algorithm="HS256"))
    assert err.value.status == 401
    assert reason.lower() in (err.value.detail or "").lower()


async def test_alg_none_rejected() -> None:
    token = jwt.encode(claims(), key=None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(AppError, match="Unsupported"):
        await hs_verifier().verify(token)


async def test_malformed_token_rejected() -> None:
    with pytest.raises(AppError, match="Malformed"):
        await hs_verifier().verify("not.a.jwt")


async def test_unconfigured_verifier_returns_503() -> None:
    with pytest.raises(AppError) as err:
        await TokenVerifier(Settings(app_env=AppEnv.TEST)).verify("x.y.z")
    assert err.value.status == 503


# --------------------------------------------------------------------------- JWKS (ES256)


@pytest.fixture(scope="module")
def jwks_server() -> Iterator[tuple[str, ec.EllipticCurvePrivateKey]]:
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "test-key", "alg": "ES256", "use": "sig"})
    body = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/.well-known/jwks.json", key
    server.shutdown()


def jwks_verifier(url: str, *, with_secret: bool = False) -> TokenVerifier:
    return TokenVerifier(
        Settings(
            app_env=AppEnv.TEST,
            auth_jwt_issuer=ISSUER,
            auth_jwks_url=url,
            auth_jwt_secret=SECRET if with_secret else None,  # type: ignore[arg-type]
        )
    )


async def test_valid_es256_token_via_jwks(
    jwks_server: tuple[str, ec.EllipticCurvePrivateKey],
) -> None:
    url, key = jwks_server
    token = jwt.encode(claims(), key, algorithm="ES256", headers={"kid": "test-key"})
    assert (await jwks_verifier(url).verify(token)).email == "alice@example.com"


async def test_es256_token_signed_by_unknown_key_rejected(
    jwks_server: tuple[str, ec.EllipticCurvePrivateKey],
) -> None:
    url, _ = jwks_server
    other = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(claims(), other, algorithm="ES256", headers={"kid": "test-key"})
    with pytest.raises(AppError, match="Invalid token"):
        await jwks_verifier(url).verify(token)


async def test_hs256_rejected_when_only_jwks_configured(
    jwks_server: tuple[str, ec.EllipticCurvePrivateKey],
) -> None:
    """Algorithm-confusion guard: an HS256 token is not accepted by a JWKS-only verifier."""
    url, _ = jwks_server
    token = jwt.encode(claims(), SECRET, algorithm="HS256")
    with pytest.raises(AppError, match="Unsupported"):
        await jwks_verifier(url).verify(token)
